"""feed/qbit.py 单测：mock requests，覆盖幂等判重、magnet 解析、路径翻译。

真机 live 验证在 test_qbit_live.py（需 MEDIAFORGE_LIVE_QBIT=1）。
"""

import json

import pytest

import mediaforge.feed.qbit as qmod
from mediaforge.feed.qbit import (
    QbitClient,
    QbitError,
    extract_infohash,
    to_magnet,
    translate_savepath,
)

HASH_1 = "a" * 40
HASH_2 = "b" * 40
MAGNET_1 = f"magnet:?xt=urn:btih:{HASH_1}&dn=Movie+1080p"


class FakeResponse:
    def __init__(self, status, payload, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (
            json.dumps(payload) if not isinstance(payload, str) else payload
        )

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """记录调用的假 session；torrents 状态可注入。"""

    def __init__(self, torrents=None):
        self.torrent_state = list(torrents or [])
        self.calls = []  # (method, path, kwargs)

    # ---- requests.Session 接口 ----
    def post(self, url, data=None, timeout=None, **kw):
        self.calls.append(("post", url, {"data": data, "timeout": timeout}))
        if url.endswith("/auth/login"):
            return FakeResponse(204, "")  # 坑1：204 空 body
        if url.endswith("/torrents/add"):
            return FakeResponse(200, {"added_torrent_ids": [], "pending_count": 1})
        if url.endswith("/torrents/delete"):
            return FakeResponse(200, "")
        return FakeResponse(200, "")

    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append(("get", url, {"params": params, "timeout": timeout}))
        if url.endswith("/torrents/info"):
            return FakeResponse(200, self.torrent_state)
        if url.endswith("/app/version"):
            return FakeResponse(200, "v5.0.4")
        return FakeResponse(200, "")


@pytest.fixture
def fake(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(qmod, "make_qbit_session", lambda: session)
    # 时间轴：monotonic 递增（循环有界），sleep 无操作（测试不真等）
    state = {"t": 0.0}
    monkeypatch.setattr(qmod.time, "monotonic", lambda: (state.__setitem__("t", state["t"] + 1.0), state["t"])[1])
    monkeypatch.setattr(qmod.time, "sleep", lambda s: None)
    return session


def _client(cfg=None):
    return QbitClient(cfg or {"url": "http://qbit:8080", "username": "u",
                              "password": "p"}, timeout=5)


class TestLogin:
    def test_login_204_accepted(self, fake):
        _client()  # 不抛异常即通过

    def test_login_failure_raises(self, monkeypatch):
        class BadSession(FakeSession):
            def post(self, url, data=None, timeout=None, **kw):
                if url.endswith("/auth/login"):
                    return FakeResponse(403, "Fails.")
                return super().post(url, data=data, timeout=timeout, **kw)

        monkeypatch.setattr(qmod, "make_qbit_session", BadSession)
        with pytest.raises(QbitError):
            _client()


class TestExtractInfohash:
    def test_bare_hash(self):
        assert extract_infohash(HASH_1.upper()) == HASH_1

    def test_magnet(self):
        assert extract_infohash(MAGNET_1) == HASH_1

    def test_torrent_download_url(self):
        # YTS download 字段是 .torrent 下载链接，hash 藏在路径里
        url = f"https://yts.gg/torrent/download/{HASH_1.upper()}"
        assert extract_infohash(url) == HASH_1

    def test_garbage(self):
        assert extract_infohash("not-a-magnet") is None
        assert extract_infohash("") is None
        assert extract_infohash("short-hash-1234") is None

    def test_to_magnet_roundtrip(self):
        magnet = to_magnet(HASH_1, "Movie")
        assert f"urn:btih:{HASH_1}" in magnet
        assert extract_infohash(magnet) == HASH_1


class TestTranslateSavepath:
    MAP = [{"host": "/media/Media/Downloads", "container": "/downloads"}]

    def test_host_to_container(self):
        assert translate_savepath("/media/Media/Downloads/Movies", self.MAP) == \
            "/downloads/Movies"

    def test_exact_host(self):
        assert translate_savepath("/media/Media/Downloads", self.MAP) == "/downloads"

    def test_already_container_side_passthrough(self):
        assert translate_savepath("/downloads/Movies", self.MAP) == "/downloads/Movies"

    def test_unmapped_raises(self):
        with pytest.raises(QbitError):
            translate_savepath("/opt/elsewhere", self.MAP)


class TestIdempotentAdd:
    def test_already_present_skips_add(self, fake):
        fake.torrent_state = [{"hash": HASH_1, "name": "Movie"}]
        result = _client().add_magnet(MAGNET_1)
        assert result["status"] == "already_present"
        assert result["hash"] == HASH_1
        # 判重后绝不再调 add
        assert not any(c[0] == "post" and c[1].endswith("/torrents/add")
                       for c in fake.calls)

    def test_new_hash_adds_and_confirms(self, fake):
        orig_get = FakeSession.get
        info_calls = {"n": 0}

        def _info(url, *a, **kw):
            info_calls["n"] += 1
            if info_calls["n"] >= 2:  # 第一次=判重；第二次起=回查确认，任务已落队
                fake.torrent_state.append({"hash": HASH_2, "name": "Movie2"})
            return orig_get(fake, url, *a, **kw)

        fake.get = _info
        result = _client().add_magnet(to_magnet(HASH_2))
        assert result["status"] == "added"
        assert result["hash"] == HASH_2
        add_calls = [c for c in fake.calls if c[1].endswith("/torrents/add")]
        assert len(add_calls) == 1

    def test_paused_and_category_passed(self, fake):
        fake.torrent_state = [{"hash": HASH_1, "name": "Movie"}]
        _client().add_magnet(MAGNET_1, paused=True, category="movies",
                             savepath="/media/Media/Downloads",
                             path_map=[{"host": "/media/Media/Downloads",
                                        "container": "/downloads"}])
        # HASH_1 已在状态里 → already_present，不调 add
        _client().add_magnet(to_magnet(HASH_2), paused=True, category="movies",
                             savepath="/media/Media/Downloads",
                             path_map=[{"host": "/media/Media/Downloads",
                                        "container": "/downloads"}])
        add_calls = [c for c in fake.calls if c[1].endswith("/torrents/add")]
        assert len(add_calls) == 1
        data = add_calls[0][2]["data"]
        assert data["paused"] == "true"
        assert data["category"] == "movies"
        assert data["savepath"] == "/downloads"

    def test_bare_infohash_accept_and_confirm(self, fake):
        result = _client().add_magnet(HASH_2)
        # 状态里从未出现该 hash → 受理但超时未落队
        assert result["status"] == "accepted_pending"
        assert result["hash"] == HASH_2
        assert result["pending_count"] == 1

    def test_garbage_input_raises(self, fake):
        with pytest.raises(QbitError):
            _client().add_magnet("https://example.com/x.torrent")

    def test_delete_defaults_delete_files_false(self, fake):
        _client().delete(HASH_1)
        delete_calls = [c for c in fake.calls if c[1].endswith("/torrents/delete")]
        assert delete_calls[0][2]["data"] == {
            "hashes": HASH_1, "deleteFiles": "false"}
