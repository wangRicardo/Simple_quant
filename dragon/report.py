# -*- coding: utf-8 -*-
"""
HTML 报告渲染层。

把四阶段判定结果渲染成一份可直接阅读/存档的报告：
    - 总览：候选池 × 阶段判定矩阵
    - 详情：每只标的的证据链 + 关键指标 + 量价图 + 资金流图 + 筹码分布图
    - 回放：阶段随时间的迁移轨迹
    - 附录：阈值表与口径说明

图表用 ECharts（CDN），主题配色遵循 A 股习惯。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from .stage import STAGE_META, confidence_label

ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"

ORDER = ["ACCUMULATION", "WASH", "LAUNCH", "DISTRIBUTION"]


# ==============================================================
# 序列化工具
# ==============================================================
def clean(obj):
    """把 numpy / None / 嵌套结构清洗成 JSON 安全的原生类型。"""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (bool,)):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):  # NaN / Inf
            return None
        return round(float(obj), 4)
    if obj is None or isinstance(obj, str):
        return obj
    return str(obj)


def f2(v, unit: str = "", nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}{unit}"
    except Exception:  # noqa: BLE001
        return "—"


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
     background:#f7f8fa;color:#1f2328;line-height:1.7;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 80px}
header{background:linear-gradient(135deg,#1e3a5f 0%,#2c5282 100%);color:#fff;
       border-radius:14px;padding:36px 40px;margin-bottom:28px;box-shadow:0 8px 24px rgba(30,58,95,.18)}
header h1{font-size:27px;font-weight:650;letter-spacing:.5px;margin-bottom:10px}
header .sub{opacity:.9;font-size:14.5px}
.meta-row{display:flex;flex-wrap:wrap;gap:22px;margin-top:20px;font-size:13px;opacity:.92}
.meta-row span b{font-weight:600}
h2{font-size:20px;font-weight:640;margin:34px 0 16px;padding-left:12px;border-left:4px solid #2c5282}
h3{font-size:16.5px;font-weight:620;margin:22px 0 12px;color:#2c3e50}
.card{background:#fff;border:1px solid #e6e9ef;border-radius:12px;padding:22px 26px;margin-bottom:18px;
      box-shadow:0 1px 3px rgba(16,24,40,.04)}
.grid{display:grid;gap:16px}
.card-hd{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;
         padding-bottom:14px;margin-bottom:16px;border-bottom:1px solid #eef0f4}
.stock-nm{font-size:19px;font-weight:660}
.stock-cd{font-size:13.5px;color:#6b7280;margin-left:8px;font-weight:400}
.badge{display:inline-block;padding:5px 15px;border-radius:20px;color:#fff;font-size:14px;font-weight:600}
.conf-box{text-align:right;font-size:12.5px;color:#6b7280}
.conf-box b{display:block;font-size:23px;line-height:1.25}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid #eef0f4}
th{background:#fafbfc;font-weight:600;color:#4b5563;font-size:12.5px;
   text-transform:uppercase;letter-spacing:.4px}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#fafbfc}
.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:#c62828;font-weight:600}
.neg{color:#2e7d32;font-weight:600}
.mut{color:#9ca3af}
.stage-bars{margin:14px 0 6px}
.sb{display:flex;align-items:center;gap:11px;margin-bottom:7px}
.sb-lb{width:78px;font-size:13px;color:#4b5563;flex-shrink:0}
.sb-tr{flex:1;height:22px;background:#f0f2f5;border-radius:4px;overflow:hidden}
.sb-fl{height:100%;border-radius:4px;transition:width .5s ease;opacity:.92}
.sb-vl{width:52px;text-align:right;font-size:13px;font-variant-numeric:tabular-nums;font-weight:600}
.ev-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:9px;margin-top:12px}
.ev{border:1px solid #e8eaee;border-radius:8px;padding:10px 13px;background:#fcfcfd;font-size:13px}
.ev.y{border-left:3px solid #c62828;background:#fef7f7}
.ev.n{border-left:3px solid #d1d5db;opacity:.72}
.ev-t{font-weight:600;display:flex;justify-content:space-between;align-items:center;gap:8px}
.ev-d{color:#6b7280;font-size:12.5px;margin-top:3px}
.w{font-size:11px;color:#9ca3af;font-weight:400}
.chart{width:100%;height:280px;margin-top:8px}
.chart-s{width:100%;height:230px}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:11px;margin-top:14px}
.kv-i{background:#fafbfc;border:1px solid #eef0f4;border-radius:8px;padding:10px 13px}
.kv-l{font-size:11.5px;color:#6b7280;letter-spacing:.2px}
.kv-v{font-size:16.5px;font-weight:640;margin-top:2px;font-variant-numeric:tabular-nums}
.note{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:15px 19px;
      font-size:13.5px;color:#78350f;margin:18px 0}
.sum-tbl td:first-child{font-weight:600}
.foot{margin-top:40px;padding:20px 24px;background:#fff;border:1px solid #e6e9ef;border-radius:12px;
      font-size:12.5px;color:#6b7280;line-height:1.85}
.tagline{display:inline-block;font-size:12px;padding:3px 9px;border-radius:5px;margin-left:7px;
         background:#eef2ff;color:#3b4ea0;font-weight:500}
"""


