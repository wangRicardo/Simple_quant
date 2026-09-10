# -*- coding: utf-8 -*-
"""
特征工程 + 分析流水线。

职责：
  1. 拉取一只股票的全部原始数据（K线/资金流/快照/龙虎榜/融资/户数）
  2. 加工成 stage.detect_stage 所需的特征字典 F
  3. 调用四阶段模型，返回完整分析结果（含证据链、原文数据、图表数据）
  4. 支持「历史回放」：对最近 N 个交易日逐日重算，观察阶段轮转轨迹
"""
from __future__ import annotations

import itertools
import time as _time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .datasource import EMClient, parse_kline, parse_fflow
from . import indicators as I
from .stage import STAGE_META, detect_stage, build_conclusion, confidence_label


# ==============================================================
# 特征计算
# ==============================================================
def compute_features(kline: List[Dict], fflow: List[Dict], code: str = "",
                     lhb_net: Optional[float] = None,
                     margin_pctile: Optional[float] = None,
                     float_cap: float = 0.0) -> Dict:
    """把行情/资金流加工成特征值字典。缺失字段一律 None，由模型自行降权。"""
    if len(kline) < 30:
        return {}

    closes = [b["close"] for b in kline]
    highs = [b["high"] for b in kline]
    lows = [b["low"] for b in kline]
    vols = [b["volume"] for b in kline]
    amounts = [b["amount"] for b in kline]

    last = kline[-1]
    mas = I.moving_averages(closes, (5, 10, 20, 30, 60, 120))
    m = I.macd(closes)
    agg = I.fflow_aggregate(fflow, (1, 3, 5, 10, 20)) if fflow else {}

    # 筹码模型
    chip = I.ChipModel(kline, window=min(140, len(kline)))
    chip_shift = I.chip_centroid_shift(kline, lookback=20,
                                       window=min(140, len(kline)))

    # 形态统计
    up_shadow_days = sum(1 for b in kline[-10:] if I.upper_shadow(b) > 0.5)
    low_shadow_days = sum(1 for b in kline[-10:] if I.lower_shadow(b) > 0.5)
    dump_days = sum(1 for b in kline[-10:]
                    if b["chg"] < -2 and b["volume"] > sum(vols[-11:-1]) / 10 * 1.5)
    bo = I.breakout_strength(kline, 20)

    def dist(n: int) -> Optional[float]:
        v = mas.get(n)
        if v is None or v == 0:
            return None
        return (closes[-1] - v) / v * 100

    F: Dict = {
        # --- 基础 ---
        "code": code,
        "price": closes[-1],
        "last_chg": last["chg"],
        "turnover5": I.turnover_avg(kline, 5),
        "turnover10": I.turnover_avg(kline, 10),
        "amp10": I.amplitude_avg(kline, 10),

        # --- 量能 ---
        "vr": I.volume_ratio(vols, 5),
        "vol_trend5": I.volume_trend(vols, 5),
        "up_down_vol20": I.up_down_vol_ratio(kline, 20),
        "obv_slope20": I.obv_slope(closes, vols, 20),

        # --- 价格 ---
        "ma5": mas.get(5), "ma10": mas.get(10), "ma20": mas.get(20),
        "ma60": mas.get(60), "ma120": mas.get(120),
        "dist_ma10": dist(10), "dist_ma20": dist(20), "dist_ma60": dist(60),
        "bias20": I.bias_to_ma(closes, 20),
        "dd20": I.drawdown_from_high(closes, 20),
        "dd60": I.drawdown_from_high(closes, 60),
        "pos250": I.position_percentile(closes, 250),
        "ma_align": I.ma_bull_alignment(closes),
        "band20": I.consolidation_band(kline, 20),

        # --- 指标 ---
        "macd_dif": m["dif"], "macd_dea": m["dea"], "macd_hist": m["hist"],
        "macd_hist_prev": m["hist_prev"],
        "divergence": I.detect_divergence(closes, list(itertools.accumulate(vols)), 30),

        # --- 形态 ---
        "breakout": bo.get("breakout", False),
        "breakout_info": f"创20日新高，量能 {bo.get('volume_ratio') and round(bo['volume_ratio'], 2)}倍",
        "locus5": I.locus(last) and float(I.locus(last)),
        "up_shadow_days10": up_shadow_days,
        "low_shadow_days10": low_shadow_days,
        "dump_days10": dump_days,
        "limitup10": I.limit_up_count(kline, 10, code)[0],
        "consec_up": I.consecutive_up_days(kline),

        # --- 筹码 ---
        "chip_concentration": chip.concentration(),
        "profit_ratio": (chip.profit_ratio(closes[-1]) * 100
                         if chip.profit_ratio(closes[-1]) is not None else None),
        "peak_price": chip.peak_price(),
        "avg_cost": chip.avg_cost(),
        "bottom_locked": (chip.bottom_locked(closes[-1]) * 100
                          if chip.bottom_locked(closes[-1]) is not None else None),
        "overhead": (chip.overhead_pressure(closes[-1]) * 100
                     if chip.overhead_pressure(closes[-1]) is not None else None),
        "chip_shift20": chip_shift,

        # --- 外部数据 ---
        "lhb_net": lhb_net,
        "margin_pctile": margin_pctile,
        "float_cap": float_cap,
    }

    # locus 修正为 5 日均值
    loci = [I.locus(b) for b in kline[-5:]]
    F["locus5"] = float(sum(loci) / len(loci)) if loci else None

    # --- 资金流 ---
    if agg:
        for k in ("main", "huge", "big", "mid", "small"):
            F[k + "5"] = agg[k].get(5)
            F[k + "3"] = agg[k].get(3)
        F["main10"] = agg["main"].get(10)
        F["main20"] = agg["main"].get(20)
        F["main_pct5"] = I.fflow_pct_avg(fflow, "main_pct", 5)
        F["huge_dom3"] = I.huge_dominance(fflow, 3)

        # 资金「相对强度」：净额占同期成交额比例。
        # 绝对值会被市值规模掩盖（2000亿市值的票流出50亿 vs 50亿市值的票流出2亿，
        # 前者其实更温和），用占比才是可跨个股比较的资金压强指标。
        amt5 = sum(b["amount"] for b in kline[-5:]) / 1e8
        amt10 = sum(b["amount"] for b in kline[-10:]) / 1e8
        if amt5 > 0 and agg["main"].get(5) is not None:
            F["main5_amt_ratio"] = agg["main"][5] / amt5 * 100
        if amt10 > 0 and agg["main"].get(10) is not None:
            F["main10_amt_ratio"] = agg["main"][10] / amt10 * 100
    return F


