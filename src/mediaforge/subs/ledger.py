"""字幕台账 —— 每季每集的状态持久化。

台账是"无感闭环"的心脏：Agent/进程下次不用重扫，直接读账本判断
"这集字幕是否已 done / 需要人工品味 / 上次体检值是多少 / 修过什么"。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

LEDGER_DIR_ENV = "MEDIAFORGE_LEDGER_DIR"


def ledger_dir() -> Path:
    d = Path(os.environ.get(LEDGER_DIR_ENV, str(Path.home() / ".config" / "mediaforge" / "ledger")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(show: str, season: str) -> str:
    # 规范化：小写、去符号，防跨平台路径问题
    return f"{show.lower().replace(' ', '_')}__{season.lower().replace(' ', '_')}"


def load_ledger(show: str, season: str) -> dict:
    """读某季台账；不存在返回空 dict。"""
    p = ledger_dir() / f"{_key(show, season)}.json"
    if not p.exists():
        return {"show": show, "season": season, "episodes": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"show": show, "season": season, "episodes": {}}


def save_ledger(show: str, season: str, data: dict) -> Path:
    p = ledger_dir() / f"{_key(show, season)}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def update_episode(show: str, season: str, ep_key: str, **fields) -> dict:
    """更新单集状态并落盘。返回更新后的台账。"""
    data = load_ledger(show, season)
    eps = data.setdefault("episodes", {})
    ep = eps.setdefault(ep_key, {})
    for k, v in fields.items():
        ep[k] = v
    ep["updated_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    save_ledger(show, season, data)
    return data


def list_ledgers() -> list[Path]:
    return sorted(ledger_dir().glob("*.json"))