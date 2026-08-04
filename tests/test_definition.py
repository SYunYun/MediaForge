"""Tests for definition.py — YAML card parsing & config merging."""

from pathlib import Path

import pytest

from mediaforge.cardigann.definition import (
    DefinitionError,
    load_definition,
    parse_definition,
)

FIXTURE = Path(__file__).parent / "fixtures" / "yts.yml"


class TestYtsCard:
    def test_parse_basics(self):
        d = load_definition(str(FIXTURE))
        assert d.id == "yts"
        assert d.name == "YTS"
        assert d.type == "public"
        assert d.links[0] == "https://yts.gg/"
        assert "https://yts.mx/" in d.legacylinks

    def test_settings_and_defaults(self):
        d = load_definition(str(FIXTURE))
        assert len(d.settings) == 1
        s = d.settings[0]
        assert s.name == "apiurl" and s.default == "movies-api.accel.li"

    def test_build_config_merges_user_values(self):
        d = load_definition(str(FIXTURE))
        cfg = d.build_config()
        assert cfg["apiurl"] == "movies-api.accel.li"
        assert cfg["sitelink"] == "https://yts.gg/"
        cfg2 = d.build_config({"apiurl": "mirror.example.com"})
        assert cfg2["apiurl"] == "mirror.example.com"

    def test_search_block(self):
        d = load_definition(str(FIXTURE))
        s = d.search
        assert s is not None
        assert s.paths[0].response_type == "json"
        assert "{{ .Config.apiurl }}" in s.paths[0].path
        assert s.inputs["limit"] == 50
        assert s.keywordsfilters[0]["name"] == "re_replace"
        assert s.rows.selector == "data.movies"
        assert s.rows.attribute == "torrents"
        assert s.rows.multiple is True
        assert s.rows.missing_attribute_equals_no_results is True

    def test_fields_order_and_attrs(self):
        d = load_definition(str(FIXTURE))
        names = [f.name for f in d.search.fields]
        assert names[0] == "_quality"
        assert "title" in names and "infohash" in names
        cat = next(f for f in d.search.fields if f.name == "category")
        assert cat.case["1080p"] == 44 and cat.case["*"] == 45
        dvf = next(f for f in d.search.fields if f.name == "downloadvolumefactor")
        assert dvf.text == 0


class TestErrors:
    def test_missing_id(self):
        with pytest.raises(DefinitionError):
            parse_definition("name: nope\n")

    def test_non_dict(self):
        with pytest.raises(DefinitionError):
            parse_definition("- just\n- a\n- list\n")
