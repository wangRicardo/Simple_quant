# -*- coding: utf-8 -*-
"""
行业龙头选取模块。

龙头的定义不是单一维度，而是三种龙头角色的叠加：
    · 市值龙头（行业地位，机构底仓所在）
    · 资金龙头（当下人气，主力资金流向）
    · 涨幅龙头（赚钱效应，带动板块情绪）

因此采用「行业内三项排名加权」而非绝对值打分 —— 绝对值会被行业体量差异
（银行 vs 光伏）严重扭曲，排名分位才可跨行业比较。

同时负责把行业板块代码解析出来（BK 代码会随东财调整变化，故按名称动态匹配）。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .datasource import EMClient

# 关注行业。东财板块为三级细分口径（如「证券Ⅲ」「锂电池」「品牌消费电子」），
# 故每个行业配置多个候选关键词，按优先级取第一个匹配到的板块。
FOCUS_INDUSTRIES: List[Tuple[str, List[str]]] = [
    ("半导体", ["半导体", "集成电路", "芯片", "模拟芯片", "数字芯片", "封测"]),
    ("消费电子", ["品牌消费电子", "消费电子", "消费电子零部件"]),
    ("通信设备", ["通信设备", "通信终端", "电信运营商", "通信工程"]),
    ("软件与IT", ["软件", "信息技术", "计算机设备", "IT服务", "金融信息服务"]),
    ("电子元件", ["印制电路板", "被动元件", "电子元件", "元件", "光学元件"]),
    ("面板光电子", ["光学光电子", "面板", "LED", "显示器件"]),
    ("电池", ["锂电池", "蓄电池", "电池", "燃料电池"]),
    ("光伏", ["光伏设备", "光伏加工", "光伏发电", "光伏辅材", "逆变器"]),
    ("汽车", ["汽车零部件", "综合乘用车", "汽车", "车身附件", "轮胎轮毂"]),
    ("医药", ["化学制药", "化学制剂", "生物制品", "原料药", "中药", "创新药"]),
    ("医疗器械", ["医疗器械", "医疗设备", "体外诊断", "诊断服务"]),
    ("白酒食品", ["白酒", "非白酒", "饮料乳品", "食品加工", "调味发酵品", "啤酒"]),
    ("银行", ["银行"]),
    ("证券金融", ["证券", "非银金融", "多元金融", "金融控股"]),
    ("有色贵金属", ["贵金属", "黄金", "白银", "小金属", "工业金属", "有色金属"]),
    ("电力", ["电力", "火力发电", "水力发电", "核力发电", "风力发电", "电能综合"]),
    ("军工", ["航天装备", "航空装备", "军工电子", "航海装备", "兵器"]),
    ("传媒游戏", ["游戏", "影视", "出版", "传媒", "广告", "院线", "媒体"]),
    ("煤炭石油", ["煤炭", "焦炭", "油气开采", "石油石化"]),
    ("房地产", ["房地产开发", "房地产服务", "商业地产", "物业管理"]),
    ("化工", ["化学制品", "化学工程", "农化", "化纤", "橡胶", "塑料"]),
    ("机械装备", ["工程机械", "自动化设备", "通用设备", "专用设备", "机床工具"]),
    ("钢铁煤炭链", ["钢铁", "特钢", "长材", "冶钢"]),
    ("交通运输", ["物流", "航空运输", "港口", "铁路公路", "快递", "高速公路"]),
]


def fetch_boards(client: EMClient, pz: int = 100, pages: int = 7) -> List[Dict]:
    """拉取行业板块列表（按主力净流入排序）。

    东财单页最多 100 条，行业板块约 86 个但接口在排序下可能重复/截断，
    因此分页拉取并按代码去重，确保关注行业都能匹配到。
    """
    import time as _t
    out, seen = [], set()
    for pn in range(1, pages + 1):
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get?"
            f"pn={pn}&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2"
            f"&fields=f12,f14,f2,f3,f62,f184"
        )
        d = client.get_json(url)
        if not d or not d.get("data"):
            _t.sleep(1.0)
            continue
        diff = d["data"].get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break
        for x in diff:
            code = x.get("f12")
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({
                "code": code,
                "name": x.get("f14") or "",
                "chg": x.get("f3"),
                "main_net": (x.get("f62") or 0) / 1e8,
                "main_pct": x.get("f184"),
            })
        _t.sleep(0.35)
    return out


def match_focus(boards: List[Dict],
                focus: Optional[List[Tuple[str, List[str]]]] = None
                ) -> List[Dict]:
    """按关键词把关注行业匹配到板块代码。每个行业取匹配到的第一个板块。"""
    focus = focus or FOCUS_INDUSTRIES
    picked: List[Dict] = []
    used = set()
    for label, keys in focus:
        for kw in keys:
            hit = None
            for b in boards:
                if b["code"] in used:
                    continue
                if kw in b["name"]:
                    hit = b
                    break
            if hit:
                hit = dict(hit)
                hit["label"] = label
                picked.append(hit)
                used.add(hit["code"])
                break
    return picked


def fetch_members(client: EMClient, board_code: str, pz: int = 60,
                  retries: int = 3) -> List[Dict]:
    """板块成分股，按成交额排序。带重试——批量拉取时容易被限流。"""
    import time as _t
    fields = "f12,f14,f2,f3,f6,f8,f10,f20,f62,f184"
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get?pn=1"
        f"&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f6&fs=b:{board_code}"
        f"&fields={fields}"
    )
    d = None
    for i in range(retries):
        d = client.get_json(url)
        if d and d.get("data"):
            break
        _t.sleep(1.5 * (i + 1))
    if not d or not d.get("data"):
        return []
    diff = d["data"].get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    out = []
    for x in diff:
        code = x.get("f12")
        name = (x.get("f14") or "").upper()
        if not code:
            continue
        if "ST" in name or "退" in name or "*" in name:
            continue
        if str(code).startswith(("4", "8", "92")):     # 北交所流动性不足
            continue
        price = x.get("f2")
        if not isinstance(price, (int, float)) or price <= 3:
            continue
        out.append({
            "code": code,
            "name": x.get("f14"),
            "price": price,
            "chg": x.get("f3"),
            "amount": (x.get("f6") or 0) / 1e8,        # 成交额(亿)
            "turnover": x.get("f8"),
            "vr": x.get("f10"),
            "mktcap": (x.get("f20") or 0) / 1e8,       # 总市值(亿)
            "main_net": (x.get("f62") or 0) / 1e8,     # 主力净额(亿)
            "main_pct": x.get("f184"),
        })
    return out


def _rank_pct(items: List[Dict], key: str) -> List[float]:
    """返回每个元素在 key 上的排名分位（0=最低, 1=最高）。"""
    n = len(items)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: -(items[i].get(key) or -1e18))
    pct = [0.0] * n
    if n == 1:
        return [1.0]
    for pos, i in enumerate(order):
        pct[i] = 1.0 - pos / (n - 1)
    return pct


def pick_leaders(members: List[Dict], n: int = 3) -> List[Dict]:
    """在行业内按「市值 + 资金 + 涨幅」三项排名加权选出龙头。

    权重依据龙头三角色的相对重要性：
        市值 40%（行业地位，决定能否承载大资金）
        资金 35%（当下主力态度）
        涨幅 25%（赚钱效应与带动能力）
    """
    if not members:
        return []
    cap_r = _rank_pct(members, "mktcap")
    main_r = _rank_pct(members, "main_net")
    chg_r = _rank_pct(members, "chg")
    for i, m in enumerate(members):
        m["leader_score"] = round((0.40 * cap_r[i]
                                   + 0.35 * main_r[i]
                                   + 0.25 * chg_r[i]) * 100, 1)
    items = sorted(members, key=lambda x: -x["leader_score"])
    return items[:n]


def build_industry_universe(client: EMClient, per_industry: int = 3,
                            focus: Optional[List[Tuple[str, List[str]]]] = None,
                            verbose: bool = True) -> List[Dict]:
    """构建「行业 → 龙头」清单。

    返回 [{'label','board','chg','main_net','leaders':[{code,name,...}]}, ...]
    """
    boards = fetch_boards(client)
    if not boards:
        if verbose:
            print("[行业] 板块列表获取失败")
        return []
    targets = match_focus(boards, focus)
    if verbose:
        print(f"[行业] 板块 {len(boards)} 个，匹配到关注行业 {len(targets)} 个")

    import time as _t
    universe: List[Dict] = []
    for i, t in enumerate(targets):
        members = fetch_members(client, t["code"], pz=60)
        _t.sleep(0.4)                       # 板块间留出间隔，降低触发限流概率
        if len(members) < 2:
            if verbose:
                print(f"       [跳过] {t['label']} 成分股获取失败")
            continue
        leaders = pick_leaders(members, per_industry)
        if not leaders:
            continue
        universe.append({
            "label": t["label"],
            "board": t["code"],
            "board_name": t["name"],
            "chg": t["chg"],
            "main_net": t["main_net"],
            "member_count": len(members),
            "leaders": leaders,
        })
        if verbose:
            names = "、".join(f"{x['name']}({x['leader_score']:.0f})" for x in leaders)
            print(f"       {t['label']:<8} {t['name']:<12} 涨{t['chg']:+.2f}% "
                  f"主力{t['main_net']:+.1f}亿 → {names}")
    return universe
