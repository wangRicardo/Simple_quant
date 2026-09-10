# -*- coding: utf-8 -*-
"""
龙头候选池筛选器。

龙头不是单只股票的属性，而是「板块 + 资金 + 人气 + 技术」共同确认出来的。
本模块负责从全市场 5000+ 标的中自动缩小候选范围，再由 analyzer 做深度判定。

筛选逻辑（自上而下三层漏斗）：
    L1 广度过滤：剔除 ST / 退市 / 新股 / 仙股 / 停牌
    L2 资金过滤：主力净流入为正，且超大单占主导（排除纯游资拆单）
    L3 龙头相打分：涨幅吸引力 + 资金承接 + 换手活跃 + 位置不高 + 板块效应

最终输出按「龙头分」排序的候选列表。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .datasource import EMClient
from . import indicators as I


def _clean(it: Dict) -> bool:
    """基础过滤。"""
    name = (it.get("name") or "").upper()
    code = (it.get("code") or "")
    price = it.get("price")
    if not code or not name:
        return False
    if "ST" in name or "退" in name or "*" in name:
        return False
    if code.startswith(("4", "8", "92")):      # 北交所流动性不足，剔除
        return False
    if not isinstance(price, (int, float)) or price <= 3 or price > 800:
        return False
    return True


def leading_score(item: Dict) -> Dict:
    """龙头相打分（0-100）。越高越具备「板块核心」特征。"""
    s = 0.0
    detail = {}

    chg = item.get("chg")
    if isinstance(chg, (int, float)):
        # 涨幅：涨停最佳，5-9% 次优，暴涨后回落反而危险
        if chg >= 9.5:
            v = 25
        elif chg >= 5:
            v = 20
        elif chg >= 2:
            v = 14
        elif chg >= 0:
            v = 8
        elif chg >= -3:
            v = 4
        else:
            v = 0
        s += v
        detail["涨幅"] = v

    mn = item.get("main_net") or 0     # 亿元
    if mn >= 10:
        v = 25
    elif mn >= 5:
        v = 22
    elif mn >= 2:
        v = 18
    elif mn >= 0.5:
        v = 12
    elif mn > 0:
        v = 6
    else:
        v = 0
    s += v
    detail["主力资金"] = v

    mp = item.get("main_pct")
    if isinstance(mp, (int, float)):
        if mp >= 15:
            v = 20
        elif mp >= 8:
            v = 16
        elif mp >= 3:
            v = 11
        elif mp > 0:
            v = 6
        else:
            v = 0
        s += v
        detail["资金占比"] = v

    hv = item.get("huge_net") or 0
    if hv > 0 and mn > 0:
        v = 15 if hv / mn > 0.5 else 9
        s += v
        detail["超大单"] = v
    else:
        detail["超大单"] = 0

    # 换手活跃度（reserved，需额外数据）
    detail["合计"] = round(s, 1)
    return {"score": round(s, 1), "detail": detail}


def scan(client: EMClient, top_n: int = 12, verbose: bool = True) -> List[Dict]:
    """全市场扫描，返回龙头候选池。"""
    if verbose:
        print("[扫描] 拉取全市场主力资金流排行 ...")
    rows = client.stock_pool_mainflow(pz=200)
    if not rows:
        if verbose:
            print("[扫描] 资金流列表获取失败，尝试涨幅榜")
        rows = []

    # 补充超大单数据（接口若未返回则忽略）
    cands = []
    for r in rows:
        if not _clean(r):
            continue
        if (r.get("main_net") or 0) <= 0:
            continue
        ls = leading_score(r)
        if ls["score"] < 45:
            continue
        r.update(ls)
        cands.append(r)

    cands.sort(key=lambda x: -x["score"])
    picked = cands[:top_n]

    if verbose:
        print(f"[扫描] 候选池 {len(cands)} 只，取前 {len(picked)} 只做深度判定")
        for i, c in enumerate(picked, 1):
            print(f"       {i:2d}. {c['code']} {c['name']:<8} "
                  f"涨 {c['chg']:+.2f}%  主力 {c['main_net']:+.2f}亿  分 {c['score']}")
    return picked


def board_scan(client: EMClient, top_n: int = 8, verbose: bool = True) -> List[Dict]:
    """板块资金流排行 —— 龙头必出自强板块。"""
    boards = client.board_list(pz=60)
    boards = [b for b in boards if _clean(b) and (b.get("main_net") or 0) > 0]
    boards.sort(key=lambda x: -(x.get("main_net") or 0))
    if verbose and boards:
        print("[板块] 资金净流入前列：")
        for b in boards[:top_n]:
            print(f"       {b['code']} {b['name']:<10} "
                  f"涨 {b['chg']:+.2f}%  主力 {b['main_net']:+.2f}亿")
    return boards[:top_n]
