"""Tests for engine.py against a fake HTML definition (CSS selector path).

不碰网络：用 requests_mock 风格的本地 transport adapter 回灌 fixture HTML。
"""

from pathlib import Path

import pytest
import requests
import requests.adapters

from mediaforge.cardigann.definition import parse_definition
from mediaforge.cardigann.engine import (
    EngineError,
    Query,
    make_session,
    search,
    stripped_proxy_env,
)

HTML_FIXTURE = """\
<html><body>
<table class="torrents">
  <tr class="trow">
    <td class="name"><a class="tlink" href="/details/1">Some.Movie.2024.1080p</a></td>
    <td class="magnet"><a href="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567">mag</a></td>
    <td class="size">1.5 GB</td>
    <td class="seed">120</td>
    <td class="leech">7</td>
  </tr>
  <tr class="trow">
    <td class="name"><a class="tlink" href="/details/2">Other.Film.2023.720p</a></td>
    <td class="magnet"><a href="magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01">mag</a></td>
    <td class="size">800 MB</td>
    <td class="seed">5</td>
    <td class="leech">1</td>
  </tr>
</table>
</body></html>
"""

FAKE_HTML_DEF = """\
id: fakehtml
name: FakeHTML
type: public
language: en-US
links:
  - https://fake.example/
settings: []
caps:
  modes:
    search: [q]
search:
  paths:
    - path: "https://fake.example/search?q={{ .Keywords }}"
      response:
        type: html
  rows:
    selector: "table.torrents tr.trow"
  fields:
    title:
      selector: "a.tlink"
    details:
      selector: "a.tlink"
      attribute: href
      filters:
        - name: prepend
          args: "https://fake.example"
    download:
      selector: "td.magnet a"
      attribute: href
    size:
      selector: "td.size"
    seeders:
      selector: "td.seed"
    leechers:
      selector: "td.leech"
    category:
      text: 2000
"""


class _MockAdapter(requests.adapters.BaseAdapter):
    def send(self, request, **kwargs):
        resp = requests.Response()
        resp.status_code = 200
        resp.url = request.url
        resp._content = HTML_FIXTURE.encode()
        resp.headers["Content-Type"] = "text/html"
        return resp

    def close(self):
        pass


def _mock_session():
    s = make_session()
    s.mount("https://", _MockAdapter())
    return s


@pytest.fixture
def html_def():
    return parse_definition(FAKE_HTML_DEF)


class TestHtmlEngine:
    def test_css_selector_extraction(self, html_def):
        rels = search(html_def, Query(keywords="movie"), session=_mock_session())
        assert len(rels) == 2
        r0 = rels[0]
        assert r0["title"] == "Some.Movie.2024.1080p"
        assert r0["download"].startswith("magnet:?xt=urn:btih:0123456789abcdef")
        assert r0["details"] == "https://fake.example/details/1"
        assert r0["seeders"] == 120
        assert r0["leechers"] == 7
        assert r0["category"] == 2000
        assert r0["indexer"] == "fakehtml"
        assert rels[1]["title"] == "Other.Film.2023.720p"

    def test_keywords_rendered_into_url(self, html_def):
        seen = {}

        class SpyAdapter(_MockAdapter):
            def send(self, request, **kw):
                seen["url"] = request.url
                return super().send(request, **kw)

        s = make_session()
        s.mount("https://", SpyAdapter())
        search(html_def, Query(keywords="inside job"), session=s)
        # requests encodes query params with %20 (not +)
        assert "q=inside%20job" in seen["url"]


class TestHelpers:
    def test_timeout_guard(self, html_def):
        with pytest.raises(EngineError):
            search(html_def, Query(keywords="x"), session=_mock_session(), timeout=30)

    def test_no_search_block(self):
        d = parse_definition("id: bare\nname: Bare\nlinks: [https://x.example/]\n")
        with pytest.raises(EngineError):
            search(d, Query(keywords="x"))

    def test_stripped_proxy_env(self, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://1.2.3.4:8080")
        monkeypatch.setenv("https_proxy", "http://1.2.3.4:8080")
        monkeypatch.setenv("PATH", "/usr/bin")
        env = stripped_proxy_env()
        assert "HTTP_PROXY" not in env and "https_proxy" not in env
        assert env["PATH"] == "/usr/bin"

    def test_make_session_explicit_proxy(self):
        s = make_session(proxy="http://127.0.0.1:7892")
        assert s.proxies["https"] == "http://127.0.0.1:7892"
        assert s.trust_env is False
