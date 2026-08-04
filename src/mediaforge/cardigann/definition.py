"""Cardigann YAML definition loader.

把 Jackett/Prowlarr 的 YAML 卡解析成 Definition dataclass，
settings 段的 default 与用户配置在此合并（build_config）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import yaml


class DefinitionError(Exception):
    """Raised on malformed or unsupported definitions."""


@dataclass
class Setting:
    name: str
    type: str = "text"
    label: str = ""
    default: Any = None
    values: dict = field(default_factory=dict)


@dataclass
class SearchPath:
    path: str
    response_type: str = "json"  # "json" | "html"
    method: str = "get"
    inputs: dict = field(default_factory=dict)


@dataclass
class RowsSpec:
    selector: str = ""
    attribute: Optional[str] = None
    multiple: bool = False
    missing_attribute_equals_no_results: bool = False
    count_selector: Optional[str] = None


@dataclass
class FieldSpec:
    name: str
    selector: Optional[str] = None
    attribute: Optional[str] = None
    optional: bool = False
    default: Any = None
    case: Optional[dict] = None
    filters: list = field(default_factory=list)
    text: Any = None  # static value


@dataclass
class SearchSpec:
    paths: list = field(default_factory=list)  # list[SearchPath]
    inputs: dict = field(default_factory=dict)
    keywordsfilters: list = field(default_factory=list)
    rows: Optional[RowsSpec] = None
    fields: list = field(default_factory=list)  # list[FieldSpec], ordered


@dataclass
class Definition:
    id: str
    name: str
    description: str = ""
    type: str = "public"
    language: str = ""
    encoding: str = "UTF-8"
    links: list = field(default_factory=list)
    legacylinks: list = field(default_factory=list)
    settings: list = field(default_factory=list)  # list[Setting]
    caps: dict = field(default_factory=dict)
    search: Optional[SearchSpec] = None
    raw: dict = field(default_factory=dict)

    @property
    def sitelink(self) -> str:
        """Primary site link, guaranteed to end with '/'."""
        link = self.links[0] if self.links else ""
        return link if link.endswith("/") else link + "/"

    def build_config(self, user_config: Optional[dict] = None) -> dict:
        """Merge setting defaults with user-supplied config values."""
        config = {s.name: s.default for s in self.settings}
        for key, value in (user_config or {}).items():
            if value is not None:
                config[key] = value
        config["sitelink"] = self.sitelink
        return config


def _parse_field(name: str, data: Any) -> FieldSpec:
    if not isinstance(data, dict):
        return FieldSpec(name=name, text=data)
    return FieldSpec(
        name=name,
        selector=data.get("selector"),
        attribute=data.get("attribute"),
        optional=bool(data.get("optional", False)),
        default=data.get("default"),
        case=data.get("case"),
        filters=data.get("filters") or [],
        text=data.get("text"),
    )


def parse_definition(text: str) -> Definition:
    """Parse a Cardigann YAML card into a Definition."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "id" not in data:
        raise DefinitionError("not a Cardigann definition (missing 'id')")

    settings = [
        Setting(
            name=s["name"],
            type=s.get("type", "text"),
            label=s.get("label", ""),
            default=s.get("default"),
            values=s.get("values") or {},
        )
        for s in data.get("settings") or []
    ]

    search = None
    sdata = data.get("search")
    if sdata:
        paths = []
        for p in sdata.get("paths") or []:
            pdict: dict = {"path": p} if isinstance(p, str) else dict(p)
            resp = pdict.get("response") or {}
            paths.append(
                SearchPath(
                    path=pdict["path"],
                    response_type=resp.get("type", "json"),
                    method=pdict.get("method", "get"),
                    inputs=pdict.get("inputs") or {},
                )
            )
        rdata = sdata.get("rows") or {}
        rows = RowsSpec(
            selector=rdata.get("selector", ""),
            attribute=rdata.get("attribute"),
            multiple=bool(rdata.get("multiple", False)),
            missing_attribute_equals_no_results=bool(
                rdata.get("missingAttributeEqualsNoResults", False)
            ),
            count_selector=(rdata.get("count") or {}).get("selector"),
        )
        fields = [
            _parse_field(fname, fdata)
            for fname, fdata in (sdata.get("fields") or {}).items()
        ]
        search = SearchSpec(
            paths=paths,
            inputs=sdata.get("inputs") or {},
            keywordsfilters=sdata.get("keywordsfilters") or [],
            rows=rows,
            fields=fields,
        )

    return Definition(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        type=data.get("type", "public"),
        language=data.get("language", ""),
        encoding=data.get("encoding", "UTF-8"),
        links=data.get("links") or [],
        legacylinks=data.get("legacylinks") or [],
        settings=settings,
        caps=data.get("caps") or {},
        search=search,
        raw=data,
    )


def load_definition(path: str) -> Definition:
    """Load a Cardigann YAML card from disk."""
    with open(path, "r", encoding="utf-8") as fh:
        return parse_definition(fh.read())
