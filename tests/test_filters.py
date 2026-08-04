"""Tests for the filter pipeline (filters.py)."""

import pytest

from mediaforge.cardigann.filters import (
    FilterError,
    apply_filter,
    apply_pipeline,
    available_filters,
)


class TestBasicFilters:
    def test_replace(self):
        # YTS real: replace [":", ""] on title_long
        assert apply_filter("replace", "Inside Job: 2010", [":", ""]) == "Inside Job 2010"

    def test_re_replace_yts_keywordsfilter(self):
        # YTS real keywordsfilter: re_replace ["[^\\w]+", " "]
        assert apply_filter("re_replace", "america's Next Top Model", ["[^\\w]+", " "]) == (
            "america s Next Top Model"
        )

    def test_re_replace_sitelink(self):
        # YTS real: re_replace ["^https?:\\/\\/yts\\.(mx|lt|bz|gg)\\/", "https://yts.gg/"]
        out = apply_filter(
            "re_replace",
            "https://yts.mx/torrent/download/ABC",
            ["^https?:\\/\\/yts\\.(mx|lt|bz|gg)\\/", "https://yts.gg/"],
        )
        assert out == "https://yts.gg/torrent/download/ABC"

    def test_append(self):
        # YTS real: append " (2010)"
        assert apply_filter("append", "Inside Job", " (2010)") == "Inside Job (2010)"

    def test_prepend(self):
        assert apply_filter("prepend", "Job", "Inside ") == "Inside Job"

    def test_trim(self):
        assert apply_filter("trim", "  padded  ") == "padded"
        assert apply_filter("trim", "xxhelloxx", "x") == "hello"

    def test_tolower(self):
        assert apply_filter("tolower", "ABCdef") == "abcdef"

    def test_toupper(self):
        assert apply_filter("toupper", "ABCdef") == "ABCDEF"

    def test_querystring(self):
        assert apply_filter("querystring", "inside job & co") == "inside+job+%26+co"


class TestSplitJoin:
    def test_split_returns_list(self):
        assert apply_filter("split", "a,b,c", ",") == ["a", "b", "c"]

    def test_split_with_index(self):
        assert apply_filter("split", "a,b,c", [",", 1]) == "b"

    def test_split_negative_index(self):
        assert apply_filter("split", "a,b,c", [",", -1]) == "c"

    def test_join(self):
        assert apply_filter("join", ["a", "b", "c"], ", ") == "a, b, c"

    def test_split_then_join_pipeline(self):
        pipeline = [
            {"name": "split", "args": ","},
            {"name": "join", "args": "|"},
        ]
        assert apply_pipeline("a,b,c", pipeline) == "a|b|c"

    def test_string_filter_maps_over_list(self):
        assert apply_filter("toupper", ["a", "b"]) == ["A", "B"]


class TestCaseFilter:
    def test_case_mapping(self):
        # YTS real category case table
        table = {"720p": 45, "1080p": 44, "2160p": 46, "3D": 47, "*": 45}
        assert apply_filter("case", "1080p", table) == "44"

    def test_case_fallback_star(self):
        table = {"720p": 45, "*": 45}
        assert apply_filter("case", "weird", table) == "45"

    def test_case_no_fallback_passthrough(self):
        assert apply_filter("case", "x", {"a": 1}) == "x"


class TestPipeline:
    def test_yts_title_pipeline(self):
        # title: replace [":", ""] then append suffix
        pipeline = [
            {"name": "replace", "args": [":", ""]},
            {"name": "append", "args": " 1080p BRRip -YTS"},
        ]
        assert apply_pipeline("Inside Job: 2010", pipeline) == "Inside Job 2010 1080p BRRip -YTS"

    def test_pipeline_renders_args(self):
        pipeline = [{"name": "append", "args": " ({{ .Result.year }})"}]
        out = apply_pipeline("Inside Job", pipeline, render_args=lambda s: s.replace("{{ .Result.year }}", "2010"))
        assert out == "Inside Job (2010)"

    def test_unknown_filter_raises(self):
        with pytest.raises(FilterError):
            apply_filter("doesnotexist", "x")

    def test_registry_lists_required_filters(self):
        for name in (
            "replace", "re_replace", "append", "prepend", "trim",
            "tolower", "toupper", "split", "join", "case", "querystring",
        ):
            assert name in available_filters()
