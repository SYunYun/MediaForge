"""Cardigann filter pipeline.

每个滤镜输入字符串（split 例外，产出 list，供 join 消费）输出字符串；
当输入为 list 时，字符串滤镜逐元素应用。
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable, Union

Value = Union[str, list]


class FilterError(Exception):
    """Raised on unknown filter or bad args."""


def _to_list(value: Any) -> list:
    if isinstance(value, list):
        return ["" if v is None else str(v) for v in value]
    return ["" if value is None else str(value)]


def _unwrap(items: list, was_list: bool) -> Value:
    return items if was_list else (items[0] if items else "")


def _f_replace(value: Any, old: str, new: str = "") -> Value:
    was_list = isinstance(value, list)
    return _unwrap([s.replace(old, new) for s in _to_list(value)], was_list)


def _f_re_replace(value: Any, pattern: str, repl: str = "") -> Value:
    was_list = isinstance(value, list)
    rx = re.compile(pattern)
    return _unwrap([rx.sub(repl, s) for s in _to_list(value)], was_list)


def _f_append(value: Any, suffix: str = "") -> Value:
    was_list = isinstance(value, list)
    return _unwrap([s + suffix for s in _to_list(value)], was_list)


def _f_prepend(value: Any, prefix: str = "") -> Value:
    was_list = isinstance(value, list)
    return _unwrap([prefix + s for s in _to_list(value)], was_list)


def _f_trim(value: Any, cutset: "str | None" = None) -> Value:
    was_list = isinstance(value, list)
    if cutset is None:
        items = [s.strip() for s in _to_list(value)]
    else:
        items = [s.strip(cutset) for s in _to_list(value)]
    return _unwrap(items, was_list)


def _f_tolower(value: Any) -> Value:
    was_list = isinstance(value, list)
    return _unwrap([s.lower() for s in _to_list(value)], was_list)


def _f_toupper(value: Any) -> Value:
    was_list = isinstance(value, list)
    return _unwrap([s.upper() for s in _to_list(value)], was_list)


def _f_split(value: Any, sep: str, index: Any = None) -> Value:
    """Split string(s) on sep. With index, return that element; else a list."""
    items = [s.split(sep) for s in _to_list(value)]
    if index is not None:
        idx = int(index)
        picked = [parts[idx] if -len(parts) <= idx < len(parts) else "" for parts in items]
        return _unwrap(picked, isinstance(value, list))
    # flatten when input was a single string
    if not isinstance(value, list):
        return items[0]
    return [p for parts in items for p in parts]


def _f_join(value: Any, sep: str = ", ") -> str:
    return sep.join(_to_list(value))


def _f_case(value: Any, mapping: dict) -> str:
    """Map value through a case table; '*' is the fallback key."""
    key = "" if value is None else str(value)
    if key in mapping:
        return str(mapping[key])
    if "*" in mapping:
        return str(mapping["*"])
    return key


def _f_querystring(value: Any) -> str:
    """URL-encode (application/x-www-form-urlencoded)."""
    return urllib.parse.quote_plus("" if value is None else str(value))


_REGISTRY: dict[str, Callable] = {
    "replace": _f_replace,
    "re_replace": _f_re_replace,
    "append": _f_append,
    "prepend": _f_prepend,
    "trim": _f_trim,
    "tolower": _f_tolower,
    "toupper": _f_toupper,
    "split": _f_split,
    "join": _f_join,
    "case": _f_case,
    "querystring": _f_querystring,
}


def available_filters() -> list:
    return sorted(_REGISTRY)


def apply_filter(name: str, value: Any, args: Any = None) -> Value:
    """Apply one named filter. args may be a scalar, a list, or a dict (case)."""
    fn = _REGISTRY.get(name)
    if fn is None:
        raise FilterError(f"unsupported filter: {name}")
    if args is None:
        return fn(value)
    if isinstance(args, dict):
        return fn(value, args)
    if isinstance(args, (list, tuple)):
        return fn(value, *args)
    return fn(value, args)


def apply_pipeline(value: Any, filters: list, render_args=None) -> Value:
    """Apply a Cardigann filters list to a value.

    render_args: optional callable(str) -> str used to render Go templates
    embedded in filter args (e.g. " ({{ .Result.year }})").
    """
    for spec in filters or []:
        name = spec.get("name")
        args = spec.get("args")
        if render_args is not None:
            if isinstance(args, str):
                args = render_args(args)
            elif isinstance(args, list):
                args = [render_args(a) if isinstance(a, str) else a for a in args]
        value = apply_filter(name, value, args)
    return value
