"""字幕体检器 —— 把 S06 错轴案验证过的"两段式体检"固化成规则。

判定逻辑（对齐 bilingual-subtitle-pipeline 技能的实测结论）：
- 内容匹配：ASS 的英文内联段 vs mkv 内嵌 SDH 英轨（±5s 时间窗防跨段错配）
- Start 差：ASS.start - SDH.start
- End 差：  ASS.end   - SDH.end
- 判定序列：
    1. 片中断裂：前段(<720s)与后段(>=720s)的 Start 中位差缺口 >0.5s
    2. 均匀错轴：整体 Start 中位差 |med| >0.6s
    3. End 偏短：Start 已对齐但 End 中位差 < -0.5s
    4. 正常：全部落在惯例区间（-0.4~+0.2s）
输出：每集判定 + 可复检的数值。
"""
from __future__ import annotations

import bisect
import os
from dataclasses import dataclass, field
from typing import Optional

from .ass import AssCue, extract_eng_track, norm_tokens, parse_ass, parse_srt

# 惯例：SDH 英轨按惯例比语音提前 0.3-0.4s，Start 落在该区间视为对齐
START_OK_LO, START_OK_HI = -0.5, 0.3
# 断裂判定：前后段中位差缺口
BREAK_GAP = 0.5
# 均匀错轴判定阈值
UNIFORM_THRESHOLD = 0.6
# 分界点（S06 实测片中段断裂发生在 ~12:00）
CUT = 720.0
# 内容匹配时间窗（防台词重复跨段错配）
MATCH_WIN = 5.0
# SDH 匹配最少共同词
MIN_COMMON = 2


@dataclass
class EpResult:
    """单集体检结果。"""
    ep: str
    mkv: str
    has_ass: bool
    n_cues: int = 0
    n_matched: int = 0
    start_med: Optional[float] = None
    end_med: Optional[float] = None
    front_med: Optional[float] = None   # 前段(<720s) Start 中位
    back_med: Optional[float] = None    # 后段(>=720s) Start 中位
    verdict: str = "no_ass"

    @property
    def ok(self) -> bool:
        return self.verdict == "ok"


def _match_sdh(ass_cues: list[AssCue], sdh: list[tuple[float, float, str]]
               ) -> list[tuple[AssCue, float, float]]:
    """内容匹配 ASS cue -> (cue, 匹配SDH start, 匹配SDH end)。

    含英文的 cue 且匹配到 SDH。全表扫描 + ±5s 时间窗（防台词重复跨段错配），
    取 |Start 差| 最小的匹配。注意：不能用 bisect 局部窗——SDH 是合并条
    结构，真正匹配的 cue 常超出局部窗口（S06 实战教训）。
    """
    sdh_toks = [(st, en, norm_tokens(seng)) for st, en, seng in sdh]
    out = []
    for cue in ass_cues:
        if not cue.is_dialogue:
            continue
        a_toks = norm_tokens(cue.eng)
        best = None
        for st, en, s_toks in sdh_toks:
            if abs(cue.start - st) > MATCH_WIN:
                continue
            common = len(a_toks & s_toks)
            if common >= MIN_COMMON:
                d = cue.start - st
                if best is None or abs(d) < abs(best[3]):
                    best = (st, en, common, d)
        if best:
            out.append((cue, best[0], best[1]))
    return out


def _med(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    return s[len(s) // 2]


def inspect_episode(mkv: str, ass_path: str, srt_tmp: str = "/tmp/mf_subs_sdh.srt"
                    ) -> EpResult:
    """体检一集。返回 EpResult。"""
    ep = os.path.basename(mkv)
    if not os.path.exists(ass_path):
        return EpResult(ep=ep, mkv=mkv, has_ass=False, verdict="no_ass")
    try:
        extract_eng_track(mkv, srt_tmp)
        sdh = parse_srt(srt_tmp)
    except Exception:
        # 无内嵌英轨 / 无法提取：只能做"有没有字幕"级别检查
        ass_cues = parse_ass(ass_path)
        return EpResult(ep=ep, mkv=mkv, has_ass=True, n_cues=len(ass_cues),
                        verdict="no_eng_track")

    ass_cues = parse_ass(ass_path)
    matched = _match_sdh(ass_cues, sdh)
    if not matched:
        return EpResult(ep=ep, mkv=mkv, has_ass=True, n_cues=len(ass_cues),
                        verdict="no_match")

    d_start = [cue.start - st for (cue, st, en) in matched]
    d_end = [cue.end - en for (cue, st, en) in matched]
    front = [cue.start - st for (cue, st, en) in matched if cue.start < CUT]
    back = [cue.start - st for (cue, st, en) in matched if cue.start >= CUT]

    start_med = _med(d_start)
    end_med = _med(d_end)
    front_med = _med(front)
    back_med = _med(back)

    result = EpResult(
        ep=ep, mkv=mkv, has_ass=True,
        n_cues=len(ass_cues), n_matched=len(matched),
        start_med=start_med, end_med=end_med, front_med=front_med,
        back_med=back_med,
    )
    result.verdict = judge(start_med, end_med, front_med, back_med)
    return result


def judge(start_med: Optional[float], end_med: Optional[float],
          front_med: Optional[float], back_med: Optional[float]) -> str:
    """按体检数值判定。返回 verdict 字符串。"""
    if start_med is None:
        return "no_match"
    # 1) 片中断裂：前后段缺口
    if front_med is not None and back_med is not None \
            and abs(back_med - front_med) > BREAK_GAP:
        return "break"
    # 2) 均匀错轴
    if abs(start_med) > UNIFORM_THRESHOLD:
        return "uniform"
    # 3) End 偏短（Start 已对齐但 End 偏早）
    if end_med is not None and end_med < -0.5:
        return "end_short"
    # 4) 正常
    if START_OK_LO <= start_med <= START_OK_HI:
        return "ok"
    return "slight"


def inspect_series(season_dir: str, ass_suffix: str = ".default.chi.zh-cn.ass"
                   ) -> list[EpResult]:
    """体检一个季目录下所有 mkv。"""
    results = []
    for mkv in sorted(os.listdir(season_dir)):
        if not mkv.endswith((".mkv", ".mp4")):
            continue
        mkv_path = os.path.join(season_dir, mkv)
        ass_path = os.path.splitext(mkv_path)[0] + ass_suffix
        results.append(inspect_episode(mkv_path, ass_path))
    return results