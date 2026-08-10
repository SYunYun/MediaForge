"""ASS 字幕解析与时间工具 —— subs 模块公共基础。

把 S06 错轴案里验证过的 ASS 处理逻辑固化成可复用函数：
- Dialogue 行解析（时间 + 提取内联英文段）
- ASS/SRT 时间码 <-> 秒 转换
- 整条/分段时间平移（含 `next_start` 边界钳制）
- 内容归一化（用于和英轨匹配）
"""
from __future__ import annotations

import re
from typing import Optional

# 内联英文段：`中文\N{\fs50\c&H00D7D7D7&\b0}English...`
_EN_INLINE = re.compile(r"\\N\{\\[^}]*\}([^\\{]*)")
# 署名样式名（不参与对白体检）
_CREDIT_STYLES = ("片头", "片尾", "署名", "字幕", "特效", "纯色", "片尾")


def ts2sec(ts: str) -> float:
    """ASS/SRT 时间码 H:MM:SS.CC -> 秒。"""
    ts = ts.strip()
    h, m, rest = ts.split(":")
    s, cc = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cc) / 100


def sec2ts(t: float) -> str:
    """秒 -> ASS 时间码 H:MM:SS.CC。"""
    if t < 0:
        t = 0
    hh = int(t // 3600)
    mm = int((t % 3600) // 60)
    ss = int(t % 60)
    cc = int(round((t - int(t)) * 100))
    if cc >= 100:
        cc = 99
    return f"{hh}:{mm:02d}:{ss:02d}.{cc:02d}"


class AssCue:
    """一条 Dialogue 行（含原始行索引，便于回写）。"""

    __slots__ = ("line_idx", "start", "end", "style", "eng", "raw")

    def __init__(self, line_idx: int, start: float, end: float, style: str,
                 eng: str, raw: str):
        self.line_idx = line_idx
        self.start = start
        self.end = end
        self.style = style
        self.eng = eng       # 归一化后的英文片段（可能为空）
        self.raw = raw

    @property
    def is_dialogue(self) -> bool:
        return bool(self.eng)

    @property
    def is_credit(self) -> bool:
        return any(k in self.style for k in _CREDIT_STYLES)


def parse_ass(path: str) -> list[AssCue]:
    """解析 ASS 文件的 Dialogue 行。"""
    cues = []
    for idx, line in enumerate(open(path, encoding="utf-8", errors="ignore")):
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        eng = " ".join(_EN_INLINE.findall(parts[9]))
        eng = re.sub(r"[^\w\s]", " ", eng).lower()
        eng = re.sub(r"\s+", " ", eng).strip()
        cues.append(AssCue(
            line_idx=idx,
            start=ts2sec(parts[1]),
            end=ts2sec(parts[2]),
            style=parts[3].strip(),
            eng=eng,
            raw=line,
        ))
    return cues


def parse_srt(path: str) -> list[tuple[float, float, str]]:
    """解析 SRT 为 (start, end, 归一化文本)。"""
    t = open(path, encoding="utf-8", errors="ignore").read()
    cues = []
    for m in re.finditer(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})(.*?)(?=\n\d+\s*\n|\Z)",
        t, re.S,
    ):
        def _ts(x: str) -> float:
            a, b, c, d = re.split(r"[:.,]", x)
            # SRT 毫秒是 3 位小数，除以 1000（不是 ASS 厘秒的 /100）
            return int(a) * 3600 + int(b) * 60 + int(c) + int(d) / 1000

        txt = re.sub(r"<[^>]+>", "", m.group(3))
        txt = re.sub(r"{\\[^}]*}", "", txt)
        txt = re.sub(r"\[[^\]]*\]", "", txt)          # SDH 括号
        txt = re.sub(r"[^\w\s]", " ", txt).lower()
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            cues.append((_ts(m.group(1)), _ts(m.group(2)), txt))
    return cues


