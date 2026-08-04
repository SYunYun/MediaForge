"""qbit 真机 live 验证（opt-in：MEDIAFORGE_LIVE_QBIT=1 才跑）。

流程：搜一条真实 YTS 720p 磁力 → paused=True 投喂 → 验证落队
→ deleteFiles=False 清任务。全程不真正下载。
"""

import os
from pathlib import Path

import pytest
import requests

from mediaforge.cardigann import Query, load_definition, search
from mediaforge.config import load_config
from mediaforge.feed.qbit import QbitClient, extract_infohash

FIXTURE = Path(__file__).parent / "fixtures" / "yts.yml"
PROXY = os.environ.get("MEDIAFORGE_TEST_PROXY", "http://127.0.0.1:7892")

pytestmark = pytest.mark.skipif(
    os.environ.get("MEDIAFORGE_LIVE_QBIT") != "1",
    reason="真机测试需 MEDIAFORGE_LIVE_QBIT=1（会真实投喂 qbit）",
)


def _find_720p_magnet():
    try:
        releases = search(load_definition(str(FIXTURE)), Query(keywords="inside job"),
                          proxy=None, timeout=12)
    except requests.RequestException:
        releases = search(load_definition(str(FIXTURE)), Query(keywords="inside job"),
                          proxy=PROXY, timeout=12)
    for r in releases:
        title = (r.get("title") or "").lower()
        if "720p" in title and r.get("download"):
            return r["download"], r["infohash"]
    raise RuntimeError("没找到 720p 磁力")


def test_live_idempotent_add_then_cleanup():
    cfg = load_config()
    client = QbitClient(cfg["qbit"], timeout=12)
    magnet, infohash = _find_720p_magnet()
    assert extract_infohash(magnet) == infohash

    # 第一次投喂：应为 added（或已存在则 already_present，都算幂等通过）
    first = client.add_magnet(magnet, paused=True, confirm_timeout=30)
    assert first["status"] in ("added", "already_present"), first
    assert first["hash"] == infohash

    # 第二次投喂：必须 already_present（幂等判重）
    second = client.add_magnet(magnet, paused=True)
    assert second["status"] == "already_present", second

    # 清理：deleteFiles=False，绝不误删
    client.delete(infohash, delete_files=False)
    hashes = {t["hash"] for t in client.torrents()}
    assert infohash not in hashes, "清理后任务应已移除"
