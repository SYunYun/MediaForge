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