# ==============================================================
# 单股分析
# ==============================================================
def fetch_margin_percentile(client: EMClient, code: str,
                            days: int = 180) -> Optional[float]:
    """融资余额在近 days 日区间中的百分位。

    融资余额代表杠杆资金参与度，处于历史高位说明筹码脆弱、容易踩踏。
    返回 None 表示该标的无两融数据或接口不可用。
    """
    try:
        rows = client.margin(code, days=days)
        if not rows or len(rows) < 20:
            return None
        # 字段名在不同版本接口中可能是 RZYE / RZJME / FIN_BALANCE，做容错
        vals = []
        for r in rows:
            v = r.get("RZYE") or r.get("FIN_BALANCE") or r.get("RZJME")
            if isinstance(v, (int, float)):
                vals.append(float(v))
        if len(vals) < 20:
            return None
        cur = vals[0]                       # 接口已按日期倒序
        rank = sum(1 for v in vals if v <= cur) / len(vals) * 100
        return round(rank, 1)
    except Exception:  # noqa: BLE001
        return None


def need_trim_today(kline: List[Dict]) -> bool:
    """判断最后一根 K 线是否为「未走完的当日」。

    盘中运行时，当日成交量只累计了半天，直接用于计算会出现系统性失真：
      - 量比被严重低估（看起来在缩量，实为时间不够）
      - 涨跌幅、换手率均为中间态
    因此 A 股标准做法：15:00 收盘前一律以「上一交易日」作为判定基准日。
    """
    if not kline:
        return False
    today = _time.strftime("%Y-%m-%d")
    if kline[-1]["date"] != today:
        return False
    now = datetime.now()
    return (now.hour < 15) or (now.hour == 15 and now.minute < 5)


