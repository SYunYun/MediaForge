"""Go template subset renderer for Cardigann definitions.

Supported syntax:
  {{ .Config.x }} {{ .Query.X }} {{ .Keywords }} {{ .Result.x }}  -- variable interpolation
  {{ if <cond> }}A{{ else }}B{{ end }}                            -- conditionals (nestable)
  Conditions: variable truthiness, eq a b, and ..., or ..., not x
  Values in conditions: variable paths or quoted string/number literals.

手写 tokenizer + 递归解析，不依赖第三方模板引擎。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

_TOKEN_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)


class TemplateError(Exception):
    """Raised on template parse/render failures."""


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass
class _Text:
    text: str


@dataclass
class _Var:
    path: str


@dataclass
class _If:
    cond: list  # token list of the condition expression
    then: list
    otherwise: Optional[list]


@dataclass
class _Call:
    """Go-template function call, e.g. {{ join .Categories "," }}."""

    fn: str
    args: list  # raw arg tokens ('.Path' | '"literal"' | nested)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _tokenize(template: str) -> list:
    """Split a template into ('text', s) and ('action', s) tokens."""
    tokens = []
    pos = 0
    for m in _TOKEN_RE.finditer(template):
        if m.start() > pos:
            tokens.append(("text", template[pos : m.start()]))
        tokens.append(("action", m.group(1).strip()))
        pos = m.end()
    if pos < len(template):
        tokens.append(("text", template[pos:]))
    return tokens


def _split_expr(expr: str) -> list:
    """Split a condition expression on whitespace, respecting quotes."""
    parts = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', expr)
    return parts


def _maybe_call(value: str):
    """If value is a known function call (e.g. 'join .Categories \",\"'), return a
    (call_node, next_token_idx) tuple; else None. Word-boundary check avoids
    mangling plain variables."""
    parts = value.split(None, 1)
    if len(parts) < 2:
        return None
    fn, rest = parts
    if fn not in _FUNCS:
        return None
    return _Call(fn, _split_expr(rest))


def _parse(tokens: list, idx: int = 0, stop: frozenset = frozenset({"else", "end"})):
    """Recursively parse tokens into AST nodes.

    Returns (nodes, next_idx, stop_word).
    """
    nodes = []
    while idx < len(tokens):
        kind, value = tokens[idx]
        if kind == "text":
            nodes.append(_Text(value))
            idx += 1
            continue
        word = value.split(None, 1)[0] if value else ""
        if word in stop:
            return nodes, idx + 1, word
        if word == "if":
            cond = _split_expr(value[len("if") :].strip())
            then_nodes, idx, stop_word = _parse(tokens, idx + 1)
            else_nodes = None
            if stop_word == "else":
                else_nodes, idx, stop_word = _parse(tokens, idx)
                if stop_word != "end":
                    raise TemplateError("expected {{ end }} after {{ else }}")
            nodes.append(_If(cond, then_nodes, else_nodes))
            continue
        if word in ("else", "end"):
            raise TemplateError(f"unexpected {{{{ {word} }}}}")
        call = _maybe_call(value)
        if call is not None:
            nodes.append(call)
        else:
            nodes.append(_Var(value))
        idx += 1
    if stop:
        raise TemplateError("unclosed {{ if }} block")
    return nodes, idx, None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _resolve(path: str, context: dict) -> Any:
    """Resolve a dotted path like .Config.apiurl against the context."""
    path = path.strip()
    if not path.startswith("."):
        raise TemplateError(f"invalid variable path: {path!r}")
    cur: Any = context
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _atom(token: str, context: dict) -> Any:
    """Evaluate a single condition atom: literal or variable path."""
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        return token[1:-1]
    if token.startswith("."):
        return _resolve(token, context)
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value not in ("", "0", "false")
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _eval_cond(cond: list, context: dict) -> bool:
    """Evaluate a condition token list."""
    if not cond:
        return False
    op = cond[0]
    if op == "not":
        if len(cond) < 2:
            raise TemplateError(f"{{{{ if {op} }}}} 缺操作数")
        return not _truthy(_atom(cond[1], context))
    if op == "eq":
        if len(cond) < 3:
            raise TemplateError(f"{{{{ if {op} }}}} 需两个操作数")
        return _atom(cond[1], context) == _atom(cond[2], context)
    if op == "and":
        if len(cond) < 2:
            raise TemplateError(f"{{{{ if {op} }}}} 缺操作数")
        return all(_truthy(_atom(t, context)) for t in cond[1:])
    if op == "or":
        if len(cond) < 2:
            raise TemplateError(f"{{{{ if {op} }}}} 缺操作数")
        return any(_truthy(_atom(t, context)) for t in cond[1:])
    # bare variable / literal truthiness
    return _truthy(_atom(op, context))


def _eval_call(call: "_Call", context: dict) -> str:
    """Evaluate a function call with Go-template semantics (minimal subset)."""
    args = [_atom(a, context) for a in call.args]
    fn = call.fn
    if fn == "join":
        sep = args[1] if len(args) > 1 else " "
        return sep.join(str(x) for x in (args[0] if isinstance(args[0], list) else [args[0]]))
    if fn == "lower":
        return str(args[0]).lower()
    if fn == "upper":
        return str(args[0]).upper()
    if fn == "trim":
        return str(args[0]).strip()
    if fn == "split":
        return str(args[0]).split(args[1]) if len(args) > 1 else [str(args[0])]
    if fn == "replace":
        return str(args[0]).replace(args[1], args[2] if len(args) > 2 else "")
    if fn == "append":
        return str(args[0]) + str(args[1])
    if fn == "prepend":
        return str(args[1]) + str(args[0])
    return ""


_FUNCS = {"join", "lower", "upper", "trim", "split", "replace", "append", "prepend"}


def _render_nodes(nodes: list, context: dict, out: list) -> None:
    for node in nodes:
        if isinstance(node, _Text):
            out.append(node.text)
        elif isinstance(node, _Var):
            value = _resolve(node.path, context)
            out.append("" if value is None else str(value))
        elif isinstance(node, _Call):
            value = _eval_call(node, context)
            out.append("" if value is None else str(value))
        elif isinstance(node, _If):
            branch = node.then if _eval_cond(node.cond, context) else node.otherwise
            if branch:
                _render_nodes(branch, context, out)


def render(template: Any, context: dict) -> str:
    """Render a template string against a context dict.

    Non-string scalars (int/float) pass through str(); None yields "".
    """
    if template is None:
        return ""
    if not isinstance(template, str):
        return str(template)
    if "{{" not in template:
        return template
    nodes, _, _ = _parse(_tokenize(template), stop=frozenset())
    out: list = []
    _render_nodes(nodes, context, out)
    return "".join(out)
