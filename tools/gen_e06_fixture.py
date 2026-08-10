"""Build tests/fixtures/subs S06E06 segment fixtures from the real 病灶 file.

One-off generator (not part of the test run): reads /tmp/e06_backup.ass and
the freshly-extracted SDH track, slices a [560, 775] window around the
museum-scene segment, and writes:
  - e06_sdh.srt        SDH reference slice
  - e06_seg_bad.ass    病灶 slice (segment still misaligned)
  - e06_seg_fixed.ass  修复 slice (segment shifted by +shift)

Run: .venv/bin/python tools/gen_e06_fixture.py
"""
from __future__ import annotations
from pathlib import Path

BACKUP = "/tmp/e06_backup.ass"
SDH = "/tmp/e06_sdh_fresh.srt"
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "subs"
LO, HI = 250.0, 1100.0

from mediaforge.subs.ass import parse_srt, ts2sec, sec2ts
from mediaforge.subs.inspect import _match_sdh, _med  # noqa: F401


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- SDH slice ----
    sdh = [c for c in parse_srt(SDH) if LO - 6 <= c[0] <= HI + 6]
    srt_lines = []
    for i, (st, en, txt) in enumerate(sdh, 1):
        def _ts(t: float) -> str:
            hh = int(t // 3600); mm = int((t % 3600) // 60)
            ss = int(t % 60); ms = int(round((t - int(t)) * 1000))
            if ms >= 1000: ms = 999
            return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"
        srt_lines.append(f"{i}\n{_ts(st)} --> {_ts(en)}\n{txt}\n")
    (OUT / "e06_sdh.srt").write_text("\n".join(srt_lines), encoding="utf-8")

    # ---- ASS slice: bad ----
    raw_lines = open(BACKUP, encoding="utf-8", errors="ignore").readlines()
    header = []
    i = 0
    # keep script-info + styles + events format header up to first Dialogue
    while i < len(raw_lines) and not raw_lines[i].startswith("Dialogue:"):
        header.append(raw_lines[i]); i += 1
    dlg_lines = [ln for ln in raw_lines if ln.startswith("Dialogue:")]
    inwin = [ln for ln in dlg_lines if LO <= ts2sec(ln.split(",", 9)[1]) <= HI]
    (OUT / "e06_seg_bad.ass").write_text("".join(header + inwin), encoding="utf-8")

    # ---- detect on the slice to get segment ----
    from mediaforge.subs import inspect
    matched = _match_sdh(inspect.parse_ass(str(OUT / "e06_seg_bad.ass")), sdh)
    offs = sorted((cue.start, cue.start - st) for (cue, st, en) in matched)
    starts = [s for s, _ in offs]; ds = [d for _, d in offs]
    n = len(starts)
    sm = [_med(ds[max(0, i - 4):min(n, i + 5)]) for i in range(n)]
    base = _med(sm)
    devpts = [abs(x - base) > 1.0 for x in sm]
    runs = []; cur = None
    for idx, v in enumerate(devpts):
        if v and cur is None: cur = [idx, idx]
        elif v: cur[1] = idx
        elif cur is not None: runs.append(cur); cur = None
    if cur: runs.append(cur)
    merged = []
    for rlo, rhi in runs:
        if merged and starts[rlo] - merged[-1][2] < 20.0:
            merged[-1][1] = rhi; merged[-1][2] = starts[rhi]
        else: merged.append([rlo, rhi, starts[rhi]])
    segs = []
    for rlo, rhi, _ in merged:
        dur = starts[rhi] - starts[rlo]
        sh = _med(ds[rlo:rhi + 1])
        if dur > 30.0 and abs(sh - base) > 1.0:
            segs.append((starts[rlo], starts[rhi], sh))
    assert segs, "no segment detected on slice"
    cstart, cend, shift = segs[0]
    print(f"detected on slice: cut_start={cstart:.1f} cut_end={cend:.1f} shift={shift:.3f}")

    # ---- fixed slice: shift cues in [cstart, cend] by -shift ----
    fixed_lines = list(header)
    import re
    for ln in inwin:
        parts = ln.split(",", 9)
        st = ts2sec(parts[1])
        if cstart <= st <= cend:
            parts[1] = sec2ts(ts2sec(parts[1]) - shift)
            parts[2] = sec2ts(ts2sec(parts[2]) - shift)
            ln = ",".join(parts)
        fixed_lines.append(ln)
    (OUT / "e06_seg_fixed.ass").write_text("".join(fixed_lines), encoding="utf-8")
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()