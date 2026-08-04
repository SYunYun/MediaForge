"""mediaforge CLI —— 三段式工作流：search → pick → add。

子命令：
  indexers list|update   管理索引器定义卡缓存
  search <关键词>        多索引器并发搜索 + 打分排序（人类表格 / --json）
  pick <关键词> [--index N]  搜索后按序号选（交互或参数化）
  add <magnet|infohash>  幂等投喂 qbit（infohash 判重）
  config show|init       查看 / 初始化配置

运行：`mediaforge ...`（pip install -e . 后）或 `python -m mediaforge.cli ...`
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from . import __version__
from .cardigann.engine import Query, search as engine_search
from .cardigann.loader import DefinitionLoader
from .config import CONFIG_PATH, ensure_config, load_config, redact
from .feed.qbit import QbitClient, QbitError, to_magnet
from .hunt.score import rank_releases

MAX_WORKERS = 4  # 项目铁律：不做 24 线程重活


class CliError(Exception):
    pass


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------


def human_size(size: Optional[int]) -> str:
    if not size:
        return "-"
    gb = size / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f}GB"
    return f"{size / (1024 ** 2):.0f}MB"


def _table(releases: list, explain: bool = False) -> str:
    rows = []
    for i, r in enumerate(releases, 1):
        bd = r.get("score_breakdown") or {}
        extra = ""
        if explain:
            extra = (
                f"  [s={bd.get('seeders', 0):g} sz={bd.get('size_band', 0):g}"
                f" g={bd.get('group', 0):g}{' anim' if bd.get('is_animation') else ''}]"
            )
        rows.append(
            f"{i:>3}  {r.get('score', 0):>5.1f}  {human_size(r.get('size')):>9}  "
            f"{str(r.get('seeders') or 0):>5}  {r.get('indexer', '-'):>12}  "
            f"{r.get('title', '')[:100]}{extra}"
        )
    header = f"{'#':>3}  {'score':>5}  {'size':>9}  {'seeds':>5}  {'indexer':>12}  title"
    return header + "\n" + "\n".join(rows)


def _out(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


# ---------------------------------------------------------------------------
# 搜索核心（search / pick 共用）
# ---------------------------------------------------------------------------


def _search_releases(keywords: str, indexer_ids: list, cfg: dict) -> tuple:
    """并发搜索（≤4 线程）。返回 (releases, errors)。"""
    proxy = cfg.get("proxy") or None
    timeout = int(cfg.get("timeout") or 12)
    loader = DefinitionLoader(proxy=proxy, timeout=timeout)

    def run_one(indexer_id: str):
        definition = loader.load(indexer_id)
        return engine_search(definition, Query(keywords=keywords),
                             proxy=proxy, timeout=timeout)

    releases, errors = [], {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(indexer_ids))) as pool:
        futures = {pool.submit(run_one, iid): iid for iid in indexer_ids}
        for fut in as_completed(futures):
            iid = futures[fut]
            try:
                releases.extend(fut.result())
            except Exception as exc:  # 单索引器失败不拖垮整体
                errors[iid] = f"{type(exc).__name__}: {exc}"
    return releases, errors


def _do_search(keywords: str, indexer_ids: list, cfg: dict) -> tuple:
    releases, errors = _search_releases(keywords, indexer_ids, cfg)
    ranked = rank_releases(releases, cfg)
    return ranked, errors


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_indexers(args, cfg) -> int:
    proxy = cfg.get("proxy") or None
    timeout = int(cfg.get("timeout") or 12)
    loader = DefinitionLoader(proxy=proxy, timeout=timeout)
    if args.action == "list":
        cached = loader.list_cached()
        _out(cached, args.json)
        return 0
    # update
    ids = [args.id] if args.id else None
    try:
        updated = loader.update(ids)
    except Exception as exc:
        print(f"更新失败（可试 --proxy http://127.0.0.1:7892）: {exc}", file=sys.stderr)
        return 1
    paths = [str(p) for p in updated]
    _out(paths, args.json)
    return 0


def _split_indexers(raw: Optional[str]) -> Optional[list]:
    """'yts,tpb' -> ['yts','tpb']；None/空 -> None。"""
    if not raw:
        return None
    ids = [i.strip() for i in raw.split(",") if i.strip()]
    return ids or None


def cmd_search(args, cfg) -> int:
    indexer_ids = _split_indexers(args.indexers) or cfg.get("indexers") or ["yts"]
    ranked, errors = _do_search(args.keywords, indexer_ids, cfg)
    if args.limit:
        ranked = ranked[: args.limit]
    if args.json:
        _out(ranked, True)
    else:
        print(_table(ranked, explain=args.explain))
        if errors:
            print(f"\n[警告] {len(errors)} 个索引器失败: " +
                  "; ".join(f"{k} ({v})" for k, v in errors.items()), file=sys.stderr)
    if not ranked and errors:
        return 2
    return 0


def _pick_release(ranked: list, index: Optional[int], keywords: str, args) -> int:
    if index is None:
        print(_table(ranked, explain=args.explain))
        raw = input(f"\n选择序号 1-{len(ranked)}（回车跳过）: ").strip()
        if not raw:
            print("已跳过。")
            return 0
        index = int(raw)
    if index < 1 or index > len(ranked):
        raise CliError(f"序号越界：1-{len(ranked)}")
    r = ranked[index - 1]
    magnet = r.get("download") or (to_magnet(r["infohash"], r.get("title", ""))
                                   if r.get("infohash") else "")
    payload = {
        "index": index,
        "title": r.get("title"),
        "score": r.get("score"),
        "infohash": r.get("infohash"),
        "size": r.get("size"),
        "seeders": r.get("seeders"),
        "indexer": r.get("indexer"),
        "magnet": magnet,
        "score_breakdown": r.get("score_breakdown"),
    }
    _out(payload, args.json)
    if not args.json:
        print("\n下一步: mediaforge add <magnet|infohash> [--paused]")
    return 0


def cmd_pick(args, cfg) -> int:
    indexer_ids = _split_indexers(args.indexers) or cfg.get("indexers") or ["yts"]
    ranked, errors = _do_search(args.keywords, indexer_ids, cfg)
    if args.json and args.index is None:
        # json 模式下无 --index 就整表输出，交给调用方自己选
        _out(ranked, True)
        return 0
    if not ranked:
        print(f"无结果（{len(errors)} 个索引器失败）", file=sys.stderr)
        return 2
    return _pick_release(ranked, args.index, args.keywords, args)


def cmd_add(args, cfg) -> int:
    qcfg = dict(cfg.get("qbit") or {})
    qcfg["paused"] = args.paused if args.paused is not None else bool(qcfg.get("paused"))
    try:
        client = QbitClient(qcfg, timeout=int(cfg.get("timeout") or 12))
        savepath = args.savepath or qcfg.get("savepath") or None
        result = client.add_magnet(
            args.magnet,
            paused=bool(qcfg["paused"]),
            category=args.category or None,
            savepath=savepath,
            path_map=qcfg.get("path_map") or [],
        )
    except QbitError as exc:
        _out({"ok": False, "error": str(exc)}, args.json)
        return 1
    if args.json:
        _out(result, True)
    else:
        status = result["status"]
        extra = f" paused={result.get('paused')}" if status == "added" else ""
        print(f"status={status}  hash={result.get('hash')}{extra}")
        if status == "added" and not qcfg["paused"]:
            print("任务已开始下载（paused=False）。")
    return 0


def cmd_config(args, cfg) -> int:
    if args.action == "init":
        path = ensure_config(force=args.force)
        print(f"配置已生成: {path}", file=sys.stderr)
        return 0
    # show
    _out(redact(cfg), args.json)
    print(f"\n# 配置文件: {CONFIG_PATH}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# argparse 装配
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediaforge",
        description="Agent 原生媒体栈工具箱 —— hunt（找种）模块",
    )
    parser.add_argument("--version", action="version", version=f"mediaforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_indexers = sub.add_parser("indexers", help="索引器定义卡管理")
    p_indexers.add_argument("action", choices=["list", "update"])
    p_indexers.add_argument("--id", help="只更新指定索引器")
    p_indexers.add_argument("--json", action="store_true")
    p_indexers.set_defaults(func=cmd_indexers)

    p_search = sub.add_parser("search", help="多索引器搜索 + 打分排序")
    p_search.add_argument("keywords", help="搜索关键词（如 'inside job'）")
    p_search.add_argument("--indexers", help="逗号分隔索引器 id，默认取 config")
    p_search.add_argument("--limit", type=int, help="只显示前 N 条")
    p_search.add_argument("--explain", action="store_true", help="表格模式显示评分分解")
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_pick = sub.add_parser("pick", help="搜索后按序号选（交互/参数化）")
    p_pick.add_argument("keywords")
    p_pick.add_argument("--indexers")
    p_pick.add_argument("--index", type=int, help="直接选第 N 条（不交互）")
    p_pick.add_argument("--explain", action="store_true")
    p_pick.add_argument("--json", action="store_true")
    p_pick.set_defaults(func=cmd_pick)

    p_add = sub.add_parser("add", help="幂等投喂 qbit")
    p_add.add_argument("magnet", help="magnet 链接或裸 40 位 infohash")
    p_add.add_argument("--paused", action="store_true", default=None,
                       help="只入队不下载（安全验证用）")
    p_add.add_argument("--category")
    p_add.add_argument("--savepath", help="宿主机下载目录（自动翻译容器路径）")
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(func=cmd_add)

    p_config = sub.add_parser("config", help="查看 / 初始化配置")
    p_config.add_argument("action", choices=["show", "init"])
    p_config.add_argument("--force", action="store_true", help="init 时覆盖现有配置")
    p_config.add_argument("--json", action="store_true")
    p_config.set_defaults(func=cmd_config)

    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config()
        return args.func(args, cfg)
    except CliError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
