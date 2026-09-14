# -*- coding: utf-8 -*-
"""
ETF 模块：热门 ETF 榜池 + 热度分 + 四阶段机会评分。

口径说明（重要，读结论前先看这里）：
  1. 榜池：沪深两市全部场内基金（东财板块 MK0021~MK0024，共 1600+ 只），
     按**当日成交额**降序取前 N，剔除货币型 ETF —— 货币 ETF 成交额常年
     巨大但没有「机构行为四阶段」的分析意义，混进来会污染热榜。
  2. 热度分（0~100，衡量「当下被交易/被资金关注的程度」）：
        成交额分位 × 45   榜内当日成交额排名百分位，流动性是热度的核心
      + 主力净流入强度 ×20  当日主力净额占成交额比（5% 封顶）
      + 量比 ×15          当日量比（1→0 分，3→满分）
      + 涨幅 ×10          当日涨跌幅（-2%→0 分，+4%→满分）
      + 量能趋势 ×10      近5日/前5日量能（0.9→0 分，1.7→满分）
     各分量先归一到 0~1 再加权；主力数据缺失时该分量记 0（不惩罚、不加成）。
  3. 机会分 / 风险分 / 阶段判定：与个股**共用 stage.py 打分卡**。差异：
        - ETF 无龙虎榜、无两融数据，相关证据自动降权（不计入分母）；
        - ETF 的换手率口径为「成交量/份额」，与个股「成交量/流通股本」
          量纲一致但数值普遍偏低，涉及换手的阈值命中率会下降；
        - 筹码模型基于量价换手推算，对 ETF 近似成立（T+0 套利盘的
          换手衰减与个股持有结构不同，精度低于个股）。
     解读 ETF 的阶段判定时按「弱一档置信」对待。
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from . import analyzer as AZ
from .stage import STAGE_META, action_scores, confidence_label

CLIST_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz={pz}&po=1&np=1"
    "&fltt=2&invt=2&fid=f6&fs=b:MK0021,b:MK0022,b:MK0023,b:MK0024"
    "&fields=f12,f14,f2,f3,f6,f8,f62,f184"
)

# 货币/现金管理型 ETF：成交额巨大但无阶段分析意义，从热榜剔除
MONEY_KEYWORDS = ("货币", "日利", "添益", "理财", "现金", "增利", "快线")


def to_tx_symbol_etf(code: str) -> str:
    """场内基金代码 → 腾讯行情符号。沪基金 5xxxxx，深基金 15/16/18。"""
    c = code.strip()
    if c.startswith("5"):
        return "sh" + c
    if c.startswith(("15", "16", "18")):
        return "sz" + c
    # 其余交给通用规则（理论上 ETF 不会走到这里）
    from .datasource import to_tx_symbol
    return to_tx_symbol(c)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _f(v) -> Optional[float]:
    """东财 fltt=2 下缺数会返回 '-' 等字符串。"""
    return float(v) if isinstance(v, (int, float)) else None


def hot_list(client, top_n: int = 30, pz: int = 80,
             verbose: bool = True) -> List[Dict]:
    """当日成交额最大的 N 只 ETF（剔除货币型）。返回按成交额降序的原始行。"""
    d = client.get_json(CLIST_URL.format(pz=pz))
    rows = (d.get("data") or {}).get("diff") or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    out: List[Dict] = []
    for r in rows:
        name = str(r.get("f14") or "")
        code = str(r.get("f12") or "")
        if "ETF" not in name:
            continue          # 排除 LOF / 封基等非 ETF 品种
        if any(k in name for k in MONEY_KEYWORDS):
            continue
        amt = _f(r.get("f6"))
        if amt is None or amt <= 0:
            continue
        out.append({
            "code": code,
            "name": name,
            "price": _f(r.get("f2")) or 0,
            "chg": _f(r.get("f3")) or 0,
            "amount": amt / 1e8,            # 当日成交额（亿元）
            "turnover_now": _f(r.get("f8")),  # 当日换手 %
            "main_net": (_f(r.get("f62")) or 0) / 1e8,   # 当日主力净额（亿元）
            "main_pct": _f(r.get("f184")),  # 当日主力净占比 %
        })
        if len(out) >= top_n:
            break

    if verbose:
        print(f"[ETF] 榜池就绪：{len(out)} 只（按当日成交额，剔除货币型）")
    return out


def hot_score(F: Dict, row: Dict, amt_pct: float) -> Tuple[int, Dict]:
    """热度分 = 成交额分位45 + 主力净流入20 + 量比15 + 涨幅10 + 量能趋势10。"""
    main_pct = row.get("main_pct")
    p_amt = clamp(amt_pct) * 45
    p_flow = clamp((main_pct or 0) / 5.0) * 20
    vr = F.get("vr")
    p_vr = clamp(((vr or 1.0) - 1.0) / 2.0) * 15
    p_chg = clamp(((row.get("chg") or 0) + 2) / 6.0) * 10
    vt = F.get("vol_trend5")
    p_vt = clamp(((vt or 0.9) - 0.9) / 0.8) * 10
    parts = {"amt": round(p_amt), "flow": round(p_flow), "vr": round(p_vr),
             "chg": round(p_chg), "trend": round(p_vt)}
    return int(round(p_amt + p_flow + p_vr + p_chg + p_vt)), parts


def analyze_etfs(client, etfs: List[Dict], verbose: bool = True
                 ) -> Tuple[List[Dict], Dict[str, Dict]]:
    """逐只跑四阶段打分卡，合并热度分。返回 (合并行列表, code→analysis)。"""
    n = len(etfs)
    # 榜内成交额百分位：列表已按成交额降序，第 i 名的分为 (n-i)/(n-1)
    for i, row in enumerate(etfs):
        row["amt_pct"] = (n - i) / (n - 1) if n > 1 else 1.0

    results: List[Dict] = []
    analyses: Dict[str, Dict] = {}
    for i, row in enumerate(etfs, 1):
        code, name = row["code"], row["name"]
        if verbose:
            print(f"  [ETF {i}/{n}] {code} {name} ...")
        a = None
        for attempt in range(2):
            try:
                a = AZ.analyze_stock(client, code, name, verbose=False,
                                     fetch_extra=False)
            except Exception:  # noqa: BLE001
                a = None
            if a:
                break
            time.sleep(2.0 * (attempt + 1))
        if not a:
            if verbose:
                print(f"  [跳过] {code} {name} 数据获取失败")
            continue
        analyses[code] = a

        res = a["result"]
        F = a["features"]
        act = action_scores(F, res)
        hot, parts = hot_score(F, row, row.get("amt_pct", 0))
        vr = F.get("vr")

        evidence = [{"label": e.label, "hit": bool(e.hit), "desc": e.desc}
                    for e in res.evidences[res.stage] if e.hit is not None]
        results.append({
            "code": code,
            "name": name,
            "price": F.get("price") or row["price"],
            "chg": row["chg"],
            "amount": round(row["amount"], 2),
            "turnover_now": row.get("turnover_now"),
            "main_net": round(row["main_net"], 2),
            "main_pct": row.get("main_pct"),
            "vr": round(vr, 2) if vr is not None else None,
            "hot": hot,
            "hot_parts": parts,
            "stage": res.stage,
            "stage_name": STAGE_META[res.stage]["name"],
            "score": round(res.score),
            "scores": {k: round(v) for k, v in res.scores.items()},
            "confidence": res.confidence,
            "conf_label": confidence_label(res.confidence),
            "opportunity": act["opportunity"],
            "risk": act["risk"],
            "action": act["action"],
            "tone": act["tone"],
            "reason": act["reason"],
            "evidence": evidence,
        })
        if verbose:
            print(f"  ✓ {name:<18}{code}  {STAGE_META[res.stage]['name']}"
                  f"({res.score:.0f}分/{confidence_label(res.confidence)})"
                  f"  热度{hot}  机会{act['opportunity']}/风险{act['risk']}")

    results.sort(key=lambda x: -x["hot"])
    return results, analyses


def run_pipeline(client, top_n: int = 30, verbose: bool = True
                 ) -> Tuple[List[Dict], Dict[str, Dict]]:
    """完整 ETF 流水线：榜池 → 逐只评分 → 热榜排序。"""
    etfs = hot_list(client, top_n=top_n, verbose=verbose)
    if not etfs:
        if verbose:
            print("[ETF] 榜池为空（接口限流或域名不可达），本次看板不含 ETF 部分")
        return [], {}
    return analyze_etfs(client, etfs, verbose=verbose)