def analyze_stock(client: EMClient, code: str, name: str = "",
                  kline_req: int = 320, verbose: bool = True,
                  strict_complete: bool = True,
                  fetch_extra: bool = True) -> Optional[Dict]:
    """分析单只标的：拉数据 → 算特征 → 判定阶段 → 组装结果。"""
    if verbose:
        print(f"  [数据] {code} {name or ''} 拉取行情/资金流/龙虎榜 ...")

    # 核心两只接口（K线/资金流）必须拿到，否则整只票无意义 —— 单独重试
    raw_k = raw_f = None
    for attempt in range(3):
        raw_k = client.kline(code, beg="20240101")
        if raw_k:
            break
        _time.sleep(1.5 * (attempt + 1))
    if raw_k and raw_k.get("data"):
        for attempt in range(3):
            raw_f = client.fflow(code)
            if raw_f:
                break
            _time.sleep(1.5 * (attempt + 1))

    if not raw_k or not raw_k.get("data"):
        if verbose:
            print(f"  [跳过] {code} K线获取失败")
        return None
    kline = parse_kline(raw_k)
    if len(kline) < 60:
        if verbose:
            print(f"  [跳过] {code} 历史数据不足 ({len(kline)} 根)")
        return None
    name = raw_k["data"].get("name") or name
    fflow = parse_fflow(raw_f) if raw_f else []

    # 实时快照
    snap_num = {}
    try:
        snap = client.snapshot(code)
        if snap and snap.get("data"):
            d = snap["data"]
            # 东财 f116/f117 单位为「元」，统一换算成「亿元」便于阈值比较
            def _yi(v):
                return None if not isinstance(v, (int, float)) else round(v / 1e8, 2)

            snap_num = {
                "vr_real": d.get("f50"),        # 实时量比
                "turnover": d.get("f168"),      # 换手率 %
                "pe": d.get("f162"),
                "pb": d.get("f167"),
                "float_cap": _yi(d.get("f117")),     # 流通市值(亿元)
                "total_cap": _yi(d.get("f116")),     # 总市值(亿元)
                "price": d.get("f43"),
                "chg": d.get("f170"),
            }
    except Exception:  # noqa: BLE001
        pass

    # 龙虎榜机构净额（单位转亿元）
    lhb_net = None
    try:
        info = client.lhb_institution(code)
        if info and info["rows"] > 0:
            lhb_net = info["net"] / 1e8
    except Exception:  # noqa: BLE001
        pass

    # 融资余额分位（辅助项，批量扫描时可跳过以节省请求配额）
    margin_pctile = None
    if fetch_extra:
        margin_pctile = fetch_margin_percentile(client, code)

    float_cap = float(snap_num.get("float_cap") or 0)

    # ---- 判定基准日处理 ----
    # 盘中最后一根 K 线不完整，会系统性扭曲量比/换手/涨跌幅，
    # 因此默认剔除，用上一完整交易日做判定（这是避免"未来函数"的关键一步）。
    trimmed = strict_complete and need_trim_today(kline)
    judge_kline = kline[:-1] if trimmed else kline
    judge_date = judge_kline[-1]["date"]
    if trimmed and fflow:
        judge_fflow = [r for r in fflow if r["date"] <= judge_date]
    else:
        judge_fflow = fflow

    if len(judge_kline) < 60:
        return None

    F = compute_features(judge_kline, judge_fflow, code, lhb_net,
                         margin_pctile, float_cap)
    if not F:
        return None

    # 记录实时行情（仅作展示，不参与阶段判定，避免半成品数据污染结论）
    live_discarded = None
    if trimmed:
        live = kline[-1]
        live_discarded = {
            "date": live["date"], "close": live["close"], "chg": live["chg"],
            "turnover": live["turnover"], "amount": round(live["amount"] / 1e8, 2),
        }

    res = detect_stage(F)
    conclusion = build_conclusion(res, F)

    # 图表数据：近 60 日量价
    chart = []
    for b in kline[-60:]:
        chart.append({
            "date": b["date"], "open": b["open"], "close": b["close"],
            "low": b["low"], "high": b["high"],
            "volume": round(b["volume"] / 1e4, 2),            # 万手
            "amount": round(b["amount"] / 1e8, 2),            # 亿元
            "chg": b["chg"], "turnover": b["turnover"],
        })

    # 资金流近 30 日
    flow_chart = [{"date": r["date"], "main": round(r["main"] / 1e8, 3),
                   "huge": round(r["huge"] / 1e8, 3),
                   "small": round(r["small"] / 1e8, 3),
                   "main_pct": r["main_pct"]} for r in fflow[-30:]]

    chip_raw_fold = I.ChipModel(judge_kline, window=min(140, len(judge_kline)))
    return {
        "code": code, "name": name,
        "features": F,
        "snapshot": snap_num,
        "result": res,
        "conclusion": conclusion,
        "kline": chart,
        "flow": flow_chart,
        "chip_curve": chip_raw_fold.curve(90),
        "chip_concentration": chip_raw_fold.concentration(),
        "avg_cost": chip_raw_fold.avg_cost(),
        "kline_raw": kline,
        "fflow_raw": fflow,
        "as_of": judge_date,
        "trimmed": trimmed,
        "live_discarded": live_discarded,
    }


