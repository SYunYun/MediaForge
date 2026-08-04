"""Tests for loader.py — 定义仓库缓存管理。

真实 jsdelivr 拉取单独成 test，网络失败时 skip 而不是 fail。
"""

import pytest
import requests

from mediaforge.cardigann.loader import (
    JACKETT_BASE,
    DefinitionLoader,
    LoaderError,
)

MINI_DEF = """\
id: mini
name: Mini
links: [https://mini.example/]
settings:
  - name: apikey
    type: text
    default: abc
"""


class TestCache:
    def test_cache_roundtrip(self, tmp_path):
        loader = DefinitionLoader(cache_dir=tmp_path)
        loader.cache_path("mini").write_text(MINI_DEF, encoding="utf-8")
        d = loader.load("mini", fetch_if_missing=False)
        assert d.id == "mini"
        assert d.build_config()["apikey"] == "abc"

    def test_missing_raises_without_fetch(self, tmp_path):
        loader = DefinitionLoader(cache_dir=tmp_path)
        with pytest.raises(LoaderError):
            loader.load("nope", fetch_if_missing=False)

    def test_list_cached(self, tmp_path):
        loader = DefinitionLoader(cache_dir=tmp_path)
        loader.cache_path("b").write_text(MINI_DEF.replace("id: mini", "id: b"))
        loader.cache_path("a").write_text(MINI_DEF.replace("id: mini", "id: a"))
        assert loader.list_cached() == ["a", "b"]

    def test_timeout_guard(self, tmp_path):
        with pytest.raises(LoaderError):
            DefinitionLoader(cache_dir=tmp_path, timeout=30)


class TestUpstream:
    def test_fetch_yts_from_jsdelivr(self, tmp_path):
        """真实网络：从 jsdelivr 拉 YTS 卡。GFW 抖动时 skip。"""
        loader = DefinitionLoader(cache_dir=tmp_path)
        try:
            path = loader.fetch("yts")
        except (requests.RequestException, LoaderError) as exc:
            pytest.skip(f"jsdelivr unreachable: {exc}")
        assert path.exists()
        d = loader.load("yts", fetch_if_missing=False)
        assert d.id == "yts"
        assert d.search is not None
