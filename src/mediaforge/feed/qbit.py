"""qBittorrent 5.x 幂等投喂客户端。

姿势参考自 ~/media-ctl/mediacTL/clients/qbit.py（上一项目已踩平的坑），
本模块自包含，不依赖 media-ctl。

qbit 5.x 四坑（已内置处理，详见 docs/pitfalls.md）：
1. login 成功返回 204 空 body（不是 "Ok." 文本）
2. add 返回 JSON {"added_torrent_ids": [...], "pending_count": N} —— 异步受理，
   必须随后用 torrents/info 回查确认落队
3. resume 已改名 start（本模块用不到，但别踩）
4. savepath 只认容器内路径（宿主机路径必须按 path_map 翻译成 /downloads 前缀）

幂等：add_magnet() 先查 torrents/info 的 hash 集合，已存在直接返回
{"status": "already_present"}，绝不重复投喂。
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests

INFOHASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class QbitError(Exception):
    """qbit 调用失败。"""


def make_qbit_session() -> requests.Session:
    """本地服务专用 session：不信任 env 代理（Hermes 后台会注入 proxy env）。"""
    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    return session


def extract_infohash(value: str) -> Optional[str]:
    """从 magnet / 裸 infohash / 含 hash 的 URL（如 YTS download 链接）提取小写 40 位 hash。

    识别不了返回 None。
    """
    value = (value or "").strip()
    if INFOHASH_RE.match(value):
        return value.lower()
    # magnet 的 btih:xxx 或 URL 路径里的 xxx（如 yts.gg/torrent/download/<hash>）
    match = re.search(r"([0-9a-fA-F]{40})", value)
    if match:
        return match.group(1).lower()
    return None


def to_magnet(infohash: str, name: str = "") -> str:
    """裸 infohash -> magnet（qbit add 只收 magnet/url，不收裸 hash）。"""
    infohash = extract_infohash(infohash) or infohash.lower()
    return f"magnet:?xt=urn:btih:{infohash}&dn={name or infohash}"


def translate_savepath(host_path: str, path_map: list) -> str:
    """宿主机路径 -> 容器路径。已在容器侧（/downloads 开头）原样放行。"""
    host_path = (host_path or "").rstrip("/")
    if host_path.startswith("/downloads"):
        return host_path
    for entry in path_map or []:
        host = (entry.get("host") or "").rstrip("/")
        container = (entry.get("container") or "").rstrip("/")
        if not host or not container:
            continue
        if host_path == host:
            return container
        if host_path.startswith(host + "/"):
            return container + host_path[len(host):]
    raise QbitError(
        f"savepath {host_path!r} 翻译不到容器路径，请在 config.yaml 的 "
        f"qbit.path_map 里补一条映射"
    )


class QbitClient:
    """薄封装：login（204 判定）+ torrents/info 判重 + add + 回查确认。"""

    def __init__(self, cfg: dict, timeout: int = 10):
        self.url = str(cfg.get("url") or "http://localhost:8080").rstrip("/")
        self.username = cfg.get("username") or "admin"
        self.password = cfg.get("password") or ""
        self.timeout = timeout
        self.s = make_qbit_session()
        self._login()

    def _login(self):
        try:
            resp = self.s.post(
                f"{self.url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise QbitError(f"qbit 连接失败: {exc}") from exc
        # 坑1：成功是 204 空 body；老版本才是文本 "Ok."
        if resp.status_code != 204 and "Ok." not in resp.text:
            raise QbitError(
                f"qbit login 失败: HTTP {resp.status_code} {resp.text[:120]!r}"
            )

    def _get(self, path: str, **kw) -> requests.Response:
        return self.s.get(f"{self.url}/api/v2{path}", timeout=self.timeout, **kw)

    def _post(self, path: str, **kw) -> requests.Response:
        return self.s.post(f"{self.url}/api/v2{path}", timeout=self.timeout, **kw)

    # ---- 查询 ----
    def torrents(self, hashes: Optional[list] = None) -> list:
        params = {}
        if hashes:
            params["hashes"] = "|".join(hashes)
        try:
            resp = self._get("/torrents/info", params=params)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise QbitError(f"torrents/info 查询失败: {exc}") from exc
        return resp.json()

    def hash_set(self) -> set:
        """现有任务 hash 集合（判重依据）。"""
        try:
            return {t.get("hash", "").lower() for t in self.torrents() if t.get("hash")}
        except requests.RequestException as exc:
            raise QbitError(f"torrents/info 查询失败: {exc}") from exc

    def version(self) -> str:
        return self._get("/app/version").text.strip()

    # ---- 写操作 ----
    def _add(self, magnet: str, paused: bool, category: Optional[str],
             savepath: Optional[str], path_map: list) -> dict:
        data = {"urls": magnet}
        if paused:
            data["paused"] = "true"
        if category:
            data["category"] = category
        if savepath:
            data["savepath"] = translate_savepath(savepath, path_map)
        try:
            resp = self._post("/torrents/add", data=data)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise QbitError(f"qbit add 失败: {exc}") from exc
        # 坑2：5.x 返回 JSON pending_count；老版本才是文本 "Ok."
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text, "status": resp.status_code}
        return body

    def add_magnet(
        self,
        magnet: str,
        paused: bool = False,
        category: Optional[str] = None,
        savepath: Optional[str] = None,
        path_map: Optional[list] = None,
        confirm_timeout: float = 25.0,
        poll_interval: float = 1.0,
    ) -> dict:
        """幂等投喂。返回 status ∈ {already_present, added, accepted_pending}。"""
        infohash = extract_infohash(magnet)
        if infohash is None:
            raise QbitError(
                "识别不出 infohash：请给 magnet:?xt=urn:btih:... 或裸 40 位 hash"
            )
        target = magnet if magnet.lower().startswith("magnet:") else to_magnet(magnet)
        path_map = path_map if path_map is not None else []

        existing = self.hash_set()
        if infohash in existing:
            return {"status": "already_present", "hash": infohash}

        body = self._add(target, paused, category, savepath, path_map)

        # 回查确认落队（add 是异步受理）
        deadline = time.monotonic() + confirm_timeout
        while time.monotonic() < deadline:
            if infohash in self.hash_set():
                return {
                    "status": "added",
                    "hash": infohash,
                    "pending_count": body.get("pending_count"),
                    "added_torrent_ids": body.get("added_torrent_ids"),
                    "paused": paused,
                }
            time.sleep(poll_interval)
        return {
            "status": "accepted_pending",
            "hash": infohash,
            "pending_count": body.get("pending_count"),
            "added_torrent_ids": body.get("added_torrent_ids"),
            "note": "qbit 已受理但超时未见落队，请稍后重查",
        }

    def delete(self, hashes, delete_files: bool = False):
        """铁律：清任务默认 deleteFiles=False，绝不误删媒体文件。"""
        if isinstance(hashes, list):
            hashes = "|".join(hashes)
        return self._post(
            "/torrents/delete",
            data={"hashes": hashes, "deleteFiles": "true" if delete_files else "false"},
        )

    def start(self, hashes):
        if isinstance(hashes, list):
            hashes = "|".join(hashes)
        return self._post("/torrents/start", data={"hashes": hashes})
