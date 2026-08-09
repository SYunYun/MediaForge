"""mediaforge subs 子命令实现（inspect / ledger）。"""
from __future__ import annotations

import json
import sys
from typing import Optional

from . import inspect as inspect_mod
from . import ledger as ledger_mod
from .media import get_adapter


def _show_short(ep: str) -> str:
    import re
    m = re.search(r"(S\d+E\d+)", ep)
    return m.group(1) if m else ep[:24]


def _verdict_name(v: str) -> str:
    return {
        "ok": "OK",
        "break": "片中断裂",
        "uniform": "均匀错轴",
        "end_short": "End偏短",
        "slight": "轻微",
        "no_ass": "无字幕",
        "no_eng_track": "无英轨",
        "no_match": "无法匹配",
    }.get(v, v)


def cmd_inspect(args, cfg) -> int:
    adapter = get_adapter(cfg)
    season_dir = adapter.locate_series(args.show, args.season)
    if not season_dir:
        print(f"找不到 {args.show} {args.season}（media.root={cfg.get('subs',{}).get('media',{}).get('root')}）",
              file=sys.stderr)
        return 2
    results = inspect_mod.inspect_series(season_dir)
    # 体检结果写入台账（无感闭环：状态持久化，下次不用重扫）
    for r in results:
        ledger_mod.update_episode(
            args.show, args.season, _show_short(r.ep),
            mkv=r.mkv, has_ass=r.has_ass,
            verdict=r.verdict, n_cues=r.n_cues, n_matched=r.n_matched,
            start_med=r.start_med, end_med=r.end_med,
            front_med=r.front_med, back_med=r.back_med,
        )
    if args.json:
        out = [{
            "ep": _show_short(r.ep), "verdict": r.verdict,
            "n_cues": r.n_cues, "n_matched": r.n_matched,
            "start_med": r.start_med, "end_med": r.end_med,
            "front_med": r.front_med, "back_med": r.back_med,
        } for r in results]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    # 人类表格
    print(f"{'集':<10} {'判定':<10} {'cues':>5} {'mch':>4} {'Start':>7} {'End':>7} "
          f"{'前段':>7} {'后段':>7}")
    for r in results:
        def f(v): return f"{v:+.2f}" if v is not None else "  -  "
        ep = _show_short(r.ep)
        cues = r.n_cues if r.has_ass else "-"
        mch = r.n_matched if r.has_ass else "-"
        print(f"{ep:<10} {_verdict_name(r.verdict):<10} {str(cues):>5} {str(mch):>4} "
              f"{f(r.start_med):>7} {f(r.end_med):>7} {f(r.front_med):>7} {f(r.back_med):>7}")
    # 汇总
    from collections import Counter
    cnt = Counter(r.verdict for r in results)
    bad = [v for v in ("no_ass", "break", "uniform", "end_short") if cnt[v]]
    ok_n = cnt["ok"] + cnt["slight"]
    print(f"\n共 {len(results)} 集：OK/轻微 {ok_n}，异常 {sum(cnt[v] for v in bad)}")
    if bad:
        print("异常分布: " + ", ".join(f"{_verdict_name(v)}×{cnt[v]}" for v in bad))
    return 0 if not bad else 1


def cmd_ledger(args, cfg) -> int:
    data = ledger_mod.load_ledger(args.show, args.season)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    eps = data.get("episodes", {})
    if not eps:
        print(f"{args.show} {args.season} 台账为空（还没体检过）。")
        return 0
    print(f"台账 · {args.show} {args.season} · {len(eps)} 集")
    for k in sorted(eps):
        ep = eps[k]
        verdict = ep.get("verdict", "-")
        updated = ep.get("updated_at", "")[:16]
        print(f"  {k:<12} {verdict:<10} {updated}")
    return 0