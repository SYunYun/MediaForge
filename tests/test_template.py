"""Tests for the Go template subset renderer (template.py)."""

import pytest

from mediaforge.cardigann import template
from mediaforge.cardigann.template import TemplateError, render

CTX = {
    "Config": {"apiurl": "movies-api.accel.li", "sitelink": "https://yts.gg/"},
    "Keywords": "inside job",
    "Query": {"Keywords": "inside job", "IMDBID": "", "Season": "", "Episode": ""},
    "Result": {"year": "2010", "_quality": "1080p", "_type": "bluray", "_audio": "5.1"},
}


class TestVariables:
    def test_config_var(self):
        # YTS real path template
        out = render("https://{{ .Config.apiurl }}/api/v2/list_movies.json", CTX)
        assert out == "https://movies-api.accel.li/api/v2/list_movies.json"

    def test_keywords_var(self):
        assert render("q={{ .Keywords }}", CTX) == "q=inside job"

    def test_query_var(self):
        assert render("{{ .Query.Keywords }}", CTX) == "inside job"

    def test_result_var(self):
        # YTS real filter arg template
        assert render(" ({{ .Result.year }})", CTX) == " (2010)"

    def test_missing_var_renders_empty(self):
        assert render("[{{ .Config.nope }}]", CTX) == "[]"

    def test_no_template_passthrough(self):
        assert render("plain string", CTX) == "plain string"

    def test_non_string_passthrough(self):
        assert render(50, CTX) == "50"
        assert render(None, CTX) == ""


class TestIfElse:
    def test_if_truthy(self):
        assert render("{{ if .Keywords }}yes{{ else }}no{{ end }}", CTX) == "yes"

    def test_if_falsy_empty_string(self):
        assert render("{{ if .Query.IMDBID }}yes{{ else }}no{{ end }}", CTX) == "no"

    def test_yts_query_term_template_with_imdbid(self):
        # YTS real inputs template
        tpl = "{{ if .Query.IMDBID }}{{ .Query.IMDBID }}{{ else }}{{ .Keywords }}{{ end }}"
        assert render(tpl, CTX) == "inside job"
        ctx2 = {**CTX, "Query": {**CTX["Query"], "IMDBID": "tt1645089"}}
        assert render(tpl, ctx2) == "tt1645089"

    def test_if_without_else(self):
        assert render("a{{ if .Keywords }}b{{ end }}c", CTX) == "abc"
        ctx = {**CTX, "Keywords": ""}
        assert render("a{{ if .Keywords }}b{{ end }}c", ctx) == "ac"

    def test_nested_if(self):
        tpl = "{{ if .Query.IMDBID }}imdb{{ else }}{{ if .Keywords }}kw{{ else }}none{{ end }}{{ end }}"
        assert render(tpl, CTX) == "kw"
        ctx = {**CTX, "Keywords": ""}
        assert render(tpl, ctx) == "none"
        ctx2 = {**CTX, "Query": {**CTX["Query"], "IMDBID": "tt1"}}
        assert render(tpl, ctx2) == "imdb"


class TestConditions:
    def test_eq_true(self):
        # YTS real title filter condition
        tpl = '{{ if eq .Result._type "bluray" }}BRRip{{ else }}WEBRip{{ end }}'
        assert render(tpl, CTX) == "BRRip"

    def test_eq_false(self):
        tpl = '{{ if eq .Result._type "web" }}WEBRip{{ else }}BRRip{{ end }}'
        assert render(tpl, CTX) == "BRRip"

    def test_eq_numbers(self):
        assert render("{{ if eq 1 1 }}y{{ end }}", CTX) == "y"
        assert render("{{ if eq 1 2 }}y{{ else }}n{{ end }}", CTX) == "n"

    def test_and(self):
        tpl = "{{ if and .Keywords .Result.year }}both{{ else }}not{{ end }}"
        assert render(tpl, CTX) == "both"
        ctx = {**CTX, "Keywords": ""}
        assert render(tpl, ctx) == "not"

    def test_or(self):
        tpl = "{{ if or .Query.IMDBID .Keywords }}some{{ else }}none{{ end }}"
        assert render(tpl, CTX) == "some"
        ctx = {**CTX, "Keywords": ""}
        assert render(tpl, ctx) == "none"

    def test_not(self):
        assert render("{{ if not .Query.IMDBID }}no-imdb{{ end }}", CTX) == "no-imdb"

    def test_falsy_zero_string(self):
        ctx = {**CTX, "Result": {"n": "0"}}
        assert render("{{ if .Result.n }}y{{ else }}n{{ end }}", ctx) == "n"

    def test_yts_title_suffix_full(self):
        # YTS real append arg (trimmed variant)
        tpl = (
            " {{ .Result._quality }} "
            '{{ if eq .Result._type "web" }}WEBRip{{ else }}BRRip{{ end }}'
            '{{ if eq .Result._audio "5.1" }}5.1 {{ else }}{{ end }}'
        )
        assert render(tpl, CTX) == " 1080p BRRip5.1 "


class TestErrors:
    def test_unclosed_if(self):
        with pytest.raises(TemplateError):
            render("{{ if .Keywords }}oops", CTX)

    def test_unexpected_end(self):
        with pytest.raises(TemplateError):
            render("{{ end }}", CTX)