def extract_eng_track(mkv: str, out_srt: str) -> None:
    """提取 mkv 内嵌英轨到 SRT。

    不能硬编码 0:s:0——S08 前 9 集首条字幕轨是俄语，抓错轨会导致
    对齐基准全错（误判 no_match/break）。用 ffprobe 按 language=eng
    定位真实英轨索引，找不到再回退 0:s:0。
    """
    import json
    import subprocess

    track_idx = None
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index:stream_tags=language",
             "-of", "json", mkv],
            capture_output=True, text=True, check=True,
        )
        for s in json.loads(probe.stdout).get("streams", []):
            lang = (s.get("tags") or {}).get("language", "")
            if lang.lower().startswith("eng"):
                track_idx = s["index"]
                break
    except Exception:
        track_idx = None

    map_spec = f"0:{track_idx}" if track_idx is not None else "0:s:0"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mkv,
         "-map", map_spec, "-c:s", "srt", out_srt],
        check=True,
    )


def norm_tokens(s: str) -> set[str]:
    """归一化文本为小写词集。输入假定英文（中文会被滤掉）。"""
    s = s.lower()
    return set(re.sub(r"[^a-z0-9 ]", " ", s).split())


def shift_ass_file(path: str, cue_list: list[AssCue], shift: float,
                   cut: Optional[float] = None) -> int:
    """把 ASS 的 Dialogue 行时间整体平移 shift 秒。

    cut 非空时只平移 start >= cut 的 cue（分段修正用）。
    返回实际修改的行数。只延长不移早由调用方保证 shift 符号。
    """
    lines = open(path, encoding="utf-8", errors="ignore").readlines()
    changed = 0
    for cue in cue_list:
        if cut is not None and cue.start < cut:
            continue
        parts = cue.raw.split(",", 9)
        if len(parts) < 10:
            continue
        parts[1] = sec2ts(cue.start + shift)
        parts[2] = sec2ts(cue.end + shift)
        lines[cue.line_idx] = ",".join(parts)
        changed += 1
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return changed


def shift_window_ass_file(path: str, cue_list: list[AssCue], shift: float,
                          cut_start: float, cut_end: float) -> int:
    """把 start 落在 [cut_start, cut_end] 窗口内的 cue 平移 shift 秒。

    分段偏移（segment）修复用：只动错位区段，不动正常区段。返回修改行数。
    """
    lines = open(path, encoding="utf-8", errors="ignore").readlines()
    changed = 0
    for cue in cue_list:
        if not (cut_start <= cue.start <= cut_end):
            continue
        parts = cue.raw.split(",", 9)
        if len(parts) < 10:
            continue
        parts[1] = sec2ts(cue.start + shift)
        parts[2] = sec2ts(cue.end + shift)
        lines[cue.line_idx] = ",".join(parts)
        changed += 1
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return changed


def extend_ends_ass_file(path: str, cue_list: list[AssCue], delta: float,
                         min_dur: float = 0.05, gap: float = 0.01) -> int:
    """把每条 Dialogue 的 End 延长 delta 秒（Start 不动）—— End 偏短修复。

    复检用的是 End 中位差，末段延长只改 End、保留 Start，保证对齐不受扰动。
    End 延长后不得越过 Start（钳到至少 min_dur 时长）。
    关键钳制：延长不得越过"下一条同 style cue 的 Start - gap"——
    否则相邻对白互相叠屏（E07 事故：全片延长 0.72s 后屏幕堆半屏）。
    该钳制同时自动限幅：中段对白间隔小，只能延到缝隙宽；
    末段无后继 cue 的才能真正延满 delta——恰好贴合 end_short 语义。
    返回修改行数。
    """
    # 同 style 的下一条 cue start，用于钳制叠屏
    next_start: dict[int, float] = {}
    by_style: dict[str, list[AssCue]] = {}
    for c in cue_list:
        if c.is_dialogue:
            by_style.setdefault(c.style, []).append(c)
    for group in by_style.values():
        group.sort(key=lambda c: c.start)
        for prev, nxt in zip(group, group[1:]):
            next_start[prev.line_idx] = nxt.start

    lines = open(path, encoding="utf-8", errors="ignore").readlines()
    changed = 0
    for cue in cue_list:
        if not cue.is_dialogue:
            continue
        parts = cue.raw.split(",", 9)
        if len(parts) < 10:
            continue
        new_end = cue.end + delta
        if new_end < cue.start + min_dur:
            new_end = cue.start + min_dur
        limit = next_start.get(cue.line_idx)
        if limit is not None and new_end > limit - gap:
            new_end = max(cue.start + min_dur, limit - gap)
        parts[2] = sec2ts(new_end)
        lines[cue.line_idx] = ",".join(parts)
        changed += 1
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return changed