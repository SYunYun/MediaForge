"""mediaforge subs 子命令实现（inspect / ledger）。"""
from __future__ import annotations

import json
import sys
from typing import Optional

from . import inspect as inspect_mod
from . import ledger as ledger_mod
from . import fix as fix_mod
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


def _fix_json(r: fix_mod.FixResult) -> dict:
    a = r.after
    return {
        "ep": _show_short(r.ep), "before": r.verdict,
        "actions": [{"kind": x.kind, "shift": round(x.shift, 3),
                     "cut": x.cut} for x in r.actions],
        "changed": r.changed, "done": r.done,
        "after": ({"verdict": a.verdict, "start_med": a.start_med,
                   "end_med": a.end_med, "front_med": a.front_med,
                   "back_med": a.back_med}
                  if a is not None else None),
    }


def cmd_fix(args, cfg) -> int:
    """自动修复 + 复检闭环。--dry-run 只报告不落刀。"""
    adapter = get_adapter(cfg)
    season_dir = adapter.locate_series(args.show, args.season)
    if not season_dir:
        print(f"找不到 {args.show} {args.season}（media.root={cfg.get('subs',{}).get('media',{}).get('root')}）",
              file=sys.stderr)
        return 2
    suffix = (cfg.get("subs", {}).get("naming", {})
              .get("ass_suffix", ".default.chi.zh-cn.ass"))
    results = fix_mod.fix_series(season_dir, suffix, dry_run=args.dry_run)

    # 复检结果写回台账；done 才设 done=true（闭环）
    if not args.dry_run:
        for r in results:
            ep_key = _show_short(r.ep)
            a = r.after
            ledger_mod.update_episode(
                args.show, args.season, ep_key,
                verdict=a.verdict if a else r.verdict,
                done=r.done,
                fix_before=r.verdict,
                fix_actions=[x.kind for x in r.actions],
                fix_changed=r.changed,
                n_cues=(a.n_cues if a else None),
                n_matched=(a.n_matched if a else None),
                start_med=(a.start_med if a else None),
                end_med=(a.end_med if a else None),
                front_med=(a.front_med if a else None),
                back_med=(a.back_med if a else None),
            )

    if args.json:
        print(json.dumps([_fix_json(r) for r in results],
                         ensure_ascii=False, indent=2))
        return 0

    # 人类表格
    mode = "DRY-RUN" if args.dry_run else "FIX"
    print(f"[{mode}] 修复 + 复检 · {args.show} {args.season}")
    print(f"{'集':<10} {'修复前':<10} {'操作':<24} {'改行':>4} {'复检':<8}")
    for r in results:
        op = "+".join(x.kind for x in r.actions) if r.actions else "-"
        after_v = r.after.verdict if r.after else "-"
        done_s = "✔ done" if r.done else ("待人工" if r.actions else "无需")
        print(f"{_show_short(r.ep):<10} {_verdict_name(r.verdict):<10} "
              f"{op:<24} {r.changed:>4} {done_s:<8} ({after_v})")
    done_n = sum(1 for r in results if r.done)
    fixable = [r for r in results if r.actions]
    print(f"\n共 {len(results)} 集：已闭环 {done_n}，需修复 {len(fixable)}"
          + ("" if args.dry_run else "（未闭环标'待人工'）"))
    return 0 if not fixable else 1


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