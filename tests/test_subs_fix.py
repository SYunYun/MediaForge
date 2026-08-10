"""fix 自动修复闭环测试 —— 三种偏移样本 + 幂等 + dry-run。

用 inspect_with_sdh（给定 SDH 英轨内容做匹配，不依赖 mkv/ffmpeg）
作为复检回调，在临时 ASS 文件上验证"修→复检通过→闭环"。
"""
import os
import tempfile

from mediaforge.subs.ass import sec2ts, parse_ass
from mediaforge.subs.inspect import inspect_with_sdh, EpResult
from mediaforge.subs import fix as fixmod

_HEADER = (
    "[Script Info]\nPlayResX: 1920\nPlayResY: 1080\n\n"
    "[V4+ Styles]\nFormat: Name\n"
    "Style: Default,Arial,62,...,2,36,0,0,0,1,3,1.5\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)
_TEXTS = ["alpha bravo one", "charlie delta two", "echo foxtrot three",
          "golf hotel four", "india juliet five"]


def _dlg(start: float, end: float, eng: str) -> str:
    return (f"Dialogue: 0,{sec2ts(start)},{sec2ts(end)},Default,,0,0,0,,"
            f"中文主行\\N{{\\fs38\\c&H00D7D7D7&\\b0}}{eng}\n")


def _write_ass(path: str, cues: list[tuple[float, float, str]]) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(_HEADER)
        for s, e, eng in cues:
            f.write(_dlg(s, e, eng))
    return path


def _recheck(path: str, sdh, ep="E1"):
    return lambda p: inspect_with_sdh(p, sdh, ep=ep, mkv=f"{ep}.mkv")


def _sdh_series(base: float) -> list:
    return [(base + i * 4.0, base + 3.0 + i * 4.0, t) for i, t in enumerate(_TEXTS)]


# ---------------------------------------------------------------------------
# uniform：均匀错轴 -> 整体平移
# ---------------------------------------------------------------------------


def test_fix_uniform(tmp_path):
    sdh = _sdh_series(10.0)
    ass = _write_ass(str(tmp_path / "E1.ass"),
                     [(s + 1.5, e + 1.5, t) for (s, e, t) in sdh])
    before = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert before.verdict == "uniform"

    res = fixmod.fix_episode(ass, before, _recheck(ass, sdh))
    assert res.changed > 0
    assert res.done
    assert res.actions[0].kind == "uniform"
    assert abs(res.actions[0].shift + 1.5) < 1e-6

    after = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert after.verdict == "ok", after.verdict


# ---------------------------------------------------------------------------
# break：片中断裂 -> 后段平移对齐前段
# ---------------------------------------------------------------------------


def test_fix_break(tmp_path):
    front = _sdh_series(10.0)                 # 前段对齐
    back = _sdh_series(750.0)                 # 后段（>CUT）晚出 1.5s
    sdh = front + back
    cues = [(s, e, t) for (s, e, t) in front] + \
           [(s + 1.5, e + 1.5, t) for (s, e, t) in back]
    ass = _write_ass(str(tmp_path / "E1.ass"), cues)

    before = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert before.verdict == "break", before.verdict
    assert before.front_med is not None and before.back_med is not None

    res = fixmod.fix_episode(ass, before, _recheck(ass, sdh))
    assert res.done
    assert res.actions[0].kind == "break"
    assert res.actions[0].cut == 720.0
    # 只动后段，前段时间不该变
    cues_after = parse_ass(ass)
    assert abs(cues_after[0].start - 10.0) < 0.01

    after = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert after.verdict == "ok", after.verdict


# ---------------------------------------------------------------------------
# end_short：Start 对齐但 End 偏短 -> 末段延长
# ---------------------------------------------------------------------------


def test_fix_end_short(tmp_path):
    sdh = _sdh_series(10.0)
    ass = _write_ass(str(tmp_path / "E1.ass"),
                     [(s, e - 1.0, t) for (s, e, t) in sdh])
    before = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert before.verdict == "end_short", before.verdict

    res = fixmod.fix_episode(ass, before, _recheck(ass, sdh))
    assert res.done
    assert res.actions[0].kind == "end_extend"
    assert abs(res.actions[0].shift - 1.0) < 1e-6
    # Start 不该被延长，只有 End 变
    cues_after = parse_ass(ass)
    assert abs(cues_after[0].start - 10.0) < 0.01

    after = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    assert after.verdict == "ok", after.verdict


# ---------------------------------------------------------------------------
# 幂等：重复执行不叠加偏移
# ---------------------------------------------------------------------------


def test_fix_idempotent(tmp_path):
    sdh = _sdh_series(10.0)
    ass = _write_ass(str(tmp_path / "E1.ass"),
                     [(s + 1.5, e + 1.5, t) for (s, e, t) in sdh])
    before = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    res1 = fixmod.fix_episode(ass, before, _recheck(ass, sdh))
    assert res1.done and res1.changed > 0

    content = open(ass, encoding="utf-8").read()
    # 第二次跑：复检已 ok，plan 为空，不改文件、不叠加
    after = inspect_with_sdh(ass, sdh, ep="E1", mkv="E1.mkv")
    res2 = fixmod.fix_episode(ass, after, _recheck(ass, sdh))
    assert res2.actions == []
    assert res2.changed == 0
    assert res2.done
    assert open(ass, encoding="utf-8").read() == content


# ---------------------------------------------------------------------------
# plan_fix 判定映射 + dry-run 不落刀
# ---------------------------------------------------------------------------


def test_plan_fix_mapping():
    assert fixmod.plan_fix(EpResult(ep="E", mkv="m", has_ass=True,
                                    verdict="uniform", start_med=1.5))[0].kind == "uniform"
    r = fixmod.plan_fix(EpResult(ep="E", mkv="m", has_ass=True,
                                 verdict="break", front_med=0.0, back_med=1.5))
    assert r[0].kind == "break" and r[0].cut == 720.0
    assert fixmod.plan_fix(EpResult(ep="E", mkv="m", has_ass=True,
                                    verdict="end_short", end_med=-0.9))[0].kind == "end_extend"
    # 无需修复的判定 -> 空动作
    assert fixmod.plan_fix(EpResult(ep="E", mkv="m", has_ass=True, verdict="ok")) == []
    assert fixmod.plan_fix(EpResult(ep="E", mkv="m", has_ass=False, verdict="no_ass")) == []


def test_fix_series_dry_run_does_not_write(tmp_path):
    season = tmp_path / "Season 01"
    season.mkdir()
    (season / "E1.mkv").write_bytes(b"x")
    ass = season / ("E1" + ".default.chi.zh-cn.ass")
    original = _HEADER + _dlg(10.0, 13.0, "hello world one")
    ass.write_text(original, encoding="utf-8")

    # 假体检：判 uniform（有偏移），但 dry-run 只规划不落刀
    def fake_inspect(mkv, ass_path):
        return EpResult(ep=os.path.basename(mkv), mkv=mkv, has_ass=True,
                        verdict="uniform", start_med=1.5, end_med=1.5,
                        front_med=1.5, back_med=1.5)

    results = fixmod.fix_series(str(season), dry_run=True, inspect_ep=fake_inspect)
    assert len(results) == 1
    assert results[0].actions and results[0].actions[0].kind == "uniform"
    assert results[0].changed == 0
    assert not results[0].done
    # 文件一个字没动
    assert ass.read_text(encoding="utf-8") == original


def test_fix_series_real_dryrun_plans(tmp_path):
    """dry-run 规划出动作，但文件内容不变（真实 inspect 路径由 inspect_with_sdh 模拟）。"""
    sdh = _sdh_series(10.0)
    season = tmp_path / "Season 01"
    season.mkdir()
    (season / "E1.mkv").write_bytes(b"x")
    ass = season / ("E1" + ".default.chi.zh-cn.ass")
    _write_ass(str(ass), [(s + 1.5, e + 1.5, t) for (s, e, t) in sdh])
    original = ass.read_text(encoding="utf-8")

    def fake_inspect(mkv, ass_path):
        return inspect_with_sdh(ass_path, sdh, ep="E1", mkv="E1.mkv")

    results = fixmod.fix_series(str(season), dry_run=True, inspect_ep=fake_inspect)
    assert results[0].actions and results[0].actions[0].kind == "uniform"
    assert ass.read_text(encoding="utf-8") == original

# ---------------------------------------------------------------------------
# 防叠屏回归（E07 事故：end_extend 全片延长导致相邻对白叠屏半屏）
# ---------------------------------------------------------------------------

def test_end_extend_no_overlap(tmp_path):
    """首尾相接的对白，end_extend 后不得与下一条同轨 cue 重叠。"""
    sdh = _sdh_series(10.0)  # 4s 间隔、3s 长、1s 缝隙
    ass_file = tmp_path / "E1.ass"
    _write_ass(str(ass_file), [(s, e - 1.0, t) for (s, e, t) in sdh])
    before = inspect_with_sdh(str(ass_file), sdh, ep="E1", mkv="E1.mkv")
    res = fixmod.fix_episode(str(ass_file), before, _recheck(str(ass_file), sdh))
    assert res.actions[0].kind == "end_extend"
    cues = parse_ass(str(ass_file))
    body = sorted((c for c in cues if c.is_dialogue), key=lambda c: c.start)
    for prev, nxt in zip(body, body[1:]):
        assert prev.end <= nxt.start + 1e-9, \
            f"叠屏: [{prev.start}-{prev.end}] 压着 [{nxt.start}-{nxt.end}]"
