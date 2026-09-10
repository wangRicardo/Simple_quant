# -*- coding: utf-8 -*-
"""
命令行入口。

用法：
    # 分析指定标的
    python -m dragon.cli codes 002463,300308,603986

    # 全市场自动扫描龙头候选池（按主力资金 + 涨幅 + 资金占比）
    python -m dragon.cli scan --top 8

    # 附带阶段迁移轨迹回放
    python -m dragon.cli codes 002463 --history

    # 自定义输出文件
    python -m dragon.cli codes 002463 -o my_report.html
"""
from __future__ import annotations

import argparse
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from .datasource import EMClient
from . import analyzer as AZ
from . import screener as SC
from . import report as RP
from . import industry as IND
from . import site as SITE
from .stage import STAGE_META, confidence_label

BANNER = r"""
   ____                                   ___                    _
  |  _ \  _ __  __ _   __ _   ___   _ __ / _ \ _   _  ___  ___  | |_
  | | | || '__|/ _` | / _` | / _ \ | '__| | | | | | |/ __|/ _ \ | __|
  | |_| || |  | (_| || (_| || (_) || |  | |_| | |_| |\__ \  __/ | |_
  |____/ |_|   \__,_| \__, | \___/ |_|   \__\_\\__,_||___/\___|  \__|
                       |___/
          龙头战法量化系统  ·  机构行为四阶段识别引擎  v1.0
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dragon", description="龙头战法量化系统")
    sub = p.add_subparsers(dest="cmd")

    pc = sub.add_parser("codes", help="分析指定标的")
    pc.add_argument("codes", help="逗号分隔的股票代码，如 002463,300308")
    pc.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    pc.add_argument("--history", action="store_true", help="生成阶段迁移轨迹")
    pc.add_argument("--no-cache", action="store_true", help="禁用缓存")

    ps = sub.add_parser("scan", help="全市场扫描龙头候选池")
    ps.add_argument("--top", type=int, default=8, help="取前 N 只做深度判定")
    ps.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    ps.add_argument("--history", action="store_true", help="生成阶段迁移轨迹")
    ps.add_argument("--no-cache", action="store_true", help="禁用缓存")

    psite = sub.add_parser("site", help="生成/更新行业龙头每日看板网站")
    psite.add_argument("--per", type=int, default=3, help="每个行业取几只龙头（默认3）")
    psite.add_argument("-o", "--out", default="site", help="输出目录")
    psite.add_argument("--no-cache", action="store_true", help="禁用缓存")

    return p


def run_analysis(client: EMClient, items, with_history: bool, verbose=True,
                 fetch_extra: bool = True) -> tuple:
    """批量分析。返回 (analyses, history)。"""
    analyses, history = [], {}
    for i, (code, name) in enumerate(items, 1):
        if verbose:
            print(f"  [{i}/{len(items)}] 处理 {code} {name} ...")
        a = None
        for attempt in range(2):
            try:
                a = AZ.analyze_stock(client, code, name, verbose=False,
                                     fetch_extra=fetch_extra)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  [异常] {code}: {e}")
                a = None
            if a:
                break
            time.sleep(2.0 * (attempt + 1))
        if not a:
            if verbose:
                print(f"  [跳过] {code} {name} 数据获取失败")
            continue
        analyses.append(a)
        r = a["result"]
        if verbose:
            print(f"  ✓ {a['name']:<8}{a['code']}  "
                  f"{STAGE_META[r.stage]['name']:<6}"
                  f"({r.score:.0f}分/{confidence_label(r.confidence)})  "
                  f"基准日 {a['as_of']}")
        if with_history:
            h = AZ.replay_history(a, days=25)
            for row in h:
                row["name"] = a["name"]
            history[a["code"]] = h
        time.sleep(0.8)
    return analyses, history


def run_site(client: EMClient, args, t0: float) -> int:
    """生成行业龙头每日看板。"""
    print(f"[任务] 构建行业龙头看板（每行业 {args.per} 只）\n")

    universe = IND.build_industry_universe(client, per_industry=args.per,
                                           verbose=True)
    if not universe:
        print("\n[错误] 行业清单为空，可能是接口限流。请稍后重试。")
        return 1

    # 汇总待分析标的（去重，同一只票可能属于多个行业口径）
    codes = []
    seen = set()
    for ind in universe:
        for L in ind["leaders"]:
            if L["code"] not in seen:
                seen.add(L["code"])
                codes.append((L["code"], L["name"]))

    print(f"\n[分析] 共 {len(codes)} 只龙头待判定，预计需要几分钟 ...")
    analyses, _ = run_analysis(client, codes, with_history=False,
                               fetch_extra=False)
    by_code = {a["code"]: a for a in analyses}
    print(f"\n[分析] 成功 {len(by_code)}/{len(codes)} 只")

    as_of = analyses[0]["as_of"] if analyses else time.strftime("%Y-%m-%d")
    idx = SITE.generate(universe, by_code, as_of, out_dir=args.out)

    elapsed = time.time() - t0
    print(f"\n[完成] 耗时 {elapsed:.0f}s")
    print(f"[站点] {os.path.abspath(idx)}")
    print(f"[数据] {os.path.abspath(os.path.join(args.out, 'data.json'))}")
    print(f"[缓存] {client.stats()}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    print(BANNER)
    if not args.cmd:
        build_parser().print_help()
        return 1

    cache_dir = ".cache/dragon"
    min_interval = 0.5
    if getattr(args, "no_cache", False):
        cache_dir = ".cache/dragon_nocache"
    client = EMClient(cache_dir=cache_dir, verbose=True, min_interval=min_interval)

    t0 = time.time()

    if args.cmd == "site":
        return run_site(client, args, t0)

    if args.cmd == "codes":
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        print(f"[任务] 分析 {len(codes)} 只标的: {', '.join(codes)}\n")
        items = [(c, "") for c in codes]
        note = ""
    else:
        print(f"[任务] 全市场扫描龙头候选池（top {args.top}）\n")
        if hasattr(SC, "board_scan"):
            SC.board_scan(client, top_n=6, verbose=True)
            print()
        cands = SC.scan(client, top_n=args.top, verbose=True)
        print()
        if not cands:
            print("[错误] 未筛选出候选标的，可能是接口限流。请稍后重试或用 codes 模式指定标的。")
            return 1
        items = [(c["code"], c["name"]) for c in cands]
        note = ("<b>候选池来源</b>：本报告标的由系统从全市场自动扫描产生，"
                "筛选条件为「主力资金净流入 &gt; 0 + 资金占比为正 + 涨幅居前」，"
                "再按龙头相评分排序取前若干只。")

    # 批量扫描模式跳过融资融券等辅助接口：一是节省请求配额防止限流，
    # 二是该指标仅占撤离期 1.2 权重，对结论影响有限。
    analyses, history = run_analysis(
        client, items,
        with_history=getattr(args, "history", False),
        fetch_extra=(args.cmd == "codes"))

    if not analyses:
        print("\n[错误] 没有成功分析的标的。")
        return 1

    elapsed = time.time() - t0
    out = args.out or os.path.join(
        os.getcwd(), f"龙头战法阶段判定报告_{time.strftime('%Y%m%d_%H%M')}.html")
    html = RP.render(analyses, history if history else None,
                     watchlist_note=note, elapsed=elapsed)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[完成] 耗时 {elapsed:.1f}s，共分析 {len(analyses)} 只标的")
    print(f"[输出] {out}")
    print(f"[缓存] {client.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
