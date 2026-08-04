"""CLI 冒烟：--help、config 初始化、search --json 结构、add 幂等桩。

search --json 走真实 YTS（与 test_yts_e2e 一致，不可达则 skip）。
"""

import json
import os
import shutil
from pathlib import Path

import pytest
import requests

from mediaforge.cli import main

FIXTURE_DIR = Path(__file__).parent / "fixtures"
PROXY = os.environ.get("MEDIAFORGE_TEST_PROXY", "http://127.0.0.1:7892")


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把 config 和索引器缓存都隔离到临时目录。"""
    cache = tmp_path / "indexers"
    cache.mkdir()
    shutil.copy(FIXTURE_DIR / "yts.yml", cache / "yts.yml")
    monkeypatch.setenv("MEDIAFORGE_CONFIG_DIR", str(tmp_path / "cfg"))
    import mediaforge.config as mcfg

    monkeypatch.setattr(mcfg, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(mcfg, "CONFIG_PATH", tmp_path / "cfg" / "config.yaml")
    import mediaforge.cardigann.loader as mloader

    monkeypatch.setattr(mloader, "DEFAULT_CACHE_DIR", cache)
    return tmp_path


class TestHelp:
    def test_root_help(self):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert "mediaforge" in capsys.readouterr().out

    def test_subcommand_helps(self):
        for sub in ("search", "pick", "add", "config", "indexers"):
            with pytest.raises(SystemExit) as exc:
                main([sub, "--help"])
            assert exc.value.code == 0


class TestConfig:
    def test_init_creates_template(self, isolated_config):
        assert main(["config", "init"]) == 0
        cfg_path = isolated_config / "cfg" / "config.yaml"
        assert cfg_path.exists()
        text = cfg_path.read_text(encoding="utf-8")
        assert "prefer_groups" in text and "path_map" in text

    def test_show_redacts_password(self, isolated_config, capsys):
        main(["config", "init"])
        assert main(["config", "show", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["qbit"]["password"] == "***"


def _yts_reachable():
    try:
        r = requests.get("https://movies-api.accel.li/api/v2/list_movies.json",
                         params={"query_term": "inside job"}, timeout=12)
        return r.status_code == 200
    except requests.RequestException:
        return False


class TestSearchSmoke:
    def test_search_json_structure(self, isolated_config, capsys):
        if not _yts_reachable():
            pytest.skip("YTS API 不可达")
        code = main(["search", "inside job", "--indexers", "yts",
                     "--limit", "5", "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) > 0
        r = data[0]
        for key in ("title", "infohash", "size", "seeders", "indexer",
                    "score", "score_breakdown"):
            assert key in r, key
        assert r["indexer"] == "yts"
        assert r["score_breakdown"]["seeders"] >= 0

    def test_search_table_human_readable(self, isolated_config, capsys):
        if not _yts_reachable():
            pytest.skip("YTS API 不可达")
        assert main(["search", "inside job", "--indexers", "yts",
                     "--limit", "3", "--explain"]) == 0
        out = capsys.readouterr().out
        assert "score" in out and "GB" in out and "yts" in out


class TestAddStub:
    """add 子命令用桩 QbitClient 验证输出路径（真机验证在 test_qbit_live）。"""

    def test_add_json_output(self, monkeypatch, capsys):
        class StubClient:
            def __init__(self, cfg, timeout=10):
                self.cfg = cfg

            def add_magnet(self, magnet, paused=False, category=None,
                           savepath=None, path_map=None):
                return {"status": "already_present", "hash": "a" * 40}

        import mediaforge.cli as cli_mod

        monkeypatch.setattr(cli_mod, "QbitClient", StubClient)
        assert main(["add", "a" * 40, "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "already_present"
        assert out["hash"] == "a" * 40

    def test_add_error_path(self, monkeypatch, capsys):
        import mediaforge.cli as cli_mod
        from mediaforge.feed.qbit import QbitError

        class FailingClient:
            def __init__(self, cfg, timeout=10):
                pass

            def add_magnet(self, magnet, **kw):
                raise QbitError("识别不出 infohash")

        monkeypatch.setattr(cli_mod, "QbitClient", FailingClient)
        assert main(["add", "garbage-input", "--json"]) == 1
        err = json.loads(capsys.readouterr().out)
        assert err["ok"] is False
