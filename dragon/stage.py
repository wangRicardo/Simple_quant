# -*- coding: utf-8 -*-
"""
四阶段识别引擎（龙头战法核心）。

把"机构行为"这一不可见变量，映射为四个可判别的 latent state：
    ACCUMULATION 建仓期 → WASH 洗盘期 → LAUNCH 启动期 → DISTRIBUTION 撤离期

识别方式不是单一阈值，而是 **加权证据打分卡**：
    1. 每个阶段定义一组「证据规则」，每条规则是一个 (测试函数, 权重, 说明)
    2. 每条规则的产出是 True / False / None(数据不足自动剔除，不参与分母)
    3. 阶段得分 = Σ(命中权重) / Σ(适用权重) × 100
    4. 每个阶段另设「门槛条件 gate」，不满足则分数打折（避免误判）
    5. 取四阶段最高分作为判定结果，置信度 = 最高分 - 次高分

这样做的价值：
    - 可解释：每个结论都能回溯到具体指标
    - 可调参：阈值集中管理，可按股性/市值调整
    - 抗缺失：某项数据取不到时自动降权而非崩溃
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

# 阶段元数据
STAGE_META = {
    "ACCUMULATION": {
        "name": "建仓期",
        "color": "#185FA5",
        "icon": "◤",
        "core": "要买，但怕抬价",
        "action": "跟踪观察，分批低吸，等量能确认",
        "desc": "机构悄然吸筹，股价横盘或缓慢抬升，量能温和放大，OBV 领先价格走强。此阶段最重要的特征是「量在价先」——成交和筹码在动，但价格还没动。",
    },
    "WASH": {
        "name": "洗盘期",
        "color": "#e65100",
        "icon": "◢",
        "core": "要吓人，但不能真卖",
        "action": "拿住不动，破关键位止损，洗完加仓",
        "desc": "通过打压清洗浮筹。核心特征是「缩量下跌」——没有承接的资金必然是真出货，有底仓的资金才会敢于缩量打压。底部筹码峰锁定不动是唯一铁证。",
    },
    "LAUNCH": {
        "name": "启动期",
        "color": "#c62828",
        "icon": "◤",
        "core": "想快拉，但需要人跟",
        "action": "主升段持有，沿 MA10 持股，破 MA20 离场",
        "desc": "放量突破关键平台，资金跑步进场，均线转多头。此时赚钱效应最强，但也最怕「假突破」——必须同时满足放量、站稳、资金三者共振。",
    },
    "DISTRIBUTION": {
        "name": "撤离期",
        "color": "#5d4037",
        "icon": "◢",
        "core": "要卖，但怕崩",
        "action": "减仓离场，不参与高位缩量反抽",
        "desc": "高位派发。核心特征是「放量滞涨 + 底部筹码上移」。此时任何利好消息都可能是出货的掩护，追高赔率最差。",
    },
}


@dataclass
class Evidence:
    key: str
    label: str
    hit: Optional[bool]      # True 命中 / False 未命中 / None 数据不足
    desc: str                # 实际观测值描述
    weight: float
    expect: str = ""         # 期望值说明

    def to_dict(self) -> Dict:
        return {
            "key": self.key, "label": self.label,
            "hit": None if self.hit is None else bool(self.hit),
            "desc": self.desc, "weight": self.weight, "expect": self.expect,
        }


@dataclass
class Rule:
    key: str
    label: str
    test: Callable[[Dict], tuple]     # F -> (hit: bool|None, desc: str)
    weight: float = 1.0
    expect: str = ""


@dataclass
class StageResult:
    stage: str
    scores: Dict[str, float] = field(default_factory=dict)
    evidences: Dict[str, List[Evidence]] = field(default_factory=dict)
    gates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 0.0
    coverage: Dict[str, int] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return STAGE_META[self.stage]["name"]

    @property
    def score(self) -> float:
        return self.scores.get(self.stage, 0.0)

    @property
    def top_evidences(self) -> List[Evidence]:
        evs = [e for e in self.evidences.get(self.stage, []) if e.hit is True]
        return sorted(evs, key=lambda x: -x.weight)

    @property
    def failed_evidences(self) -> List[Evidence]:
        evs = [e for e in self.evidences.get(self.stage, []) if e.hit is False]
        return sorted(evs, key=lambda x: -x.weight)


# ==============================================================
# 工具：安全取值
# ==============================================================
def _ok(v) -> bool:
    return isinstance(v, bool)


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def cmpf(v, op: str, thr) -> Optional[bool]:
    """安全比较，任一为空返回 None（表示数据不足 → 不适用，不计入分母）。"""
    x = _num(v)
    t = _num(thr)
    if x is None or t is None:
        return None
    if op == ">":
        return x > t
    if op == ">=":
        return x >= thr
    if op == "<":
        return x < t
    if op == "<=":
        return x <= t
    return None


def fm(v, unit: str = "", nd: int = 2) -> str:
    if v is None:
        return "无数据"
    if isinstance(v, float):
        return f"{v:.{nd}f}{unit}"
    return f"{v}{unit}"


def _float_cap_billion(F: Dict) -> float:
    """流通市值（亿元）。取不到时返回一个足够大的值，避免因缺省而误判出逃。"""
    v = _num(F.get("float_cap"))
    if v is None or v <= 0:
        return 1e9
    return v


# ==============================================================
# 规则集合 —— 阈值集中在此，便于调参
# ==============================================================
RULES: Dict[str, List[Rule]] = {}

# ---------------- 建仓期 ----------------
RULES["ACCUMULATION"] = [
    Rule("vol_ratio", "温和放量",
         lambda F: (cmpf(F.get("vr"), ">=", 1.15) and cmpf(F.get("vr"), "<=", 2.5)
                    if _num(F.get("vr")) is not None else None,
                    f"量比 {fm(F.get('vr'))}"),
         weight=1.5, expect="1.2 ~ 2.5"),
    Rule("turnover_mild", "换手温和",
         lambda F: (cmpf(F.get("turnover5"), ">=", 1.2) and cmpf(F.get("turnover5"), "<=", 6.0)
                    if _num(F.get("turnover5")) is not None else None,
                    f"5日换手 {fm(F.get('turnover5'), '%')}"),
         weight=1.2, expect="1.2% ~ 6%"),
    Rule("obv_up", "OBV 抬升",
         lambda F: (cmpf(F.get("obv_slope20"), ">", 0.05),
                    f"OBV 20日斜率 {fm(F.get('obv_slope20'))}"),
         weight=2.0, expect="> 0.05（资金净蓄积）"),
    Rule("up_down_vol", "阳放阴缩",
         lambda F: (cmpf(F.get("up_down_vol20"), ">", 1.2),
                    f"涨跌量比 {fm(F.get('up_down_vol20'))}"),
         weight=1.5, expect="> 1.2"),
    Rule("main_inflow", "主力温和净流入",
         lambda F: ((cmpf(F.get("main5"), ">", 0) and cmpf(F.get("main_pct5"), ">=", 1.5))
                    if _num(F.get("main5")) is not None else None,
                    f"5日主力 {fm(F.get('main5'), '亿')}，占比均值 {fm(F.get('main_pct5'), '%')}"),
         weight=2.0, expect="净额>0 且 占比≥1.5%"),
    Rule("low_position", "位置处于中低位",
         lambda F: ((cmpf(F.get("dd60"), "<", -12) if _num(F.get("dd60")) is not None else None)
                    or (cmpf(F.get("pos250"), "<", 55) if _num(F.get("pos250")) is not None else None),
                    f"距60日高点 {fm(F.get('dd60'), '%')}，年内分位 {fm(F.get('pos250'))}"),
         weight=1.5, expect="回撤>12% 或 年内分位<55"),
    Rule("chip_dense", "筹码低位密集",
         lambda F: (
             ((cmpf(F.get("chip_concentration"), "<", 0.38) is True)
              and (cmpf(F.get("profit_ratio"), "<", 60) is True))
             if (F.get("chip_concentration") is not None
                 and F.get("profit_ratio") is not None)
             else None,
             f"集中度 {fm(F.get('chip_concentration'))}，获利盘 {fm(F.get('profit_ratio'), '%', 1)}",
         ),
         weight=1.5, expect="集中度<0.38 且 获利盘<60%"),
    Rule("narrow_band", "横盘整理",
         lambda F: (cmpf(F.get("band20"), "<", 28),
                    f"20日振幅带 {fm(F.get('band20'), '%')}"),
         weight=1.0, expect="< 28%"),
    Rule("inst_buy", "机构席位净买入",
         lambda F: ((True, f"近期龙虎榜机构净买 {fm(F.get('lhb_net'), '亿')}")
                    if _num(F.get("lhb_net")) is not None and F["lhb_net"] > 0
                    else ((False, f"近期龙虎榜机构净卖 {fm(F.get('lhb_net'), '亿')}")
                          if _num(F.get("lhb_net")) is not None else (None, "无龙虎榜数据"))),
         weight=1.5, expect="机构净额 > 0"),
    Rule("huge_support", "超大单参与",
         lambda F: (cmpf(F.get("huge_dom3"), ">", 0.3),
                    f"超大单占主力 {fm(F.get('huge_dom3'), '', 2)}"),
         weight=1.0, expect="> 0.3"),
    Rule("vol_trend_up", "量能趋势抬升",
         lambda F: (cmpf(F.get("vol_trend5"), ">", 1.1),
                    f"近5日/前5日量能 {fm(F.get('vol_trend5'))}"),
         weight=1.0, expect="> 1.1"),
    Rule("capital_momentum", "资金流出动能收敛",
         lambda F: (cmpf(F.get("main5"), ">", F.get("main10"))
                    if (_num(F.get("main5")) is not None
                        and _num(F.get("main10")) is not None)
                    else None,
                    f"5日主力 {fm(F.get('main5'), '亿')} vs 10日 {fm(F.get('main10'), '亿')}"),
         weight=1.5, expect="近5日资金强于近10日"),
    Rule("capital_contra", "资金逆势回流",
         lambda F: (cmpf(F.get("main5_amt_ratio"), ">", 3),
                    f"5日主力占成交额 {fm(F.get('main5_amt_ratio'), '%')}"),
         weight=2.0, expect="占成交额>3%（价滞而钱进）"),
    Rule("deep_oversold", "深度超跌（有修复空间）",
         lambda F: (cmpf(F.get("dd60"), "<", -30),
                    f"距60日高点 {fm(F.get('dd60'), '%')}"),
         weight=1.2, expect="< -30%"),
    Rule("not_yet_launch", "尚未进入拉升",
         lambda F: (cmpf(F.get("bias20"), "<", 12),
                    f"MA20 乖离 {fm(F.get('bias20'), '%')}"),
         weight=0.8, expect="乖离 < 12%（未过热）"),
]

# ---------------- 洗盘期 ----------------
RULES["WASH"] = [
    Rule("shrink_vol", "缩量下跌",
         lambda F: (cmpf(F.get("vr"), "<", 0.95),
                    f"当日量比 {fm(F.get('vr'))}"),
         weight=2.0, expect="< 0.95"),
    Rule("vol_contract", "量能持续萎缩",
         lambda F: (cmpf(F.get("vol_trend5"), "<", 0.9),
                    f"近5/前5量能 {fm(F.get('vol_trend5'))}"),
         weight=1.5, expect="< 0.9"),
    Rule("mild_drawdown", "跌幅可控",
         lambda F: ((cmpf(F.get("dd20"), ">=", -26) if _num(F.get("dd20")) is not None else None),
                    f"20日回撤 {fm(F.get('dd20'), '%')}"),
         weight=1.2, expect="≥ -26%（过深则趋势破坏）"),
    Rule("hold_key_level", "未破关键位",
         lambda F: (
             ((cmpf(F.get("dist_ma60"), ">", -6) is True)
              or (cmpf(F.get("dist_ma20"), ">", -12) is True))
             if (F.get("dist_ma60") is not None or F.get("dist_ma20") is not None)
             else None,
             f"距MA60 {fm(F.get('dist_ma60'), '%')}，距MA20 {fm(F.get('dist_ma20'), '%')}",
         ),
         weight=2.0, expect="MA60 上方或微幅跌破"),
    Rule("bottom_chip_locked", "底部筹码锁定",
         lambda F: (cmpf(F.get("bottom_locked"), ">", 18),
                    f"低位锁定筹码 {fm(F.get('bottom_locked'), '%', 1)}"),
         weight=2.0, expect="> 18%"),
    Rule("main_not_flee", "主力未大规模出逃",
         lambda F: (
             ((cmpf(F.get("main5_amt_ratio"), ">=", -5) is True)
              and (cmpf(F.get("main10_amt_ratio"), ">=", -3.5) is True))
             if F.get("main5_amt_ratio") is not None
             else None,
             f"5日主力占成交额 {fm(F.get('main5_amt_ratio'), '%')}，"
             f"10日 {fm(F.get('main10_amt_ratio'), '%')}",
         ),
         weight=1.8, expect="流出占成交额 <5%/3.5%"),
    Rule("turnover_cool", "换手降温",
         lambda F: (cmpf(F.get("turnover5"), "<", 9),
                    f"5日换手 {fm(F.get('turnover5'), '%')}"),
         weight=1.0, expect="< 9%"),
    Rule("lower_shadow", "长下影承接",
         lambda F: (cmpf(F.get("low_shadow_days10"), ">=", 2),
                    f"近10日长下影 {fm(F.get('low_shadow_days10'), '天', 0)}"),
         weight=1.2, expect="≥ 2 天"),
    Rule("close_locus", "收盘重心不弱",
         lambda F: (cmpf(F.get("locus5"), ">", 0.42),
                    f"5日收盘位置均值 {fm(F.get('locus5'))}"),
         weight=1.0, expect="> 0.42"),
    Rule("no_dump_day", "无放量出货日",
         lambda F: (cmpf(F.get("dump_days10"), "<=", 1),
                    f"近10日放量下跌天数 {fm(F.get('dump_days10'), '', 0)}"),
         weight=1.2, expect="≤ 1 天"),
    Rule("consolidating", "整理期未拉升",
         lambda F: (cmpf(F.get("bias20"), "<", 8),
                    f"MA20 乖离 {fm(F.get('bias20'), '%')}"),
         weight=0.8, expect="乖离 < 8%"),
]

# ---------------- 启动期 ----------------
RULES["LAUNCH"] = [
    Rule("vol_expand", "放量",
         lambda F: (cmpf(F.get("vr"), ">", 1.5),
                    f"当日量比 {fm(F.get('vr'))}"),
         weight=2.0, expect="> 1.5"),
    Rule("breakout", "突破平台",
         lambda F: (_ok(F.get("breakout")) and F["breakout"],
                    f"突破:{F.get('breakout_info', '-')}"),
         weight=2.0, expect="收盘创20日新高"),
    Rule("above_ma20", "站上 MA20",
         lambda F: (cmpf(F.get("dist_ma20"), ">", 0),
                    f"距MA20 {fm(F.get('dist_ma20'), '%')}"),
         weight=1.5, expect="> 0"),
    Rule("bull_align", "均线多头排列",
         lambda F: (F.get("ma_align") == "多头排列" if F.get("ma_align") else None,
                    f"{F.get('ma_align', '未知')}"),
         weight=1.5, expect="MA5>MA10>MA20>MA60"),
    Rule("macd_golden", "MACD 多头且红柱放大",
         lambda F: (
             ((cmpf(F.get("macd_dif"), ">", F.get("macd_dea")) is True)
              and (cmpf(F.get("macd_hist"), ">", 0) is True)
              and (cmpf(F.get("macd_hist"), ">=", F.get("macd_hist_prev")) is True))
             if (_num(F.get("macd_dif")) is not None
                 and _num(F.get("macd_hist_prev")) is not None)
             else None,
             f"DIF {fm(F.get('macd_dif'))} / DEA {fm(F.get('macd_dea'))}，"
             f"红柱 {fm(F.get('macd_hist'))}",
         ),
         weight=1.5, expect="DIF>DEA 且红柱持续放大"),
    Rule("macd_above_water", "DIF 站上零轴（水上）",
         lambda F: (cmpf(F.get("macd_dif"), ">", 0),
                    f"DIF {fm(F.get('macd_dif'))}"),
         weight=1.0, expect="DIF > 0"),
    Rule("capital_inflow", "资金大幅净流入",
         lambda F: ((cmpf(F.get("main3"), ">", 0) and cmpf(F.get("main_pct5"), ">", 5))
                    if _num(F.get("main3")) is not None else None,
                    f"3日主力 {fm(F.get('main3'), '亿')}，占比均值 {fm(F.get('main_pct5'), '%')}"),
         weight=2.0, expect="净额>0 且 占比>5%"),
    Rule("huge_lead", "超大单主导",
         lambda F: (cmpf(F.get("huge_dom3"), ">", 0.45),
                    f"超大单占主力 {fm(F.get('huge_dom3'))}"),
         weight=1.2, expect="> 0.45"),
    Rule("strong_bar", "强势 K 线",
         lambda F: ((cmpf(F.get("last_chg"), ">", 5) or cmpf(F.get("limitup10"), ">=", 1))
                    if _num(F.get("last_chg")) is not None else None,
                    f"当日涨幅 {fm(F.get('last_chg'), '%')}，近10日涨停 {fm(F.get('limitup10'), '次', 0)}"),
         weight=1.5, expect="涨幅>5% 或 有涨停"),
    Rule("profit_moderate", "获利盘未过热",
         lambda F: ((cmpf(F.get("profit_ratio"), ">=", 35) and cmpf(F.get("profit_ratio"), "<", 92))
                    if _num(F.get("profit_ratio")) is not None else None,
                    f"获利盘 {fm(F.get('profit_ratio'), '%', 1)}"),
         weight=1.2, expect="35% ~ 92%"),
    Rule("low_overhead", "上方抛压有限",
         lambda F: (cmpf(F.get("overhead"), "<", 22),
                    f"上方套牢盘 {fm(F.get('overhead'), '%', 1)}"),
         weight=1.2, expect="< 22%"),
    Rule("active_turnover", "换手活跃",
         lambda F: ((cmpf(F.get("turnover5"), ">=", 3) and cmpf(F.get("turnover5"), "<=", 20))
                    if _num(F.get("turnover5")) is not None else None,
                    f"5日换手 {fm(F.get('turnover5'), '%')}"),
         weight=1.0, expect="3% ~ 20%"),
    Rule("resonance", "资金共振",
         lambda F: ((cmpf(F.get("lhb_net"), ">", 0) if _num(F.get("lhb_net")) is not None else None),
                    f"机构席位净额 {fm(F.get('lhb_net'), '亿')}"),
         weight=1.2, expect="机构净买 > 0"),
    Rule("obv_rising", "OBV 同步走强",
         lambda F: (cmpf(F.get("obv_slope20"), ">", 0),
                    f"OBV 斜率 {fm(F.get('obv_slope20'))}"),
         weight=1.0, expect="> 0"),
]

# ---------------- 撤离期 ----------------
RULES["DISTRIBUTION"] = [
    Rule("vol_stagnant", "放量滞涨",
         lambda F: (
             ((cmpf(F.get("vr"), ">", 1.5) is True)
              and (cmpf(F.get("last_chg"), "<", 2.5) is True))
             if (_num(F.get("vr")) is not None and _num(F.get("last_chg")) is not None)
             else None,
             f"量比 {fm(F.get('vr'))}，当日涨幅 {fm(F.get('last_chg'), '%')}",
         ),
         weight=2.0, expect="放量但涨幅<2.5%"),
    Rule("turnover_hot", "换手过热",
         lambda F: (cmpf(F.get("turnover5"), ">", 12),
                    f"5日换手 {fm(F.get('turnover5'), '%')}"),
         weight=1.8, expect="> 12%"),
    Rule("upper_shadow_days", "反复长上影",
         lambda F: (cmpf(F.get("up_shadow_days10"), ">=", 2),
                    f"近10日长上影 {fm(F.get('up_shadow_days10'), '天', 0)}"),
         weight=1.5, expect="≥ 2 天"),
    Rule("chip_shift_up", "底部筹码上移 / 消失",
         lambda F: (
             ((cmpf(F.get("bottom_locked"), "<", 25) is True)
              and (cmpf(F.get("chip_shift20"), ">", 4) is True))
             if (F.get("bottom_locked") is not None and F.get("chip_shift20") is not None)
             else None,
             f"低位锁定 {fm(F.get('bottom_locked'), '%', 1)}，"
             f"20日重心迁移 {fm(F.get('chip_shift20'), '%')}",
         ),
         weight=2.2, expect="< 25% 且 重心上移>4%"),
    Rule("main_outflow", "主力净流出",
         lambda F: (
             ((cmpf(F.get("main5_amt_ratio"), "<", -2) is True)
              or (cmpf(F.get("main10_amt_ratio"), "<", -1.5) is True))
             if (F.get("main5_amt_ratio") is not None
                 or F.get("main10_amt_ratio") is not None)
             else None,
             f"5日主力占成交额 {fm(F.get('main5_amt_ratio'), '%')}，"
             f"10日 {fm(F.get('main10_amt_ratio'), '%')}",
         ),
         weight=2.0, expect="净流出占成交额>2%"),
    Rule("blow_off", "加速赶顶（乖离失控）",
         lambda F: (
             ((cmpf(F.get("bias20"), ">", 22) is True)
              and (cmpf(F.get("pos250"), ">", 88) is True))
             if (_num(F.get("bias20")) is not None and _num(F.get("pos250")) is not None)
             else None,
             f"MA20乖离 {fm(F.get('bias20'), '%')}，位置分位 {fm(F.get('pos250'))}",
         ),
         weight=2.2, expect="乖离>22% 且 位置分位>88"),
    Rule("limitup_crowd", "连板透支",
         lambda F: (
             ((cmpf(F.get("limitup10"), ">=", 3) is True)
              and (cmpf(F.get("pos250"), ">", 85) is True))
             if (_num(F.get("limitup10")) is not None and _num(F.get("pos250")) is not None)
             else None,
             f"近10日涨停 {fm(F.get('limitup10'), '次', 0)}，位置分位 {fm(F.get('pos250'))}",
         ),
         weight=1.5, expect="≥3次 且 位置>85"),
    Rule("extreme_turnover", "换手极端放大",
         lambda F: (cmpf(F.get("turnover5"), ">", 18),
                    f"5日换手 {fm(F.get('turnover5'), '%')}"),
         weight=1.5, expect="> 18%"),
    Rule("huge_out_small_in", "大单出、散户接",
         lambda F: (
             ((cmpf(F.get("huge3"), "<", 0) is True)
              and (cmpf(F.get("small3"), ">", 0) is True))
             if (_num(F.get("huge3")) is not None and _num(F.get("small3")) is not None)
             else None,
             f"3日超大单 {fm(F.get('huge3'), '亿')}，小单 {fm(F.get('small3'), '亿')}",
         ),
         weight=2.0, expect="超大单净流出 + 小单净流入"),
    Rule("macd_divergence", "顶背离",
         lambda F: (F.get("divergence") == "顶背离" if F.get("divergence") else None,
                    f"{F.get('divergence') or '无显著背离'}"),
         weight=1.5, expect="出现顶背离"),
    Rule("inst_sell", "机构席位净卖出",
         lambda F: ((cmpf(F.get("lhb_net"), "<", 0) if _num(F.get("lhb_net")) is not None else None),
                    f"机构席位净额 {fm(F.get('lhb_net'), '亿')}"),
         weight=1.5, expect="< 0"),
    Rule("margin_high", "融资余额高位",
         lambda F: (cmpf(F.get("margin_pctile"), ">", 75),
                    f"融资余额分位 {fm(F.get('margin_pctile'), '', 0)}"),
         weight=1.2, expect="> 75 分位"),
    Rule("break_ma10", "跌破 MA10",
         lambda F: (cmpf(F.get("dist_ma10"), "<", 0),
                    f"距MA10 {fm(F.get('dist_ma10'), '%')}"),
         weight=1.2, expect="< 0"),
    Rule("weak_rebound", "反抽缩量",
         lambda F: ((cmpf(F.get("dd20"), "<", -8) and cmpf(F.get("vol_trend5"), "<", 0.95))
                    if _num(F.get("dd20")) is not None else None,
                    f"20日回撤 {fm(F.get('dd20'), '%')}，量能趋势 {fm(F.get('vol_trend5'))}"),
         weight=1.2, expect="回撤>8% 且 量能萎缩"),
    Rule("high_swing", "高位宽幅震荡",
         lambda F: (cmpf(F.get("amp10"), ">", 5.5),
                    f"10日振幅均值 {fm(F.get('amp10'), '%')}"),
         weight=1.0, expect="> 5.5%"),
    Rule("high_position", "所处位置偏高",
         lambda F: (cmpf(F.get("pos250"), ">", 70),
                    f"年内位置分位 {fm(F.get('pos250'))}"),
         weight=1.5, expect="> 70"),
    Rule("overheated_profit", "获利盘极度膨胀",
         lambda F: (cmpf(F.get("profit_ratio"), ">", 88),
                    f"获利盘 {fm(F.get('profit_ratio'), '%', 1)}"),
         weight=1.2, expect="> 88%"),
]

# 门槛条件：不满足则该阶段得分打折
GATES: Dict[str, List[Callable[[Dict], Optional[bool]]]] = {
    # 建仓期：位置不能已在山顶
    "ACCUMULATION": [lambda F: cmpf(F.get("pos250"), "<", 78)],
    # 洗盘期：必须有明显回调，且均线未彻底转空（否则是趋势性下跌，不是洗盘）
    "WASH": [
        lambda F: cmpf(F.get("dd20"), "<", -4),
        lambda F: (False if F.get("ma_align") == "空头排列" else True)
                  if F.get("ma_align") else None,
    ],
    # 启动期：需突破或站稳关键位；且乖离不能失控（失控说明已在中后段）
    "LAUNCH": [
        lambda F: ((_ok(F.get("breakout")) and F["breakout"])
                   or cmpf(F.get("dist_ma20"), ">", -1)),
        lambda F: cmpf(F.get("bias20"), "<", 30),
    ],
    # 撤离期：位置必须偏高
    "DISTRIBUTION": [lambda F: cmpf(F.get("pos250"), ">", 55)],
}

GATE_PENALTY = 0.62     # gate 不满足时的分数折扣


# ==============================================================
# 评估主流程
# ==============================================================
def evaluate_stage(stage: str, F: Dict) -> tuple:
    """计算单阶段得分与证据列表。"""
    evs: List[Evidence] = []
    tot_w = 0.0
    hit_w = 0.0
    for rule in RULES[stage]:
        try:
            hit, desc = rule.test(F)
        except Exception as e:  # noqa: BLE001
            hit, desc = None, f"计算异常: {e}"
        if not isinstance(hit, bool):
            hit_out = None
        else:
            hit_out = bool(hit)
            tot_w += rule.weight
            if hit_out:
                hit_w += rule.weight
        evs.append(Evidence(rule.key, rule.label, hit_out, desc,
                            rule.weight, rule.expect))

    base = (hit_w / tot_w * 100) if tot_w > 0 else 0.0

    # 门槛检查
    gate_results = []
    for g in GATES.get(stage, []):
        try:
            gate_results.append(g(F))
        except Exception:  # noqa: BLE001
            gate_results.append(None)
    applicable = [g for g in gate_results if isinstance(g, bool)]
    if applicable and not all(applicable):
        score = base * GATE_PENALTY
        gate_ok = False
    else:
        score = base
        gate_ok = True

    return score, evs, gate_ok, len(applicable)


def detect_stage(F: Dict) -> StageResult:
    """主入口：输入特征字典 F，输出四阶段判定结果。"""
    scores: Dict[str, float] = {}
    evidences: Dict[str, List[Evidence]] = {}
    gates: Dict[str, Dict[str, Any]] = {}
    coverage: Dict[str, int] = {}

    for stage in STAGE_META:
        s, evs, gok, n_app = evaluate_stage(stage, F)
        scores[stage] = round(s, 1)
        evidences[stage] = evs
        gates[stage] = {"ok": gok, "checked": n_app}
        coverage[stage] = sum(1 for e in evs if e.hit is not None)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top_stage, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0

    return StageResult(
        stage=top_stage, scores=scores, evidences=evidences,
        gates=gates, confidence=round(top_score - second, 1),
        coverage=coverage,
    )


def confidence_label(conf: float) -> str:
    if conf >= 25:
        return "高置信"
    if conf >= 12:
        return "中等置信"
    if conf >= 5:
        return "弱信号"
    return "模糊区间"


# ==============================================================
# 操作评分：把「阶段判定」翻译成「当下该干什么、值不值得干」
# ==============================================================
def action_scores(F: Dict, res: StageResult) -> Dict:
    """输出机会分、风险分与操作建议。

    机会分：值不值得介入（越高越好）
    风险分：危险程度（越高越危险）
    两者正交 —— 一只票可以同时「高机会 + 高风险」，这正是需要提示的内容。
    """
    def cl(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    st = res.stage
    ratio = F.get("main5_amt_ratio")
    pos = F.get("pos250")
    bias = F.get("bias20")
    to5 = F.get("turnover5")
    pr = F.get("profit_ratio")
    shift = F.get("chip_shift20")
    locked = F.get("bottom_locked")

    # ---------- 机会分 ----------
    opp = 50.0
    opp += {"LAUNCH": 20, "ACCUMULATION": 12, "WASH": 4, "DISTRIBUTION": -18}.get(st, 0)
    if ratio is not None:
        opp += 10 if ratio > 3 else 5 if ratio > 0 else -10 if ratio < -3 else 0
    if pos is not None:
        opp += 8 if pos < 40 else -8 if pos > 85 else 0
    if F.get("vr") and F.get("vol_trend5"):
        if F["vr"] > 1.2 and F["vol_trend5"] > 1.1:
            opp += 6
    if pr is not None:
        opp += -6 if pr > 90 else 4 if pr < 30 else 0
    if not res.gates.get(st, {}).get("ok", True):
        opp -= 5
    if res.confidence < 5:
        opp -= 5                      # 阶段模糊本身就是负分
    opp = cl(opp)

    # ---------- 风险分 ----------
    risk = 25.0
    risk += {"DISTRIBUTION": 35, "LAUNCH": 12, "WASH": 5, "ACCUMULATION": 0}.get(st, 0)
    if bias is not None:
        risk += 20 if bias > 30 else 12 if bias > 20 else 5 if bias > 12 else 0
    if to5 is not None:
        risk += 15 if to5 > 18 else 8 if to5 > 12 else 0
    if shift is not None and locked is not None:
        if shift > 8 and locked < 15:
            risk += 12
    if ratio is not None and ratio < -5:
        risk += 12
    if pos is not None and pos > 90:
        risk += 8
    if pr is not None and pr > 92:
        risk += 8
    risk = cl(risk)

    # ---------- 操作建议 ----------
    if risk >= 65:
        act, tone = "减仓离场", "#c62828"
    elif risk >= 50:
        act, tone = "谨慎持有", "#e65100"
    elif opp >= 65 and risk < 45:
        act, tone = "重点介入", "#c62828"
    elif opp >= 55 and risk < 50:
        act, tone = "逢低关注", "#185FA5"
    elif opp >= 45:
        act, tone = "跟踪观察", "#5d4037"
    else:
        act, tone = "暂避观望", "#6b7280"

    return {
        "opportunity": round(opp),
        "risk": round(risk),
        "action": act,
        "tone": tone,
        "reason": (
            f"阶段为{STAGE_META[st]['name']}（{res.score:.0f}分/{confidence_label(res.confidence)}），"
            f"机会分 {opp:.0f}、风险分 {risk:.0f}；"
            f"{'资金净流入' if (ratio or 0) > 0 else '资金净流出'}"
            f"{abs(ratio or 0):.1f}%，年内位置 {pos if pos is not None else 0:.0f} 分位。"
        ),
    }


def build_conclusion(res: StageResult, F: Dict) -> str:
    """生成面向人的自然语言结论。"""
    meta = STAGE_META[res.stage]
    top = res.top_evidences[:4]
    labels = "、".join(e.label for e in top) if top else "无明显特征"
    ranked = sorted(res.scores.items(), key=lambda kv: -kv[1])
    second_stage, second_score = ranked[1]
    alt = STAGE_META[second_stage]["name"]

    txt = (
        f"综合 {res.coverage[res.stage]} 项有效指标，判定当前处于【{meta['name']}】，"
        f"阶段得分 {res.score:.0f} 分，{confidence_label(res.confidence)}"
        f"（领先次优判定「{alt}」{res.confidence:.0f} 分）。"
        f"核心支撑证据：{labels}。"
        f"该阶段机构的核心矛盾是「{meta['core']}」，"
        f"对应操作取向：{meta['action']}。"
    )
    if res.confidence < 5:
        txt += (
            f"注意：当前 {meta['name']} 与 {alt} 分数接近（差 {res.confidence:.0f} 分），"
            "处于阶段切换的模糊带，建议等待关键信号确认后再行动。"
        )
    if not res.gates[res.stage]["ok"]:
        txt += "（该阶段门槛条件未完全满足，判定为弱确认，需谨慎对待。）"
    return txt