def _badge(stage: str) -> str:
    m = STAGE_META[stage]
    return f'<span class="badge" style="background:{m["color"]}">{m["icon"]} {m["name"]}</span>'


def _stage_bars(scores: Dict[str, float], cur: str) -> str:
    rows = []
    for s in ORDER:
        v = float(scores.get(s, 0))
        m = STAGE_META[s]
        hl = "font-weight:700;color:#1f2328" if s == cur else ""
        rows.append(
            f'<div class="sb"><div class="sb-lb" style="{hl}">{m["name"]}</div>'
            f'<div class="sb-tr"><div class="sb-fl" style="width:{max(v,1.2):.1f}%;'
            f'background:{m["color"]}"></div></div>'
            f'<div class="sb-vl" style="{hl}">{v:.0f}</div></div>'
        )
    return f'<div class="stage-bars">{"".join(rows)}</div>'


def _evidences(evs: List[Dict]) -> str:
    if not evs:
        return ""
    items = []
    for e in evs:
        if e["hit"] is True:
            cls, mark = "y", "✓"
        elif e["hit"] is False:
            cls, mark = "n", "✗"
        else:
            continue
        items.append(
            f'<div class="ev {cls}"><div class="ev-t"><span>{mark} {e["label"]}</span>'
            f'<span class="w">权重{e["weight"]:.1f}</span></div>'
            f'<div class="ev-d">{e["desc"]}</div>'
            f'<div class="ev-d" style="color:#9ca3af">判据：{e["expect"]}</div></div>'
        )
    return f'<div class="ev-grid">{"".join(items)}</div>'


def _kv(pairs: List[tuple]) -> str:
    items = "".join(
        f'<div class="kv-i"><div class="kv-l">{lb}</div><div class="kv-v">{vl}</div></div>'
        for lb, vl in pairs
    )
    return f'<div class="kv">{items}</div>'


def _trail(hist: Optional[List]) -> str:
    """把阶段迁移序列压缩成一行彩色轨迹，直观展示「洗盘→建仓→启动」的演化。"""
    if not hist:
        return ""
    chips = []
    prev = None
    for row in hist:
        st = row["stage"]
        if st != prev:
            m = STAGE_META[st]
            chips.append(
                f'<span style="display:inline-block;padding:3px 10px;border-radius:4px;'
                f'background:{m["color"]};color:#fff;font-size:11.5px;font-weight:600;'
                f'margin-right:5px">{m["name"]}</span>')
            prev = st
        else:
            prev = st
    if not chips:
        return ""
    first, last = hist[0], hist[-1]
    return (
        f'<h3>阶段迁移轨迹（{first["date"]} → {last["date"]}）</h3>'
        f'<div style="margin-top:6px">{"".join(chips)}</div>'
        f'<p style="font-size:12.5px;color:#6b7280;margin-top:9px">'
        f'共 {len(hist)} 个交易日，最终收于'
        f'<b style="color:{STAGE_META[last["stage"]]["color"]}"> '
        f'{STAGE_META[last["stage"]]["name"]}</b>'
        f'（{last["score"]:.0f} 分）。轨迹从 '
        f'{STAGE_META[first["stage"]]["name"]} 起步，期间经历 '
        f'{len(chips)} 次阶段切换。</p>'
    )


