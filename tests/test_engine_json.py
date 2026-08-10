"""engine.py 的 JSON rows 抽取 / 幂等 / 路径编码单测（R2、Y3、B3）。

不碰网络：用本地 transport adapter 回灌 JSON payload。
补上 B3 指出的 JSON 路径无确定性 mock 单测的盲区。
"""
import json

import requests
import requests.adapters

from mediaforge.cardigann.definition import parse_definition
from mediaforge.cardigann.engine import Query, make_session, search

JSON_PAYLOAD = {
    "data": {"movies": [
        {"title": "Some.Movie.2024.1080p", "hash": "a" * 40, "seeders": 120},
        {"title": "Other.Film.2023.720p", "hash": "b" * 40, "seeders": 5},
    ]}
}

# rows.selector 是模板（TPB 风格），渲染后走 $.data.movies
FAKE_JSON_DEF = """\
id: fakejson
name: FakeJSON
type: public
language: en-US
links:
  - https://fake.example/
settings:
  - name: uploader
    type: text
    default: ""
caps:
  modes:
    search: [q]
search:
  paths:
    - path: "https://fake.example/api?q={{ .Keywords }}"
      response:
        type: json
  rows:
    selector: "${{ if .Config.uploader }}.data.movies{{ else }}.data.movies{{ end }}"
  fields:
    title:
      selector: title
    infohash:
      selector: hash
    seeders:
      selector: seeders
"""

# Y3：path 段已带 %20 预编码，不得被二次编码成 %2520
FAKE_JSON_DEF_PRECODED = FAKE_JSON_DEF.replace(
    'path: "https://fake.example/api?q={{ .Keywords }}"',
    'path: "https://fake.example/a%20b/api?q={{ .Keywords }}"',
)

# 空格路径：应被编码成 %20
FAKE_JSON_DEF_SPACE = FAKE_JSON_DEF.replace(
    'path: "https://fake.example/api?q={{ .Keywords }}"',
    'path: "https://fake.example/a b/api?q={{ .Keywords }}"',
)

# $ 根选择器（TPB apibay JSON 数组）
FAKE_JSON_DEF_ROOT = FAKE_JSON_DEF.replace(
    'selector: "${{ if .Config.uploader }}.data.movies{{ else }}.data.movies{{ end }}"',
    'selector: "$"',
)


class _JsonAdapter(requests.adapters.BaseAdapter):
    def __init__(self, payload=JSON_PAYLOAD):
        self.payload = payload
        self.last_url = None

    def send(self, request, **kwargs):
        self.last_url = request.url
        resp = requests.Response()
        resp.status_code = 200
        resp.url = request.url
        resp._content = json.dumps(self.payload).encode()
        resp.headers["Content-Type"] = "application/json"
        return resp

    def close(self):
        pass


def _session(adapter=None):
    adapter = adapter or _JsonAdapter()
    s = make_session()
    s.mount("https://", adapter)
    return s, adapter


class TestJsonEngine:
    def test_json_rows_extraction(self):
        d = parse_definition(FAKE_JSON_DEF)
        s, _ = _session()
        rels = search(d, Query(keywords="movie"), session=s)
        assert len(rels) == 2
        r0 = rels[0]
        assert r0["indexer"] == "fakejson"
        assert r0["title"] == "Some.Movie.2024.1080p"
        assert r0["infohash"] == "a" * 40
        assert r0["seeders"] == 120

    def test_dollar_root_selector(self):
        # TPB apibay 返回裸 JSON 数组，rows.selector 为 "$"
        root_payload = [{"name": "X", "info_hash": "c" * 40}]
        d = parse_definition(FAKE_JSON_DEF_ROOT.replace(
            "title:\n      selector: title",
            "title:\n      selector: name",
        ).replace(
            "infohash:\n      selector: hash",
            "infohash:\n      selector: info_hash",
        ))
        s, _ = _session(_JsonAdapter(root_payload))
        rels = search(d, Query(keywords="x"), session=s)
        assert len(rels) == 1
        assert rels[0]["title"] == "X"
        assert rels[0]["infohash"] == "c" * 40


class TestRowsIdempotency:
    """R2：rows.selector 模板渲染不得原地改写 Definition。"""

    def test_definition_rows_selector_unchanged_across_searches(self):
        d = parse_definition(FAKE_JSON_DEF)
        sel_before = d.search.rows.selector
        s, _ = _session()

        rels1 = search(d, Query(keywords="x"), session=s)
        rels2 = search(d, Query(keywords="x"), session=s)

        assert len(rels1) == 2 and len(rels2) == 2
        # 关键断言：两次搜索后 Definition 仍保留原始模板，没有被渲染结果污染
        assert d.search.rows.selector == sel_before
        assert "{{" in d.search.rows.selector


class TestPathEncoding:
    """Y3：path 段不得二次编码（%20 -> %2520）。"""

    def test_preencoded_segment_not_double_encoded(self):
        d = parse_definition(FAKE_JSON_DEF_PRECODED)
        s, adapter = _session()
        search(d, Query(keywords="kw"), session=s)
        assert "a%20b" in adapter.last_url
        assert "%2520" not in adapter.last_url

    def test_space_segment_encoded_once(self):
        d = parse_definition(FAKE_JSON_DEF_SPACE)
        s, adapter = _session()
        search(d, Query(keywords="kw"), session=s)
        assert "a%20b" in adapter.last_url
        assert "a b" not in adapter.last_url