# ==============================================================
# 历史回放：观察阶段轮转
# ==============================================================
def replay_history(analysis: Dict, days: int = 25) -> List[Dict]:
    """对最近 days 个交易日逐日重算所属阶段，用于观察 Stage → Stage 的演化。

    每段主体:
      按其本身的表述重写，保留全部信息（含具体数值/日期/来源），不要摘要、不要漏项。
    """
    kline = analysis.get("kline_raw") or []
    fflow = analysis.get("fflow_raw") or []
    code = analysis["code"]

    # 与主判定保持一致：排除未收盘的当日，否则回放末点会与主结论打架
    if need_trim_today(kline):
        kline = kline[:-1]
        if fflow:
            fflow = [r for r in fflow if r["date"] <= kline[-1]["date"]]

    lhb_net = analysis["features"].get("lhb_net")
    margin_pctile = analysis["features"].get("margin_pctile")
    float_cap = analysis["features"].get("float_cap") or 0

    if len(kline) < 80:
        return []

    out: List[Dict] = []
    start = max(80, len(kline) - days)
    # 为速度考虑，步长取 1 但限制总数
    for end in range(start, len(kline) + 1):
        sub_k = kline[:end]
        sub_f = [r for r in fflow if r["date"] <= sub_k[-1]["date"]]
        try:
            F = compute_features(sub_k, sub_f, code, lhb_net, margin_pctile, float_cap)
            if not F:
                continue
            res = detect_stage(F)
            out.append({
                "date": sub_k[-1]["date"],
                "close": sub_k[-1]["close"],
                "chg": sub_k[-1]["chg"],
                "stage": res.stage,
                "stage_name": STAGE_META[res.stage]["name"],
                "score": res.score,
                "scores": res.scores,
                "confidence": res.confidence,
                "vr": F.get("vr"),
                "turnover5": F.get("turnover5"),
                "main5": F.get("main5"),
                "profit_ratio": F.get("profit_ratio"),
                "bottom_locked": F.get("bottom_locked"),
                "pos250": F.get("pos250"),
            })
        except Exception:  # noqa: BLE001
            continue
    return out