def render(analyses: List[Dict], history: Optional[Dict[str, List]] = None,
           watchlist_note: str = "", elapsed: float = 0.0) -> str:
    """生成完整 HTML。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_day = analyses[0].get("as_of", "—") if analyses else "—"
    trimmed = any(a.get("trimmed") for a in analyses)

    parts: List[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>龙头战法量化系统 · 阶段判定报告</title>
<script src="{ECHARTS_CDN}"></script>
<style>{CSS}</style></head><body><div class="wrap">
<header>
  <h1>龙头战法量化系统 · 机构行为阶段判定报告</h1>
  <div class="sub">通过量价、资金、筹码与形态四维指标，判别个股当前所处的机构行为阶段：
       建仓 → 洗盘 → 启动 → 撤离</div>
  <div class="meta-row">
    <span><b>生成时间</b> {now}</span>
    <span><b>判定基准日</b> {base_day}</span>
    <span><b>标的数</b> {len(analyses)}</span>
    <span><b>数据源</b> 东方财富（行情/资金流/龙虎榜/融资融券）</span>
  </div>
</header>
""")

    if trimmed:
        parts.append(
            '<div class="note"><b>数据口径说明</b>：当前为交易时段，当日 K 线尚未收盘，'
            '成交量仅累计至当前时刻。若直接参与计算会系统性低估量比、造成"缩量"假象。'
            '系统已自动<b>剔除未收盘的当日数据</b>，以上一完整交易日作为判定基准日，'
            '避免出现未来函数与半成品数据污染。</div>'
        )

    if watchlist_note:
        parts.append(f'<div class="note">{watchlist_note}</div>')

    # ---------- 总览表 ----------
    parts.append("<h2>一、判定总览</h2><div class='card' style='padding:0;overflow:hidden'>"
                 "<table class='sum-tbl'><thead><tr>"
                 "<th>标的</th><th>阶段判定</th><th>置信</th>"
                 "<th class='num'>建仓</th><th class='num'>洗盘</th>"
                 "<th class='num'>启动</th><th class='num'>撤离</th>"
                 "<th class='num'>收盘</th><th class='num'>5日主力</th><th>阶段要义</th>"
                 "</tr></thead><tbody>")
    for a in analyses:
        r = a["result"]
        F = a["features"]
        sc = r.scores
        mn = F.get("main5")
        cls = "pos" if (mn or 0) > 0 else "neg" if (mn or 0) < 0 else "mut"
        parts.append(
            f"<tr><td>{a['name']}<span class='mut' style='font-weight:400'> {a['code']}</span></td>"
            f"<td>{_badge(r.stage)}</td>"
            f"<td><b>{confidence_label(r.confidence)}</b><span class='mut'> {r.confidence:.0f}</span></td>"
            f"<td class='num'>{sc.get('ACCUMULATION',0):.0f}</td>"
            f"<td class='num'>{sc.get('WASH',0):.0f}</td>"
            f"<td class='num'>{sc.get('LAUNCH',0):.0f}</td>"
            f"<td class='num'>{sc.get('DISTRIBUTION',0):.0f}</td>"
            f"<td class='num'>{f2(F.get('price'))}</td>"
            f"<td class='num {cls}'>{f2(mn,'亿')}</td>"
            f"<td style='font-size:12.5px;color:#6b7280'>{STAGE_META[r.stage]['action']}</td></tr>"
        )
    parts.append("</tbody></table></div>")

    # ---------- 阶段轮转图 ----------
    if history:
        parts.append("<h2>二、阶段迁移轨迹（近 25 交易日）</h2>")
        parts.append("<div class='card'><div class='chart' id='ch_tl'></div>"
                     "<p style='font-size:12.5px;color:#6b7280;margin-top:10px'>"
                     "曲线为每日重新判定所得到的「主阶段得分」，可观察机构行为在时间轴上的迁移过程。"
                     "阶段切换往往领先于价格拐点。</p></div>")

    # ---------- 个股详情 ----------
    parts.append(f"<h2>{'三' if history else '二'}、个股深度判定</h2>")
    for idx, a in enumerate(analyses):
        r = a["result"]
        F = a["features"]
        meta = STAGE_META[r.stage]
        snap = a.get("snapshot") or {}
        parts.append(f"""<div class="card">
  <div class="card-hd">
    <div><span class="stock-nm">{a['name']}</span><span class="stock-cd">{a['code']}</span>
         {_badge(r.stage)}
         <span class="tagline">核心矛盾：{meta['core']}</span></div>
    <div class="conf-box"><b style="color:{meta['color']}">{r.score:.0f}分</b>
         {confidence_label(r.confidence)}（领先{r.confidence:.0f}分）</div>
  </div>
  <p style="font-size:13.5px;color:#374151">{a['conclusion']}</p>
  <h3>阶段得分分布</h3>
  {_stage_bars(r.scores, r.stage)}
  <h3>关键量化指标</h3>
  {_kv([
      ("收盘价", f2(F.get('price'))),
      ("5日主力净额", f2(F.get('main5'), '亿')),
      ("主力占成交额", f2(F.get('main5_amt_ratio'), '%')),
      ("当日量比", f2(F.get('vr'))),
      ("5日换手率", f2(F.get('turnover5'), '%')),
      ("年内位置分位", f2(F.get('pos250'), '', 0)),
      ("20日回撤", f2(F.get('dd20'), '%')),
      ("均线排列", F.get('ma_align') or '—'),
      ("获利盘", f2(F.get('profit_ratio'), '%', 1)),
      ("低位锁定筹码", f2(F.get('bottom_locked'), '%', 1)),
      ("筹码重心迁移20日", f2(F.get('chip_shift20'), '%')),
      ("龙虎榜席位净额", f2(F.get('lhb_net'), '亿')),
  ])}
  <h3>价格与成交（近 60 日）</h3>
  <div class="chart" id="ch_px_{idx}"></div>
  <h3>主力资金流（近 30 日）</h3>
  <div class="chart-s" id="ch_fl_{idx}"></div>
  <h3>筹码分布</h3>
  <div class="chart-s" id="ch_cp_{idx}"></div>
  <h3>证据链（✓ 已满足 / ✗ 未满足）</h3>
  {_evidences([e.to_dict() for e in r.evidences[r.stage]])}
  {_trail(history.get(a['code']) if history else None)}
</div>""")

    # ---------- 阈值表 ----------
    parts.append(f"""<h2>{'四' if history else '三'}、识别体系与阈值</h2>
<div class="card">
<table><thead><tr><th>阶段</th><th>核心矛盾</th><th>关键量化判据</th><th>操作取向</th></tr></thead><tbody>
<tr><td><b style="color:#185FA5">建仓期</b></td><td>要买但怕抬价</td>
    <td>资金逆势回流（主力净流入占成交额&gt;3%）、OBV抬升而股价横盘、位置处于中低位、深度超跌、龙虎榜机构净买</td>
    <td>跟踪观察，分批低吸，等量能确认</td></tr>
<tr><td><b style="color:#e65100">洗盘期</b></td><td>要吓人但不能真卖</td>
    <td>缩量下跌（量比&lt;0.95）、跌幅可控、未破MA60、底部筹码锁定&gt;18%、主力流出占成交额&lt;5%</td>
    <td>拿住不动，破关键位止损</td></tr>
<tr><td><b style="color:#c62828">启动期</b></td><td>想快拉但需人跟</td>
    <td>放量突破平台、站上MA20、均线多头、MACD红柱放大、超大单占主力&gt;45%、上方套牢盘&lt;22%</td>
    <td>主升持有，破MA20离场</td></tr>
<tr><td><b style="color:#5d4037">撤离期</b></td><td>要卖但怕崩</td>
    <td>底部筹码上移/消失、主力净流出占成交额&gt;2%、超大单出而小单接、加速赶顶（乖离&gt;22%）、换手&gt;18%</td>
    <td>减仓离场，不参与高位缩量反抽</td></tr>
</tbody></table>
<p style="margin-top:16px;font-size:13px;color:#6b7280">
<b>判分机制</b>：每个阶段一组加权证据，每条规则输出「满足/不满足/数据不足」三态；
数据不足的项自动剔除、不计入分母。阶段得分 = Σ命中权重 / Σ适用权重 × 100。
另设<b>门槛条件</b>（如撤离期要求位置分位&gt;55、启动期要求乖离&lt;30%），
不满足则总分打 62 折。最终取四阶段最高分为判定结果，
<b>置信度 = 最高分 − 次高分</b>，差值越小说明越接近阶段切换的模糊带。</p>
</div>""")

    # ---------- 图表数据 ----------
    charts_data = []
    for idx, a in enumerate(analyses):
        charts_data.append({
            "idx": idx,
            "kline": a.get("kline", []),
            "flow": a.get("flow", []),
            "chip": a.get("chip_curve", []),
            "price": a["features"].get("price"),
            "avg_cost": a.get("avg_cost"),
            "stage": a["result"].stage,
        })
    hist_data = {}
    if history:
        hist_data = {k: v for k, v in history.items()}

    payload = clean({"charts": charts_data, "history": hist_data,
                     "order": ORDER,
                     "meta": {k: {"name": v["name"], "color": v["color"]}
                              for k, v in STAGE_META.items()}})

    parts.append(f"""
<script>
var DATA = {json.dumps(payload, ensure_ascii=False)};
(function(){{
  var META = DATA.meta, ORDER = DATA.order;
  DATA.charts.forEach(function(d){{
    var base = {{tooltip:{{trigger:'axis'}},grid:{{left:'2%',right:'2%',bottom:'2%',containLabel:true}},
      textStyle:{{fontFamily:'-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,sans-serif'}}}};
    // 1. 量价图
    var c1 = echarts.init(document.getElementById('ch_px_'+d.idx));
    var kl = d.kline||[], dates = kl.map(function(x){{return x.date;}}),
        closes = kl.map(function(x){{return x.close;}}),
        amts = kl.map(function(x){{return x.amount;}}),
        turns = kl.map(function(x){{return x.turnover;}});
    c1.setOption(Object.assign({{}}, base, {{
      tooltip:{{trigger:'axis',axisPointer:{{type:'cross'}},
        formatter:function(ps){{
          var i=ps[0].dataIndex, k=kl[i];
          return k.date+'<br/>开 '+k.open.toFixed(2)+' 收 <b>'+k.close.toFixed(2)+
            '</b><br/>高 '+k.high.toFixed(2)+' 低 '+k.low.toFixed(2)+
            '<br/>涨跌幅 '+(k.chg>0?'<span style="color:#c62828">+':'<span style="color:#2e7d32">')+k.chg.toFixed(2)+
            '%</span><br/>换手 '+k.turnover.toFixed(2)+'%<br/>成交额 '+k.amount.toFixed(2)+'亿';
        }}}},
      xAxis:{{type:'category',data:dates,axisLabel:{{fontSize:10}},axisLine:{{lineStyle:{{color:'#d0d5dd'}}}}}},
      yAxis:[{{type:'value',name:'价格',scale:true,splitLine:{{lineStyle:{{color:'#f0f2f5'}}}},
              axisLabel:{{fontSize:10}}}},
             {{type:'value',name:'成交额(亿)',splitLine:{{show:false}},axisLabel:{{fontSize:10}}}}],
      series:[
        {{name:'成交额',type:'bar',yAxisIndex:1,data:amts,
          itemStyle:{{color:'rgba(214,222,235,0.65)'}}}},
        {{name:'收盘价',type:'line',yAxisIndex:0,data:closes,symbol:'none',
          lineStyle:{{color:'#c62828',width:2.2}},areaStyle:{{color:'rgba(198,40,40,0.06)'}}}}
      ]
    }}));
    // 2. 资金流
    var c2 = echarts.init(document.getElementById('ch_fl_'+d.idx));
    var fl = d.flow||[], fd = fl.map(function(x){{return x.date;}}),
        mn = fl.map(function(x){{return x.main;}}), hg = fl.map(function(x){{return x.huge;}});
    c2.setOption(Object.assign({{}}, base, {{
      tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}}}},
      legend:{{data:['主力净额','超大单净额'],top:2,itemWidth:12,itemHeight:8,textStyle:{{fontSize:11}}}},
      grid:{{left:'2%',right:'2%',bottom:'2%',top:34,containLabel:true}},
      xAxis:{{type:'category',data:fd,axisLabel:{{fontSize:10}}}},
      yAxis:{{type:'value',name:'亿元',splitLine:{{lineStyle:{{color:'#f0f2f5'}}}}}},
      series:[
        {{name:'主力净额',type:'bar',data:mn,
          itemStyle:{{color:function(p){{return p.value>=0?'#c62828':'#2e7d32';}}}}}},
        {{name:'超大单净额',type:'line',data:hg,symbol:'none',smooth:true,
          lineStyle:{{color:'#185FA5',width:1.8}}}}
      ]
    }}));
    // 3. 筹码分布
    var c3 = echarts.init(document.getElementById('ch_cp_'+d.idx));
    var cp = d.chip||[];
    c3.setOption(Object.assign({{}}, base, {{
      tooltip:{{trigger:'axis',formatter:function(ps){{
        return '价位 '+ps[0].data[0].toFixed(2)+'<br/>筹码占比 '+(ps[0].data[1]*100).toFixed(2)+'%';}}}},
      grid:{{left:'2%',right:'2%',bottom:'2%',top:20,containLabel:true}},
      xAxis:{{type:'category',data:cp.map(function(x){{return x[0].toFixed(2);}}),
              axisLabel:{{fontSize:9,interval:Math.ceil(cp.length/12)}}}},
      yAxis:{{type:'value',name:'筹码占比',splitLine:{{lineStyle:{{color:'#f0f2f5'}}}},
              axisLabel:{{formatter:function(v){{return (v*100).toFixed(1)+'%';}},fontSize:10}}}},
      series:[{{type:'bar',data:cp.map(function(x){{return x[1];}}),barCategoryGap:'8%',
        itemStyle:{{color:function(p){{
          var pv=parseFloat(cp[p.dataIndex][0]);
          return d.price && pv> d.price ? '#94a3b8' : '#c62828';}}}},
        markLine: d.price?{{silent:true,symbol:'none',
          lineStyle:{{color:'#185FA5',type:'dashed',width:1.5}},
          label:{{formatter:'现价 '+d.price.toFixed(2),fontSize:10}},
          data:[{{xAxis: cp.reduce(function(acc,cur,i){{
            return Math.abs(cur[0]-d.price)<Math.abs(cp[acc][0]-d.price)?i:acc;}},0)}}]}}:undefined
      }}]
    }}));
  }});
  // 4. 阶段迁移轨迹
  if (document.getElementById('ch_tl')) {{
    var c4 = echarts.init(document.getElementById('ch_tl'));
    var series=[], dates=null;
    Object.keys(DATA.history).forEach(function(code){{
      var h=DATA.history[code]||[]; if(!h.length) return;
      if(!dates) dates=h.map(function(x){{return x.date;}});
      ORDER.forEach(function(st){{
        series.push({{name: h[0].name+' · '+META[st].name, type:'line', smooth:true, symbol:'none',
          lineStyle:{{width: (st===h[h.length-1].stage)?2.6:1.3, type: (st===h[h.length-1].stage)?'solid':'dashed'}},
          itemStyle:{{color:META[st].color}}, data:h.map(function(x){{return x.scores[st];}})}});
      }});
    }});
    c4.setOption({{tooltip:{{trigger:'axis'}},legend:{{type:'scroll',top:0,itemWidth:12,itemHeight:8,
        textStyle:{{fontSize:10}}}},
      grid:{{left:'2%',right:'2%',bottom:'2%',top:52,containLabel:true}},
      xAxis:{{type:'category',data:dates||[],axisLabel:{{fontSize:10}}}},
      yAxis:{{type:'value',name:'阶段得分',max:100,splitLine:{{lineStyle:{{color:'#f0f2f5'}}}}}},
      series:series}});
  }}
  window.addEventListener('resize', function(){{
    DATA.charts.forEach(function(d){{
      ['ch_px_','ch_fl_','ch_cp_'].forEach(function(p){{
        var el=document.getElementById(p+d.idx);
        if(el && echarts.getInstanceByDom(el)) echarts.getInstanceByDom(el).resize();
      }});
    }});
    var t=document.getElementById('ch_tl');
    if(t && echarts.getInstanceByDom(t)) echarts.getInstanceByDom(t).resize();
  }});
}})();
</script>
<div class="foot">
<b>系统说明</b>：本报告由「龙头战法量化系统 v1.0」自动生成。数据来源于东方财富公开接口，
包含行情、资金流、龙虎榜、融资融券等，收盘后数据可能存在修正。<br/>
<b>口径说明</b>：龙虎榜净额为上榜当日全部席位买卖净额（含机构专用席位与游资席位），
并非纯粹的机构净买额；筹码分布采用通达信式三角形衰减模型估算，为近似值而非真实股东成本。<br/><br/>
<b>免责声明</b>：本报告所有内容基于公开数据与量化模型推演，<b>仅供研究参考，不构成任何投资建议</b>。
模型结论依赖历史统计规律，不预示未来走势。股市有风险，投资需谨慎。
任何投资决策应结合个人风险承受能力、资金状况与投资目标独立判断，必要时咨询持牌专业机构。
</div>
</div></body></html>""")
    return "".join(parts)
