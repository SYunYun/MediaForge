"""Cardigann definition repository manager.

从 jsdelivr 拉取 Jackett 定义卡，缓存到 ~/.cache/mediaforge/indexers/。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

from .definition import Definition, load_definition, parse_definition
from .engine import DEFAULT_TIMEOUT, make_session

JACKETT_BASE = (
    "https://cdn.jsdelivr.net/gh/Jackett/Jackett@master"
    "/src/Jackett.Common/Definitions/{id}.yml"
)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mediaforge" / "indexers"


class LoaderError(Exception):
    """Raised on fetch/load failures."""


class DefinitionLoader:
    """Local cache + remote fetch for Jackett definition cards."""

    def __init__(
        self,
        cache_dir: Optional[os.PathLike] = None,
        base_url: str = JACKETT_BASE,
        proxy: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.base_url = base_url
        self.proxy = proxy
        if timeout > 15:
            raise LoaderError("timeout must be <= 15s (host safety rule)")
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_path(self, indexer_id: str) -> Path:
        return self.cache_dir / f"{indexer_id}.yml"

    def fetch(self, indexer_id: str) -> Path:
        """Download a definition card from jsdelivr into the local cache."""
        url = self.base_url.format(id=indexer_id)
        session = make_session(proxy=self.proxy)
        resp = session.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            raise LoaderError(f"definition not found upstream: {indexer_id}")
        resp.raise_for_status()
        path = self.cache_path(indexer_id)
        path.write_text(resp.text, encoding="utf-8")
        return path

    def update(self, ids: Optional[list] = None) -> list:
        """Refresh cached definitions. ids=None refreshes everything cached."""
        if ids is None:
            ids = [p.stem for p in self.cache_dir.glob("*.yml")]
        updated = []
        for indexer_id in ids:
            updated.append(self.fetch(indexer_id))
        return updated

    def load(
        self,
        indexer_id: str,
        fetch_if_missing: bool = True,
    ) -> Definition:
        """Load a definition by id from cache, fetching upstream if needed."""
        path = self.cache_path(indexer_id)
        if not path.exists():
            if not fetch_if_missing:
                raise LoaderError(f"definition {indexer_id!r} not in cache")
            self.fetch(indexer_id)
        return load_definition(str(path))

    def load_file(self, path: os.PathLike) -> Definition:
        """Load a definition directly from an arbitrary YAML file."""
        return load_definition(str(path))

    def parse(self, text: str) -> Definition:
        """Parse a definition from raw YAML text."""
        return parse_definition(text)

    def list_cached(self) -> list:
        return sorted(p.stem for p in self.cache_dir.glob("*.yml"))
