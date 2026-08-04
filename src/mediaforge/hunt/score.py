"""Release 打分器 —— 把阿喆的选片手册变成代码。

因子（默认权重，config 可调）：
- seeders   : 对数缩放，min(50, 10*log2(1+s))，0 种子=0 分
- size_band : 按 title 分辨率找体积带；带宽内 +25，带宽外 0.5x~2x 内 +8，更远 -10
              动画按 animation_band_factor 缩小最优带（1080p 真人 10-20GB / 动画≈6-12GB）
- group     : prefer_groups 命中一个 +15（可多个叠加）

score_release() 返回带 score / score_breakdown 字段的新 dict，供 --explain 展示每个因子贡献。
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

RESOLUTIONS = ("2160p", "1080p", "720p")
_RES_RE = re.compile(r"(\d{3,4}p)", re.IGNORECASE)
_GB = 1024 ** 3

# 档位常量（与 config 默认一致；测试直接 import 用）
SEED_CAP = 50.0
SEED_LOG_BASE = 10.0
BAND_FULL = 25.0
BAND_TOLERANCE = 8.0
BAND_OUT = -10.0


def detect_resolution(title: str) -> Optional[str]:
    """从 title 提取分辨率：2160p > 1080p > 720p，找不到返回 None。"""
    if not title:
        return None
    match = _RES_RE.findall(title)
    if not match:
        return None
    norm = [m.lower() for m in match]
    for res in RESOLUTIONS:
        if res in norm:
            return res
    return norm[0]


def detect_animation(title: str, keywords: list) -> bool:
    """title 命中任一动画关键词即视为动画（用于体积带判定）。"""
    if not title:
        return False
    low = title.lower()
    return any(str(k).lower() in low for k in (keywords or []))


def seeders_score(seeders: Optional[int]) -> float:
    """对数缩放：0 种子 0 分，100+ 种子封顶 50。"""
    if seeders is None:
        return 0.0
    s = max(0, int(seeders))
    return round(min(SEED_CAP, SEED_LOG_BASE * math.log2(1 + s)), 1)


def size_band_score(
    size: Optional[int],
    resolution: Optional[str],
    is_animation: bool,
    bands: dict,
    animation_factor: float = 0.6,
) -> float:
    """体积带打分。size 为字节；bands 形如 {"1080p": {"lo":10,"hi":20}}（GB）。"""
    if size is None or resolution is None:
        return 0.0
    spec = (bands or {}).get(resolution)
    if not spec:
        return 0.0
    lo = float(spec["lo"]) * _GB
    hi = float(spec["hi"]) * _GB
    if is_animation:
        lo *= animation_factor
        hi *= animation_factor
    if lo <= size <= hi:
        return BAND_FULL
    if (lo * 0.5) <= size <= (hi * 2.0):
        return BAND_TOLERANCE
    return BAND_OUT


def group_score(title: str, prefer_groups: list, bonus: float = 15.0) -> float:
    """prefer_groups 命中一个 +bonus（每个组最多算一次，可叠加）。"""
    if not title or not prefer_groups:
        return 0.0
    low = title.lower()
    hits = 0
    for group in prefer_groups:
        if str(group).lower() in low:
            hits += 1
    return round(hits * float(bonus), 1)


def score_release(release: dict, config: dict) -> dict:
    """给一条 Release 打分，返回带 score / score_breakdown 的新 dict。"""
    hunt_cfg = (config or {}).get("hunt") or {}
    title = str(release.get("title") or "")
    resolution = detect_resolution(title)
    is_animation = detect_animation(title, hunt_cfg.get("animation_keywords") or [])
    bands = hunt_cfg.get("size_bands") or {}

    seed = seeders_score(release.get("seeders"))
    size = size_band_score(
        release.get("size"),
        resolution,
        is_animation,
        bands,
        float(hunt_cfg.get("animation_band_factor", 0.6)),
    )
    group = group_score(
        title,
        hunt_cfg.get("prefer_groups") or [],
        float(hunt_cfg.get("group_bonus", 15.0)),
    )

    total = round(seed + size + group, 1)
    out = dict(release)
    out["score"] = total
    out["score_breakdown"] = {
        "seeders": seed,
        "size_band": size,
        "group": group,
        "resolution": resolution,
        "is_animation": is_animation,
    }
    return out


def rank_releases(releases: list, config: dict) -> list:
    """批量打分并按 score 降序；按 infohash 去重（保留高分）。"""
    scored = [score_release(r, config) for r in releases]
    by_hash: dict = {}
    for r in scored:
        key = r.get("infohash") or id(r)
        if key not in by_hash or r["score"] > by_hash[key]["score"]:
            by_hash[key] = r
    return sorted(by_hash.values(), key=lambda r: r["score"], reverse=True)
