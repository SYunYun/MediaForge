"""媒体库接口抽象层 —— subs 与媒体库的边界。

原则：subs 只通过本层访问媒体库，不直接摸 Jellyfin API / 文件系统。
先实现 FilesystemAdapter（直接扫媒体目录，字幕是外部文件最常见形态），
JellyfinAdapter 留作下一步（刷新/入库触发）。

配置（config.yaml 的 subs 段）：
  subs:
    media:
      backend: filesystem   # filesystem | jellyfin
      root: /media/Media    # 媒体根目录
      library: Shows        # 库子目录（Shows / Movies ...）
    naming:
      ass_suffix: .default.chi.zh-cn.ass
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SeriesSub:
    """一个季目录的扫描结果。"""
    show: str
    season: str
    season_dir: str
    mkvs: list[str] = field(default_factory=list)
    missing_ass: list[str] = field(default_factory=list)


class BaseMediaAdapter:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.subs_cfg = cfg.get("subs") or {}
        self.media_cfg = self.subs_cfg.get("media") or {}
        self.naming = self.subs_cfg.get("naming") or {}
        self.suffix = self.naming.get("ass_suffix", ".default.chi.zh-cn.ass")

    def locate_series(self, show: str, season: str) -> Optional[str]:
        raise NotImplementedError

    def scan_episodes(self, season_dir: str) -> SeriesSub:
        raise NotImplementedError


class FilesystemAdapter(BaseMediaAdapter):
    """直接扫媒体目录（外部 ASS 文件与 mkv 同目录）。"""

    def locate_series(self, show: str, season: str) -> Optional[str]:
        root = self.media_cfg.get("root") or "/media/Media"
        library = self.media_cfg.get("library") or ""
        base = Path(root) / library if library else Path(root)
        candidates = [
            base / show,
            base / show / season,
            base / f"{show} ({season})",
        ]
        for c in candidates:
            if c.is_dir():
                # 若已到季目录直接返回；否则查 season 子目录
                if c.name.upper().startswith("S") or c.name.lower() == season.lower():
                    return str(c)
                sub = c / season
                if sub.is_dir():
                    return str(sub)
        # 兜底：递归浅找"Season XX"目录
        if (base / show).is_dir():
            for d in (base / show).iterdir():
                if d.is_dir() and season.lower() in d.name.lower():
                    return str(d)
        return None

    def scan_episodes(self, season_dir: str) -> SeriesSub:
        show = Path(season_dir).parent.name
        season = Path(season_dir).name
        sub = SeriesSub(show=show, season=season, season_dir=season_dir)
        for f in sorted(os.listdir(season_dir)):
            lower = f.lower()
            if lower.endswith((".mkv", ".mp4", ".avi")):
                sub.mkvs.append(f)
                stem = os.path.splitext(f)[0]
                if not os.path.exists(os.path.join(season_dir, stem + self.suffix)):
                    sub.missing_ass.append(f)
        return sub


class JellyfinAdapter(BaseMediaAdapter):
    """Jellyfin —— 预留：入库触发时刷新库 / 通过 API 定位剧集。"""

    def locate_series(self, show: str, season: str) -> Optional[str]:
        # TODO: 用 Jellyfin API (Items/SearchHint) 定位
        return None

    def scan_episodes(self, season_dir: str) -> SeriesSub:
        return FilesystemAdapter(self.cfg).scan_episodes(season_dir)

    def refresh_library(self) -> None:
        """POST /Library/Refresh 让 Jellyfin 重扫字幕轨。"""
        import requests
        url = self.media_cfg.get("url") or "http://localhost:8096"
        api_key = self.media_cfg.get("api_key") or ""
        headers = {"X-Emby-Token": api_key} if api_key else {}
        requests.post(f"{url}/Library/Refresh", headers=headers,
                      timeout=int(self.cfg.get("timeout") or 12))


def get_adapter(cfg: dict) -> BaseMediaAdapter:
    backend = (cfg.get("subs") or {}).get("media", {}).get("backend") or "filesystem"
    if backend == "jellyfin":
        return JellyfinAdapter(cfg)
    return FilesystemAdapter(cfg)