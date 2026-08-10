"""分段偏移（segment）检测与修复回归测试 —— 用真实 S06E06 病灶 fixtures。

fixture 来自 /tmp/e06_backup.ass 与 mkv 内嵌 SDH 轨的 [250, 1100]s 切片：
  - e06_seg_bad.ass     病灶切片（博物馆场景 643-710s 整体早 ~1.68s）
  - e06_seg_fixed.ass   病灶切片 + 区内平移 -shift 后的修复版
  - e06_sdh.srt         SDK 参考切片
"""
import os
import shutil
import tempfile
from pathlib import Path

from mediaforge.subs.ass import parse_srt
from mediaforge.subs.inspect import (detect_segments, inspect_with_sdh, judge)
from mediaforge.subs import fix as fixmod

FIXT = Path(__file__).parent / "fixtures" / "subs"
SDH = parse_srt(str(FIXT / "e06_sdh.srt"))


def _inspect(name: str):
    return inspect_with_sdh(str(FIXT / name), SDH, ep="E06", mkv="E06.mkv")


def _recheck(path: str):
    return lambda p: inspect_with_sdh(p, SDH, ep="E06", mkv="E06.mkv")


def test_segment_bad_detected():
    """病灶样本判出 segment，切点落在 635-720s 内，偏移幅度 ~1.7s。"""
    r = _inspect("e06_seg_bad.ass")
    assert r.verdict == "segment", r.verdict
    assert 635 <= r.seg_cut_start <= 720, r.seg_cut_start
    assert 635 <= r.seg_cut_end <= 720, r.seg_cut_end
    assert r.seg_shift is not None and -2.0 <= r.seg_shift <= -1.0, r.seg_shift
    assert r.seg_n >= 15
    assert "segment" not in _inspect("e06_seg_fixed.ass").verdict


def test_segment_fixed_ok():
    """修复版样本不再判 segment，回到 ok/slight。"""
    r = _inspect("e06_seg_fixed.ass")
    assert r.verdict in ("ok", "slight"), r.verdict


def test_segment_fix_roundtrip_idempotent():
    """对病灶切片跑一次修复：segment 动作落刀、复检 ok；连修两次第二次空动作。"""
    d = tempfile.mkdtemp()
    try:
        tmp = os.path.join(d, "E06.ass")
        shutil.copy(str(FIXT / "e06_seg_bad.ass"), tmp)
        before = inspect_with_sdh(tmp, SDH, ep="E06", mkv="E06.mkv")
        assert before.verdict == "segment"

        res1 = fixmod.fix_episode(tmp, before, _recheck(tmp))
        assert res1.done, (res1.after.verdict if res1.after else None)
        assert res1.changed > 0
        act = res1.actions[0]
        assert act.kind == "segment"
        assert act.cut_start is not None and act.cut_end is not None
        assert act.cut_start >= before.seg_cut_start

        content1 = open(tmp, encoding="utf-8").read()

        # 第二次：复检已 ok，plan 为空、不改文件
        after = inspect_with_sdh(tmp, SDH, ep="E06", mkv="E06.mkv")
        assert after.verdict in ("ok", "slight"), after.verdict
        res2 = fixmod.fix_episode(tmp, after, _recheck(tmp))
        assert res2.actions == []
        assert res2.changed == 0
        assert res2.done
        assert open(tmp, encoding="utf-8").read() == content1
    finally:
        shutil.rmtree(d)


def test_segment_priority_over_end_short():
    """segment 重症优先于 end_short：同数值下非空 segments 判 segment。"""
    # 满足 end_short 条件（end_med < -0.5）但存在区段 -> segment
    assert judge(-0.2, -0.9, -0.2, -0.2, [{"dur": 45}]) == "segment"
    # 无区段才回落到 end_short
    assert judge(-0.2, -0.9, -0.2, -0.2) == "end_short"


def test_detect_segments_returns_empty_on_clean():
    """无持续偏离时 detect_segments 返回空。"""
    base = 60.0
    offsets = [(base + i, -0.2) for i in range(100)]
    assert detect_segments(offsets) == []


def test_detect_segments_finds_deviation():
    """中间一段持续早移 1.7s => 变点检测抓出该区段。"""
    offs = []
    for i in range(30):
        offs.append((i * 3.0 + 0.0, -0.2))            # 前段正常
    for i in range(25):
        offs.append((30 * 3.0 + i * 3.0, -1.7))       # 错位段（75s 长）
    for i in range(30):
        offs.append((55 * 3.0 + i * 3.0, -0.2))       # 后段正常
    segs = detect_segments(offs)
    assert segs
    s = segs[0]
    assert 85 <= s["cut_start"] <= 100, s["cut_start"]
    # 错位段 cue.start 从 90 到 90+24*3=162
    assert 155 <= s["cut_end"] <= 165, s["cut_end"]
    assert -2.0 < s["shift"] < -1.0, s["shift"]