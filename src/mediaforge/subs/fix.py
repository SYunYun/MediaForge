"""字幕自动修复 —— 自愈闭环第二步。

对 judge 判出的偏移类型执行对应修复，然后自动复检（重跑体检），
复检通过（done）才闭环；重复执行幂等（复检门禁保证不叠加偏移）。

修复映射（judge verdict -> 操作）：
- uniform   均匀错轴：整体平移 -start_med（Start/End 同移）
- break     片中断裂：后段(>=CUT)平移 front_med - back_med（对齐前段基线）
- segment   分段偏移：只平移 [cut_start, cut_end] 窗口内 cue，幅度 -shift（区段中位）
- end_short End 偏短：每条 Dialogue 的 End 延长 -end_med（Start 不动）

无修复（no_ass/no_eng_track/no_match/ok/slight）不落刀，直接报告。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from .ass import (parse_ass, shift_ass_file, shift_window_ass_file,
                  extend_ends_ass_file)
from .inspect import CUT, EpResult

# 需要落刀修复的 verdict
FIXABLE = ("uniform", "break", "segment", "end_short")
# 复检验收：这些判定视为"已闭环"
DONE_VERDICTS = ("ok", "slight")


@dataclass
class FixAction:
    """一次原子修复操作。"""
    kind: str                     # uniform | break | segment | end_extend
    shift: float                  # 平移/延长秒数
    cut: Optional[float] = None   # break 用：只动 start >= cut 的后段
    cut_start: Optional[float] = None  # segment 用：窗口左界（s）
    cut_end: Optional[float] = None    # segment 用：窗口右界（s）


@dataclass
class FixResult:
    """单集修复结果（含复检）。"""
    ep: str
    verdict: str                  # 修复前判定
    actions: list[FixAction] = field(default_factory=list)
    changed: int = 0              # 实际修改的行数
    after: Optional[EpResult] = None
    done: bool = False            # 复检通过才 true


def plan_fix(r: EpResult) -> list[FixAction]:
    """由体检结果规划修复动作（不读文件，纯函数）。"""
    if r.verdict == "uniform" and r.start_med is not None:
        return [FixAction("uniform", -r.start_med)]
    if r.verdict == "break" and r.front_med is not None and r.back_med is not None:
        # 后段对齐前段基线：back 需要移 front_med - back_med
        return [FixAction("break", r.front_med - r.back_med, cut=CUT)]
    if r.verdict == "segment" and r.seg_shift is not None \
            and r.seg_cut_start is not None and r.seg_cut_end is not None:
        # 区内 cue 平移 -shift（把区段中位偏移归零）；只动 [cut_start, cut_end]
        return [FixAction("segment", -r.seg_shift,
                          cut_start=r.seg_cut_start, cut_end=r.seg_cut_end)]
    if r.verdict == "end_short" and r.end_med is not None:
        return [FixAction("end_extend", -r.end_med)]
    return []


def apply_fix(ass_path: str, actions: list[FixAction]) -> int:
    """把动作依次落到 ASS 文件。返回修改行数。"""
    changed = 0
    for act in actions:
        cues = parse_ass(ass_path)  # 每步重新解析，保证基于当前文件状态
        if act.kind == "end_extend":
            changed += extend_ends_ass_file(ass_path, cues, act.shift)
        elif act.kind == "segment":
            changed += shift_window_ass_file(
                ass_path, cues, act.shift, act.cut_start, act.cut_end)
        else:
            changed += shift_ass_file(ass_path, cues, act.shift, cut=act.cut)
    return changed


def fix_episode(ass_path: str, before: EpResult,
                re_inspect: Callable[[str], EpResult]) -> FixResult:
    """修复一集并复检。

    re_inspect 是复检回调（生产=inspect_episode，测试=inspect_with_sdh），
    幂等性由复检门禁保证：修完若仍异常则标 done=False 交人工品味，不硬修。
    """
    actions = plan_fix(before)
    if not actions:
        return FixResult(ep=before.ep, verdict=before.verdict,
                         changed=False, after=before,
                         done=before.verdict in DONE_VERDICTS)
    changed = apply_fix(ass_path, actions)
    after = re_inspect(ass_path)
    done = after.verdict in DONE_VERDICTS
    return FixResult(ep=before.ep, verdict=before.verdict,
                     actions=actions, changed=changed, after=after, done=done)


def fix_series(season_dir: str, ass_suffix: str = ".default.chi.zh-cn.ass",
               dry_run: bool = False,
               inspect_ep: Optional[Callable] = None) -> list[FixResult]:
    """修一个季目录下所有可修 mkv。返回每集 FixResult。

    inspect_ep 默认用真实 mkv 复检；dry_run=True 只规划不落刀。
    """
    from .inspect import inspect_episode, inspect_series
    if inspect_ep is None:
        inspect_ep = inspect_episode
    results = []
    for mkv in sorted(os.listdir(season_dir)):
        if not mkv.endswith((".mkv", ".mp4")):
            continue
        mkv_path = os.path.join(season_dir, mkv)
        ass_path = os.path.splitext(mkv_path)[0] + ass_suffix
        before = inspect_ep(mkv_path, ass_path)
        actions = plan_fix(before)
        if not actions:
            results.append(FixResult(
                ep=os.path.basename(mkv), verdict=before.verdict,
                changed=False, after=before,
                done=before.verdict in DONE_VERDICTS))
            continue
        if dry_run:
            results.append(FixResult(
                ep=os.path.basename(mkv), verdict=before.verdict,
                actions=actions, changed=False, after=before, done=False))
            continue
        results.append(fix_episode(ass_path, before,
                                   lambda p, m=mkv_path: inspect_ep(m, p)))
    return results