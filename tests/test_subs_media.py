"""subs/media.py 的 locate_series / scan_episodes 单测（B1 最严重盲区）。

用 tmp_path 构造目录树，直接抓 R1（S 开头剧名误判季目录）+ 扫季逻辑。
"""
from mediaforge.subs.media import FilesystemAdapter, get_adapter


def _adapter(root, library="Shows"):
    return get_adapter({"subs": {"media": {"root": str(root), "library": library}}})


def _shows(tmp_path):
    shows = tmp_path / "Shows"
    shows.mkdir(parents=True)
    return shows


# ---------------------------------------------------------------------------
# R1：S 开头剧名不得被误判为季目录
# ---------------------------------------------------------------------------


def test_locate_s_show_returns_season_subdir(tmp_path):
    """R1 回归：Severance 应定位到 .../Severance/Season 01，而非剧根目录。"""
    shows = _shows(tmp_path)
    (shows / "Severance" / "Season 01").mkdir(parents=True)
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("Severance", "Season 01") == \
        str(shows / "Severance" / "Season 01")


def test_locate_s_show_missing_season_returns_none(tmp_path):
    """R1 回归：Severance 只有剧根目录、无季子目录时，绝不把剧根当季目录返回。"""
    shows = _shows(tmp_path)
    (shows / "Severance").mkdir()
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("Severance", "Season 01") is None


def test_locate_normal_show(tmp_path):
    shows = _shows(tmp_path)
    (shows / "Rick and Morty" / "Season 06").mkdir(parents=True)
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("Rick and Morty", "Season 06") == \
        str(shows / "Rick and Morty" / "Season 06")


def test_locate_season_named_s01(tmp_path):
    """季目录叫 S01（数字前缀）也能正确定位。"""
    shows = _shows(tmp_path)
    (shows / "Suits" / "S01").mkdir(parents=True)
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("Suits", "S01") == str(shows / "Suits" / "S01")


def test_locate_numeric_season_subdir(tmp_path):
    """季参数是纯数字（如 '01'）时，走 show/01 子目录。"""
    shows = _shows(tmp_path)
    (shows / "Severance" / "01").mkdir(parents=True)
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("Severance", "01") == str(shows / "Severance" / "01")


def test_locate_show_not_found_returns_none(tmp_path):
    _shows(tmp_path)
    adapter = _adapter(tmp_path)
    assert adapter.locate_series("No Such Show", "Season 01") is None


# ---------------------------------------------------------------------------
# scan_episodes：mkv 收集 + missing_ass 判定
# ---------------------------------------------------------------------------


def test_scan_episodes(tmp_path):
    season_dir = tmp_path / "Season 01"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").write_bytes(b"x")
    (season_dir / "S01E02.mkv").write_bytes(b"x")
    (season_dir / "S01E01.default.chi.zh-cn.ass").write_text("ok")
    (season_dir / "notes.txt").write_text("ignore me")

    adapter = FilesystemAdapter({})
    sub = adapter.scan_episodes(str(season_dir))

    assert sub.show == tmp_path.name  # 父目录名即剧名
    assert sub.season == "Season 01"
    assert set(sub.mkvs) == {"S01E01.mkv", "S01E02.mkv"}
    # S01E01 有 ass，S01E02 缺 ass
    assert sub.missing_ass == ["S01E02.mkv"]


def test_scan_episodes_ignores_non_video(tmp_path):
    season_dir = tmp_path / "Season 01"
    season_dir.mkdir()
    (season_dir / "S01E01.mkv").write_bytes(b"x")
    (season_dir / "cover.jpg").write_bytes(b"x")
    (season_dir / "S01E01.mp4").write_bytes(b"x")  # mp4 也算视频

    adapter = FilesystemAdapter({})
    sub = adapter.scan_episodes(str(season_dir))
    assert set(sub.mkvs) == {"S01E01.mkv", "S01E01.mp4"}