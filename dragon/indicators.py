# -*- coding: utf-8 -*-
"""
指标计算层：把原始行情/资金流数据加工成"机构行为可识别"的特征向量。

指标分五大族：
  A. 量能族    —— 量比、量能比、缩量/放量、阴阳量对比
  B. 价格族    —— 均线、乖离、位置分位、回撤、收盘位置(locus)
  C. 资金族    —— 主力/超大单多周期净额与占比、OBV
  D. 筹码族    —— 三角形分布筹码模型：平均成本、获利盘、峰值、集中度、低位锁定
  E. 形态族    —— 涨停、突破、长上影、连板、背离

所有函数均为纯函数，输入 list[dict]，输出标量或 dict，方便单测与复用。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ==============================================================
# 基础数学
# ==============================================================
def sma(vals: Sequence[float], n: int) -> Optional[float]:
    if len(vals) < n or n <= 0:
        return None
    return float(np.mean(vals[-n:]))


def sma_series(vals: Sequence[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(vals)):
        if i + 1 < n:
            out.append(None)
        else:
            out.append(float(np.mean(vals[i + 1 - n:i + 1])))
    return out


def ema(vals: Sequence[float], n: int) -> Optional[float]:
    if len(vals) < n:
        return None
    a = 2.0 / (n + 1)
    e = float(vals[0])
    for v in vals[1:]:
        e = a * float(v) + (1 - a) * e
    return e


def _ema_list(vals: Sequence[float], n: int) -> List[float]:
    if not vals:
        return []
    a = 2.0 / (n + 1)
    out = [float(vals[0])]
    for v in vals[1:]:
        out.append(a * float(v) + (1 - a) * out[-1])
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> Dict[str, Optional[float]]:
    """返回 DIF / DEA / HIST(红柱) 以及前一日值，用于判断金叉死叉。"""
    if len(closes) < slow + signal:
        return {"dif": None, "dea": None, "hist": None,
                "dif_prev": None, "dea_prev": None, "hist_prev": None}
    ef = _ema_list(closes, fast)
    es = _ema_list(closes, slow)
    dif = [ef[i] - es[i] for i in range(len(closes))]
    dea = _ema_list(dif, signal)
    hist = [2 * (dif[i] - dea[i]) for i in range(len(dif))]
    return {
        "dif": dif[-1], "dea": dea[-1], "hist": hist[-1],
        "dif_prev": dif[-2], "dea_prev": dea[-2], "hist_prev": hist[-2],
        "dif_5ago": dif[-6] if len(dif) > 6 else None,
        "hist_5ago": hist[-6] if len(hist) > 6 else None,
    }


# ==============================================================
# A. 量能族
# ==============================================================
def volume_ratio(vols: Sequence[float], n: int = 5) -> Optional[float]:
    """日线量比 = 当日量 / 前 n 日平均量。盘中量比语义近似。"""
    if len(vols) < n + 1:
        return None
    base = float(np.mean(vols[-1 - n:-1]))
    if base <= 0:
        return None
    return float(vols[-1]) / base


def vol_ratio_to_mean(vols: Sequence[float], cur_idx: int = -1,
                      n: int = 10) -> Optional[float]:
    """指定位置的量 / 前 n 日均量。"""
    i = cur_idx if cur_idx >= 0 else len(vols) + cur_idx
    if i < n:
        return None
    base = float(np.mean(vols[i - n:i]))
    return float(vols[i]) / base if base > 0 else None


def volume_trend(vols: Sequence[float], n: int = 5) -> Optional[float]:
    """近 n 日平均量 / 前 n 日平均量，判断整体量能是在放大还是萎缩。"""
    if len(vols) < 2 * n:
        return None
    recent = float(np.mean(vols[-n:]))
    prior = float(np.mean(vols[-2 * n:-n]))
    return recent / prior if prior > 0 else None


def up_down_vol_ratio(kline: List[Dict], n: int = 20) -> Optional[float]:
    """近 n 日：上涨日均量 / 下跌日均量。>1.2 为典型吸筹特征（阳放阴缩）。"""
    seg = kline[-n:]
    ups = [b["volume"] for b in seg if b["chg"] > 0]
    downs = [b["volume"] for b in seg if b["chg"] < 0]
    if not ups or not downs:
        return None
    return float(np.mean(ups)) / float(np.mean(downs))


def obv(closes: Sequence[float], vols: Sequence[float]) -> List[float]:
    """OBV 能量潮。"""
    out = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out.append(out[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            out.append(out[-1] - vols[i])
        else:
            out.append(out[-1])
    return out


def obv_slope(closes: Sequence[float], vols: Sequence[float],
              n: int = 20) -> Optional[float]:
    """OBV 归一化斜率（相对近 n 日总成交量），>0.05 视为资金持续净流入。"""
    if len(closes) < n + 1:
        return None
    o = obv(closes, vols)
    tot = float(np.sum(vols[-n:]))
    if tot <= 0:
        return None
    return float((o[-1] - o[-1 - n]) / tot)


# ==============================================================
# B. 价格族
# ==============================================================
def moving_averages(closes: Sequence[float],
                    windows: Sequence[int] = (5, 10, 20, 30, 60, 120)) -> Dict[int, Optional[float]]:
    return {w: sma(closes, w) for w in windows}


def bias_to_ma(closes: Sequence[float], n: int = 20) -> Optional[float]:
    """乖离率 % = (现价 - MA_n) / MA_n * 100"""
    m = sma(closes, n)
    if m is None or m == 0:
        return None
    return (closes[-1] - m) / m * 100


def drawdown_from_high(closes: Sequence[float], n: int = 60) -> Optional[float]:
    """距近 n 日最高价的回撤 %（负值表示处于回撤中）"""
    if len(closes) < 2:
        return None
    seg = closes[-n:]
    hi = max(seg)
    return (closes[-1] - hi) / hi * 100 if hi > 0 else None


def position_percentile(closes: Sequence[float], n: int = 250) -> Optional[float]:
    """当前价在近 n 日最高最低区间中的分位（0=最低 100=最高）"""
    if len(closes) < 2:
        return None
    seg = closes[-n:] if len(closes) >= n else closes
    lo, hi = min(seg), max(seg)
    if hi <= lo:
        return 50.0
    return (closes[-1] - lo) / (hi - lo) * 100


def new_high_days(closes: Sequence[float], n: int = 20) -> bool:
    """收盘价是否创近 n 日新高（不含当日）"""
    if len(closes) < n + 1:
        return False
    return closes[-1] >= max(closes[-1 - n:-1])


def locus(bar: Dict) -> float:
    """收盘位置 = (收-低)/(高-低)。>0.7 强势收于上沿，<0.3 弱势收于下沿。"""
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return 0.5
    return (bar["close"] - bar["low"]) / rng


def upper_shadow(bar: Dict) -> float:
    """上影线占全幅比例。>0.5 为明显长上影（高位警惕）。"""
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return 0.0
    shadow = bar["high"] - max(bar["close"], bar["open"])
    return shadow / rng


def lower_shadow(bar: Dict) -> float:
    """下影线占全幅比例。>0.5 说明盘中杀跌被接回（洗盘/承接信号）。"""
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return 0.0
    shadow = min(bar["close"], bar["open"]) - bar["low"]
    return shadow / rng


def ma_bull_alignment(closes: Sequence[float]) -> Optional[str]:
    """均线排列状态：多头 / 空头 / 纠缠 / 未知"""
    mas = moving_averages(closes, (5, 10, 20, 60))
    if any(mas[w] is None for w in (5, 10, 20, 60)):
        return None
    m5, m10, m20, m60 = mas[5], mas[10], mas[20], mas[60]
    if m5 > m10 > m20 > m60:
        return "多头排列"
    if m5 < m10 < m20 < m60:
        return "空头排列"
    return "均线纠缠"


def consecutive_up_days(kline: List[Dict]) -> int:
    """截至当前的连涨天数。"""
    cnt = 0
    for b in reversed(kline):
        if b["chg"] > 0:
            cnt += 1
        else:
            break
    return cnt


def limit_up_count(kline: List[Dict], window: int = 10,
                   code: str = "") -> Tuple[int, int]:
    """近 window 日内的涨停次数与连板高度（最后一个连板段）。"""
    lim = limit_threshold(code)
    cnt = sum(1 for b in kline[-window:] if b["chg"] >= lim)
    height = 0
    for b in reversed(kline):
        if b["chg"] >= lim:
            height += 1
        else:
            break
    return cnt, height


def limit_threshold(code: str) -> float:
    """按板块给出涨停阈值 %。"""
    c = code.strip()
    if c.startswith(("30", "68")):
        return 19.5
    if c.startswith(("83", "87", "82", "43", "92")):
        return 29.5
    return 9.5


# ==============================================================
# C. 资金族
# ==============================================================
def fflow_aggregate(fflow: List[Dict], windows: Sequence[int] = (1, 3, 5, 10, 20)
                    ) -> Dict[str, Dict[int, Optional[float]]]:
    """把资金流明细聚合成多周期净额（单位：亿元）。"""
    res: Dict[str, Dict[int, Optional[float]]] = {
        "main": {}, "huge": {}, "big": {}, "mid": {}, "small": {}
    }
    for w in windows:
        for k in res:
            if len(fflow) < w:
                res[k][w] = None
                continue
            res[k][w] = sum(r[k] for r in fflow[-w:]) / 1e8
    return res


def fflow_pct_avg(fflow: List[Dict], key: str = "main_pct",
                  n: int = 5) -> Optional[float]:
    """近 n 日某类资金净占比均值（%）。"""
    if len(fflow) < n:
        return None
    return float(np.mean([r[key] for r in fflow[-n:]]))


def huge_dominance(fflow: List[Dict], n: int = 3) -> Optional[float]:
    """超大单净额占主力净额比例。>0.6 说明是"真机构/大资金"在买而非游资拆单。"""
    if len(fflow) < n:
        return None
    main = sum(r["main"] for r in fflow[-n:])
    huge = sum(r["huge"] for r in fflow[-n:])
    if abs(main) < 1e6:
        return None
    return huge / main


# ==============================================================
# D. 筹码族 —— 三角形分布模型
# ==============================================================
class ChipModel:
    """筹码分布模型（通达信式三角形衰减近似）。

    原理：
      每日成交在区间 [low, high] 内以均价 avg 为顶点做三角形分配，
      分配权重 = 当日换手率；历史筹码按 (1 - 换手率*decay) 衰减。
      这样得到的分布刻画了"不同价位上的持仓成本堆积"。

    关键衍生指标：
      avg_cost     平均成本
      profit_ratio 获利盘比例（成本低于现价的筹码占比）
      peak_price   筹码峰（最大堆积价位）
      concentration 90% 集中度：越小组筹码越集中
      bottom_locked 低位锁定筹码占比：判断底部筹码是否还在
    """

    def __init__(self, kline: List[Dict], window: int = 120,
                 bins: int = 200, decay: float = 1.0):
        self.window = window
        self.bins = bins
        self.decay = decay
        self.prices: np.ndarray = np.array([])
        self.chip: np.ndarray = np.array([])
        self._build(kline[-window:] if len(kline) > window else kline)

    def _build(self, seg: List[Dict]) -> None:
        if len(seg) < 2:
            return
        lo_min = min(b["low"] for b in seg)
        hi_max = max(b["high"] for b in seg)
        if hi_max <= lo_min:
            return
        prices = np.linspace(lo_min, hi_max, self.bins)
        step = prices[1] - prices[0]
        chip = np.zeros(self.bins, dtype=float)

        for b in seg:
            lo, hi = b["low"], b["high"]
            vol = b["volume"]
            if vol <= 0 or hi <= lo:
                continue
            avg = b["amount"] / (vol * 100.0)  # 元/股
            avg = min(max(avg, lo), hi)
            w = b["turnover"] / 100.0
            chip *= max(0.0, 1.0 - w * self.decay)

            # 三角形分量：低位段 [lo, avg]，高位段 (avg, hi]
            idx_low = np.where((prices >= lo) & (prices <= avg))[0]
            idx_high = np.where((prices > avg) & (prices <= hi))[0]
            if len(idx_low):
                chip[idx_low] += (prices[idx_low] - lo + step) / (avg - lo + step)
            if len(idx_high):
                chip[idx_high] += (hi - prices[idx_high] + step) / (hi - avg + step)

            block = np.zeros_like(chip)
            if len(idx_low):
                block[idx_low] += (prices[idx_low] - lo + step) / (avg - lo + step)
            if len(idx_high):
                block[idx_high] += (hi - prices[idx_high] + step) / (hi - avg + step)
            s = block.sum()
            if s > 0:
                chip += block / s * w

        tot = chip.sum()
        if tot > 0:
            chip /= tot
        self.prices, self.chip = prices, chip

    # ---------- 衍生指标 ----------
    @property
    def valid(self) -> bool:
        return self.chip.size > 0 and self.chip.sum() > 0

    def avg_cost(self) -> Optional[float]:
        if not self.valid:
            return None
        return float(np.average(self.prices, weights=self.chip))

    def profit_ratio(self, price: float) -> Optional[float]:
        """获利盘比例（成本 <= 现价的筹码占比）"""
        if not self.valid:
            return None
        return float(self.chip[self.prices <= price].sum())

    def peak_price(self) -> Optional[float]:
        if not self.valid:
            return None
        return float(self.prices[int(np.argmax(self.chip))])

    def concentration(self, ratio: float = 0.9) -> Optional[float]:
        """集中度：(价格区间宽度 / 均价)。

        取累计占比达 ratio 的上下分位，越小说明筹码越集中于窄区间。
        """
        if not self.valid:
            return None
        cum = np.cumsum(self.chip)
        lo_i = int(np.searchsorted(cum, (1 - ratio) / 2))
        hi_i = int(np.searchsorted(cum, 1 - (1 - ratio) / 2))
        hi_i = min(hi_i, self.bins - 1)
        width = self.prices[hi_i] - self.prices[lo_i]
        mid = self.prices[(lo_i + hi_i) // 2]
        return float(width / mid) if mid > 0 else None

    def bottom_locked(self, price: float) -> Optional[float]:
        """低位锁定筹码占比：成本显著低于现价（<= price*0.85）的筹码。

        这是判断"老庄/机构底仓是否还在"的关键。撤离阶段该值会持续下降。
        """
        if not self.valid:
            return None
        return float(self.chip[self.prices <= price * 0.85].sum())

    def near_zone_ratio(self, price: float, band: float = 0.10) -> Optional[float]:
        """现价上下 band 范围内的筹码占比 —— 衡量当前价位的套牢/获利压力。"""
        if not self.valid:
            return None
        m = (self.prices >= price * (1 - band)) & (self.prices <= price * (1 + band))
        return float(self.chip[m].sum())

    def overhead_pressure(self, price: float) -> Optional[float]:
        """上方套牢盘比例（成本高于现价 10% 以内的部分）—— 压制突破的抛压。"""
        if not self.valid:
            return None
        m = (self.prices > price) & (self.prices <= price * 1.20)
        return float(self.chip[m].sum())

    def curve(self, max_points: int = 120) -> List[List[float]]:
        """返回 [价格, 占比] 曲线，供前端渲染。"""
        if not self.valid:
            return []
        idx = np.linspace(0, self.bins - 1, min(max_points, self.bins)).astype(int)
        return [[float(self.prices[i]), float(self.chip[i])] for i in idx]


def chip_centroid_shift(kline: List[Dict], lookback: int = 20,
                        window: int = 120) -> Optional[float]:
    """筹码重心迁移率：当前平均成本相对 lookback 日前的变化 %。

    > 0 表示筹码整体上移（可能是上涨带动，也可能是高位派发）；
    < 0 表示筹码整体下移。需要结合价格涨幅一起解读：
      若 重心上移 但 股价涨幅远大于重心上移 => 低位筹码未跟上，警惕派发。
    """
    if len(kline) < lookback + 30:
        return None
    cur = ChipModel(kline, window=window)
    prev = ChipModel(kline[:-lookback], window=window)
    if not cur.valid or not prev.valid:
        return None
    c1, c0 = cur.avg_cost(), prev.avg_cost()
    if c0 is None or c1 is None or c0 <= 0:
        return None
    return (c1 - c0) / c0 * 100


# ==============================================================
# E. 形态族
# ==============================================================
def detect_divergence(closes: Sequence[float], indicator: Sequence[float],
                      n: int = 30) -> Optional[str]:
    """顶背离/底背离检测：价格创新高而指标不创新高（反之亦然）。"""
    if len(closes) < n or len(indicator) < n:
        return None
    c_seg = list(closes[-n:])
    i_seg = list(indicator[-n:])
    ci = int(np.argmax(c_seg))
    if c_seg[-1] >= max(c_seg[:-1]) * 0.995:  # 价格接近/创新高
        if i_seg[-1] < i_seg[ci] * 0.95:
            return "顶背离"
    if c_seg[-1] <= min(c_seg[:-1]) * 1.005:  # 价格接近/创新低
        ci = int(np.argmin(c_seg))
        if i_seg[-1] > i_seg[ci] * 1.05:
            return "底背离"
    return None


def amplitude_avg(kline: List[Dict], n: int = 10) -> Optional[float]:
    if len(kline) < n:
        return None
    return float(np.mean([b["amplitude"] for b in kline[-n:]]))


def turnover_avg(kline: List[Dict], n: int = 5) -> Optional[float]:
    if len(kline) < n:
        return None
    return float(np.mean([b["turnover"] for b in kline[-n:]]))


def consolidation_band(kline: List[Dict], n: int = 20) -> Optional[float]:
    """近 n 日振幅带 = (最高-最低)/最低*100，衡量横盘整理的宽度。"""
    if len(kline) < n:
        return None
    seg = kline[-n:]
    hi = max(b["high"] for b in seg)
    lo = min(b["low"] for b in seg)
    return (hi - lo) / lo * 100 if lo > 0 else None


def breakout_strength(kline: List[Dict], n: int = 20) -> Dict:
    """突破强度检测：是否放量突破近 n 日平台并站稳。"""
    if len(kline) < n + 1:
        return {"breakout": False}
    closes = [b["close"] for b in kline]
    vols = [b["volume"] for b in kline]
    prior_hi = max(closes[-1 - n:-1])
    last = kline[-1]
    vr = vol_ratio_to_mean(vols, -1, min(5, n))
    return {
        "breakout": last["close"] > prior_hi,
        "prior_high": prior_hi,
        "gain_over_high": (last["close"] - prior_hi) / prior_hi * 100,
        "volume_ratio": vr,
        "close_above": last["close"] > prior_hi * 1.001,
    }
