"""YTS 真实端到端测试。

加载真实 YTS 卡 → 真实请求 movies-api.accel.li → 断言 Release 结构。
直连不通时回落到 http://127.0.0.1:7892 代理（可配置）。
"""

import os
import re
from pathlib import Path

import pytest
import requests

from mediaforge.cardigann import load_definition, search, Query

FIXTURE = Path(__file__).parent / "fixtures" / "yts.yml"
PROXY = os.environ.get("MEDIAFORGE_TEST_PROXY", "http://127.0.0.1:7892")
INFOHASH_RE = re.compile(r"^[0-9a-f]{40}$")


def _run(keywords: str, proxy: str = None):
    d = load_definition(str(FIXTURE))
    return search(d, Query(keywords=keywords), proxy=proxy, timeout=12)


@pytest.fixture(scope="module")
def releases():
    try:
        return _run("inside job")
    except requests.RequestException:
        # 直连不通 → 回落本地代理
        try:
            return _run("inside job", proxy=PROXY)
        except requests.RequestException as exc:
            pytest.skip(f"YTS API unreachable (direct & proxy): {exc}")


class TestYtsEndToEnd:
    def test_returns_releases(self, releases):
        assert len(releases) >= 1

    def test_release_shape(self, releases):
        r = releases[0]
        assert r["title"]
        assert r["download"]
        assert INFOHASH_RE.match(r["infohash"]), r["infohash"]
        assert r["indexer"] == "yts"

    def test_all_infohashes_valid(self, releases):
        for r in releases:
            assert INFOHASH_RE.match(r["infohash"]), r

    def test_field_types(self, releases):
        r = releases[0]
        assert isinstance(r["size"], int) and r["size"] > 0
        assert isinstance(r["seeders"], int)
        assert r["category"] in (44, 45, 46, 47)
        assert r["imdbid"].startswith("tt")
