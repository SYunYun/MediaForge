"""Cardigann search executor.

给定 Definition + 查询 + 用户配置：
渲染 path/inputs 模板 → requests 请求 → 按 response.type 抽取 rows
（json 走点路径，html 走 CSS 选择器）→ 逐行按 fields 抽取 + 滤镜管道
→ 输出统一 Release dict。
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from . import filters as _filters
from . import template as _template
from .definition import Definition, FieldSpec

# Release dict 的标准键（其余键原样保留在 extra）
RELEASE_KEYS = (
    "title",
    "infohash",
    "download",
    "size",
    "date",
    "seeders",
    "leechers",
    "category",
    "imdbid",
    "poster",
    "details",
    "indexer",
)

DEFAULT_TIMEOUT = 10  # seconds, must stay <= 15 per project rules
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class EngineError(Exception):
    """Raised on request or extraction failures."""


@dataclass
class Query:
    keywords: str = ""
    imdbid: str = ""
    season: Optional[int] = None
    episode: Optional[int] = None


def stripped_proxy_env() -> dict:
    """Return os.environ minus any proxy variables (剥 proxy env 的工具函数)."""
    return {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
    }


def make_session(
    proxy: Optional[str] = None,
    headers: Optional[dict] = None,
    trust_env: bool = False,
) -> requests.Session:
    """Build a requests session.

    trust_env=False 时忽略环境变量里的代理；proxy 显式指定时走该代理
    （如 http://127.0.0.1:7892）。
    """
    session = requests.Session()
    session.trust_env = trust_env
    session.headers.update(DEFAULT_HEADERS)
    if headers:
        session.headers.update(headers)
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


# ---------------------------------------------------------------------------
# Row extraction
# ---------------------------------------------------------------------------


def _dig(obj: Any, path: str) -> Any:
    """Navigate a dot path (e.g. 'data.movies') through dicts/lists."""
    cur = obj
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def _json_rows(payload: Any, rows_spec) -> list:
    """Return [(row, parent)] pairs from a JSON payload."""
    base = _dig(payload, rows_spec.selector)
    if base is None:
        return []
    items = base if isinstance(base, list) else [base]
    out = []
    for item in items:
        if rows_spec.attribute:
            child = item.get(rows_spec.attribute) if isinstance(item, dict) else None
            if child is None:
                if rows_spec.missing_attribute_equals_no_results:
                    continue
                out.append((item, item))
                continue
            if rows_spec.multiple and isinstance(child, list):
                out.extend((c, item) for c in child)
            else:
                out.append((child, item))
        else:
            out.append((item, item))
    return out


def _html_select(element, spec: FieldSpec):
    """Resolve a field selector against a BeautifulSoup element.

    '..' prefix walks to the parent element; otherwise CSS selector.
    """
    selector = spec.selector or ""
    if selector.startswith(".."):
        target = element.parent
        selector = selector[2:]
    else:
        target = element
    if target is None:
        return None
    node = target.select_one(selector) if selector else target
    if node is None:
        return None
    if spec.attribute:
        return node.get(spec.attribute)
    return node.get_text(strip=True)


def _html_rows(soup: BeautifulSoup, rows_spec) -> list:
    """Return [(row_element, parent_element)] pairs from HTML."""
    elements = soup.select(rows_spec.selector)
    out = []
    for el in elements:
        if rows_spec.attribute:
            children = el.select(rows_spec.attribute)
            if not children and rows_spec.missing_attribute_equals_no_results:
                continue
            if rows_spec.multiple:
                out.extend((c, el) for c in children)
            else:
                out.append((children[0], el) if children else (el, el))
        else:
            out.append((el, el))
    return out


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def _extract_fields(
    row: Any,
    parent: Any,
    spec_fields: list,
    context: dict,
    is_json: bool,
) -> dict:
    """Extract every field of one row, in definition order.

    Later fields may reference earlier ones via {{ .Result.x }}.
    """
    result: dict = {}
    for fspec in spec_fields:
        if fspec.text is not None:
            result[fspec.name] = _template.render(fspec.text, {**context, "Result": result})
            continue

        value: Any = None
        if fspec.selector:
            if is_json:
                sel = fspec.selector
                source = row
                if sel.startswith(".."):
                    source = parent
                    sel = sel[2:]
                value = _dig(source, sel)
            else:
                value = _html_select(row, fspec)

        if value is None:
            if fspec.default is not None:
                value = _template.render(
                    fspec.default, {**context, "Result": result}
                )
            elif not fspec.optional:
                value = ""

        if value is None:
            value = ""

        # case mapping (e.g. quality -> category id), before filters
        if fspec.case:
            value = _filters.apply_filter("case", value, fspec.case)

        if fspec.filters:
            ctx = {**context, "Result": result}
            value = _filters.apply_pipeline(
                value,
                fspec.filters,
                render_args=lambda s: _template.render(s, ctx),
            )

        result[fspec.name] = value
    return result


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _normalize_date(value: Any) -> str:
    """unix timestamp (digits) -> ISO date; otherwise pass through."""
    s = str(value).strip()
    if s.isdigit():
        ts = int(s)
        if ts > 10_000_000:  # looks like a unix timestamp
            return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
    return s


def _to_release(fields: dict, indexer_id: str) -> dict:
    release = {
        "title": str(fields.get("title", "")).strip(),
        "infohash": str(fields.get("infohash", "")).lower() or None,
        "download": fields.get("download") or None,
        "size": _coerce_int(fields.get("size")),
        "date": _normalize_date(fields.get("date", "")),
        "seeders": _coerce_int(fields.get("seeders")),
        "leechers": _coerce_int(fields.get("leechers")),
        "category": _coerce_int(fields.get("category")),
        "imdbid": fields.get("imdbid") or None,
        "poster": fields.get("poster") or None,
        "details": fields.get("details") or None,
        "indexer": indexer_id,
    }
    # internal fields (underscore-prefixed) are dropped from the Release
    release["extra"] = {
        k: v for k, v in fields.items() if k not in RELEASE_KEYS and not k.startswith("_")
    }
    return release


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def search(
    definition: Definition,
    query: Query,
    user_config: Optional[dict] = None,
    session: Optional[requests.Session] = None,
    proxy: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> list:
    """Run a search against a Cardigann definition.

    Returns a list of Release dicts (see RELEASE_KEYS).
    """
    if definition.search is None:
        raise EngineError(f"definition {definition.id!r} has no search block")
    if timeout > 15:
        raise EngineError("timeout must be <= 15s (host safety rule)")

    spec = definition.search
    config = definition.build_config(user_config)

    # keywords filters (e.g. re_replace "[^\\w]+" -> " ")
    keywords = _filters.apply_pipeline(query.keywords, spec.keywordsfilters)
    keywords = "" if keywords is None else str(keywords)

    context = {
        "Config": config,
        "Keywords": keywords,
        "Query": {
            "Keywords": keywords,
            "IMDBID": query.imdbid or "",
            "Season": "" if query.season is None else str(query.season),
            "Episode": "" if query.episode is None else str(query.episode),
        },
    }

    if session is None:
        session = make_session(proxy=proxy)

    releases: list = []
    for spath in spec.paths:
        url = _template.render(spath.path, context)
        inputs = dict(spec.inputs)
        inputs.update(spath.inputs)
        params = {
            k: _template.render(v, context) if isinstance(v, str) else v
            for k, v in inputs.items()
        }

        if spath.method.lower() == "post":
            resp = session.post(url, data=params, timeout=timeout)
        else:
            resp = session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()

        is_json = spath.response_type == "json"
        if is_json:
            try:
                payload = resp.json()
            except ValueError as exc:
                raise EngineError(f"invalid JSON from {url}: {exc}") from exc
            rows = _json_rows(payload, spec.rows)
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = _html_rows(soup, spec.rows)

        for row, parent in rows:
            fields = _extract_fields(row, parent, spec.fields, context, is_json)
            release = _to_release(fields, definition.id)
            if release["title"] or release["download"] or release["infohash"]:
                releases.append(release)

    return releases
