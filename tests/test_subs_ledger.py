"""ledger 台账读写测试。"""
import os
from mediaforge.subs import ledger


def test_ledger_roundtrip(tmp_path):
    os.environ["MEDIAFORGE_LEDGER_DIR"] = str(tmp_path)
    ledger.update_episode("Show", "Season 01", "S01E01", verdict="ok", n_cues=100)
    data = ledger.load_ledger("Show", "Season 01")
    assert data["episodes"]["S01E01"]["verdict"] == "ok"
    assert data["episodes"]["S01E01"]["n_cues"] == 100
    assert "updated_at" in data["episodes"]["S01E01"]


def test_ledger_updates_merge(tmp_path):
    os.environ["MEDIAFORGE_LEDGER_DIR"] = str(tmp_path)
    ledger.update_episode("Show", "Season 02", "S02E01", verdict="ok")
    ledger.update_episode("Show", "Season 02", "S02E01", end_med=-0.5)
    data = ledger.load_ledger("Show", "Season 02")
    ep = data["episodes"]["S02E01"]
    assert ep["verdict"] == "ok"
    assert ep["end_med"] == -0.5


def test_ledger_missing_returns_empty(tmp_path):
    os.environ["MEDIAFORGE_LEDGER_DIR"] = str(tmp_path)
    data = ledger.load_ledger("Ghost", "Season 99")
    assert data["episodes"] == {}


class TestKeySanitization:
    """Y2：_key 必须清洗文件系统非法字符，防 / 造成子目录穿越。"""

    def test_key_replaces_slash(self):
        assert ledger._key("A/B", "Season 01") == "a_b__season_01"
        assert ledger._key("A/B:C", "S01") == "a_b_c__s01"

    def test_key_normal_keeps_underscores(self):
        assert ledger._key("Rick and Morty", "Season 01") == \
            "rick_and_morty__season_01"

    def test_update_with_slash_does_not_create_subdir(self, tmp_path):
        os.environ["MEDIAFORGE_LEDGER_DIR"] = str(tmp_path)
        ledger.update_episode("A/B", "Season 01", "S01E01", verdict="ok")
        # 不产生子目录穿越：tmp_path 下只有单个扁平 json 文件
        files = [p.name for p in tmp_path.iterdir()]
        assert files == ["a_b__season_01.json"]
        data = ledger.load_ledger("A/B", "Season 01")
        assert data["episodes"]["S01E01"]["verdict"] == "ok"