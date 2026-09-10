# -*- coding: utf-8 -*-
"""
网站生成器：行业龙头 · 每日阶段评分看板。

设计取舍：
  · 零外部依赖 —— 不引 CDN，评分用纯 CSS、K线图用纯 SVG 手绘。
    定时任务是无人值守场景，任何外部资源挂掉都会让页面打不开，稳定性优先于花哨。
  · 数据驱动 —— 同时输出 data.json（看板数据）与 klines.js（个股K线量价数据），
    便于后续对接其他前端或做时间序列分析。
  · 双文件 —— index.html 自包含骨架，klines.js 为独立 <script>（file:// 协议下
    经典脚本无跨域限制，fetch 才有；所以 K 线数据不能用 fetch 加载）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List

from .stage import STAGE_META, action_scores, confidence_label

ORDER = ["ACCUMULATION", "WASH", "LAUNCH", "DISTRIBUTION"]

KLINE_BARS = 100  # 每只股票保留的最近交易日数

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
 background:#f5f6f8;color:#1f2328;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1360px;margin:0 auto;padding:26px 20px 70px}
.hd{background:linear-gradient(135deg,#1e3a5f,#2c5282);color:#fff;border-radius:14px;
 padding:30px 34px;margin-bottom:20px;box-shadow:0 8px 24px rgba(30,58,95,.16)}
.hd h1{font-size:25px;font-weight:660;letter-spacing:.4px}
.hd .sub{opacity:.9;font-size:13.5px;margin-top:7px}
.hd-meta{display:flex;flex-wrap:wrap;gap:20px;margin-top:17px;font-size:12.5px;opacity:.93}
.hd-meta b{font-weight:600}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.st{background:#fff;border:1px solid #e6e9ef;border-radius:11px;padding:15px 17px;
 box-shadow:0 1px 3px rgba(16,24,40,.04)}
.st .lb{font-size:12px;color:#6b7280;display:flex;align-items:center;gap:6px}
.st .vl{font-size:26px;font-weight:680;margin-top:3px;font-variant-numeric:tabular-nums}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
/* ---- 首页关注榜 ---- */
.topgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.topbox{background:#fff;border:1px solid #e6e9ef;border-radius:12px;overflow:hidden;
 box-shadow:0 1px 3px rgba(16,24,40,.04)}
.top-hd{padding:12px 17px;border-bottom:1px solid #eef0f4;font-size:14.5px;font-weight:640;
 display:flex;align-items:center;gap:8px}
.top-hd .ic{width:22px;height:22px;border-radius:6px;color:#fff;display:inline-flex;
 align-items:center;justify-content:center;font-size:12.5px;font-weight:700}
.top-sub{font-size:11.5px;color:#9ca3af;font-weight:400;margin-left:auto}
.topbody{padding:6px 0}
.trow{display:flex;align-items:center;gap:10px;padding:9px 17px;cursor:pointer;transition:.12s}
.trow:hover{background:#fafbfc}
.trow .rk{width:20px;height:20px;border-radius:50%;background:#f3f4f6;color:#6b7280;
 font-size:11.5px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0}
.trow .rk.hot{background:#c62828;color:#fff}
.trow .rk.cold{background:#2e7d32;color:#fff}
.tn{font-size:13.5px;font-weight:620;white-space:nowrap}
.tcd{font-size:11px;color:#9ca3af;font-weight:400}
.tind{font-size:11px;color:#b0b7c3;white-space:nowrap}
.tpx{margin-left:auto;font-size:13px;font-weight:620;font-variant-numeric:tabular-nums;white-space:nowrap}
.tsc{font-size:11.5px;color:#6b7280;font-variant-numeric:tabular-nums;white-space:nowrap}
.tact{font-size:11.5px;font-weight:600;white-space:nowrap}
.bar-wrap{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin-bottom:18px;
 background:#fff;border:1px solid #e6e9ef;border-radius:11px;padding:14px 17px}
.btn{border:1px solid #d8dde5;background:#fff;border-radius:7px;padding:6px 14px;font-size:13px;
 cursor:pointer;color:#374151;transition:.15s;font-family:inherit}
.btn:hover{border-color:#2c5282;color:#2c5282}
.btn.on{background:#2c5282;color:#fff;border-color:#2c5282}
.inp{border:1px solid #d8dde5;border-radius:7px;padding:6px 12px;font-size:13px;
 font-family:inherit;outline:none;min-width:150px}
.inp:focus{border-color:#2c5282}
.sep{width:1px;height:22px;background:#e3e7ed;margin:0 4px}
.hint{font-size:12px;color:#9ca3af;margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(410px,1fr));gap:16px}
.ind{background:#fff;border:1px solid #e6e9ef;border-radius:12px;overflow:hidden;
 box-shadow:0 1px 3px rgba(16,24,40,.04)}
.ind-hd{padding:13px 17px;border-bottom:1px solid #eef0f4;display:flex;
 justify-content:space-between;align-items:center;gap:10px;background:#fafbfc}
.ind-nm{font-size:15.5px;font-weight:640}
.ind-sub{font-size:11.5px;color:#9ca3af;margin-top:1px}
.ind-rt{text-align:right;font-size:12px;flex-shrink:0}
.up{color:#c62828;font-weight:600}.dn{color:#2e7d32;font-weight:600}
.lr{border-bottom:1px solid #f2f4f7;padding:12px 17px;cursor:pointer;transition:.12s}
.lr:last-child{border-bottom:none}
.lr:hover{background:#fafbfc}
.lr-t{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.nm{font-size:14.5px;font-weight:620}
.cd{font-size:11.5px;color:#9ca3af;font-weight:400;margin-left:4px}
.bg{display:inline-block;padding:2.5px 10px;border-radius:12px;color:#fff;font-size:11.5px;font-weight:600}
.sc{font-size:12.5px;color:#6b7280;font-variant-numeric:tabular-nums}
.px{margin-left:auto;font-size:13.5px;font-weight:620;font-variant-numeric:tabular-nums}
.lr-b{display:flex;align-items:center;gap:14px;margin-top:8px}
.mt{flex:1;min-width:0}
.mt-l{display:flex;justify-content:space-between;font-size:11px;color:#9ca3af;margin-bottom:2px}
.tr{height:5px;background:#eef0f4;border-radius:3px;overflow:hidden}
.fl{height:100%;border-radius:3px}
.act{font-size:12px;font-weight:600;flex-shrink:0;text-align:right;min-width:62px}
.evi{font-size:11.5px;padding:3px 8px;border-radius:5px;background:#f3f4f6;color:#4b5563}
.evi.y{background:#fef2f2;color:#b91c1c}
.evi.n{background:#f9fafb;color:#9ca3af}
.evwrap{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.evd{font-size:12.5px;color:#6b7280;margin-top:9px;line-height:1.75}
/* ---- K线弹窗 ---- */
.mov{display:none;position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:50;
 align-items:flex-start;justify-content:center;padding:4vh 12px;overflow-y:auto}
.mov.on{display:flex}
.mpanel{background:#fff;border-radius:14px;max-width:980px;width:100%;
 box-shadow:0 24px 64px rgba(15,23,42,.28);overflow:hidden}
.m-hd{padding:15px 20px;border-bottom:1px solid #eef0f4;display:flex;align-items:center;
 gap:10px;flex-wrap:wrap;background:#fafbfc}
.m-hd .nm{font-size:17px}
.m-hd .indlab{font-size:12px;color:#9ca3af}
.mclose{margin-left:auto;border:1px solid #d8dde5;background:#fff;border-radius:8px;
 width:30px;height:30px;font-size:15px;cursor:pointer;color:#6b7280;line-height:1}
.mclose:hover{border-color:#c62828;color:#c62828}
.m-body{padding:16px 20px 22px}
.m-sec{font-size:12px;color:#9ca3af;margin:16px 0 6px}
.kwrap{position:relative;border:1px solid #eef0f4;border-radius:10px;padding:8px 6px 4px;
 background:#fff}
.klegend{display:flex;gap:14px;font-size:11px;color:#6b7280;padding:2px 8px 6px;flex-wrap:wrap}
.klegend b{font-weight:600}
.ktip{position:absolute;top:12px;left:0;display:none;background:rgba(255,255,255,.97);
 border:1px solid #e3e7ed;border-radius:8px;padding:7px 11px;font-size:11.5px;
 line-height:1.7;box-shadow:0 6px 18px rgba(16,24,40,.12);pointer-events:none;
 white-space:nowrap;z-index:5;font-variant-numeric:tabular-nums}
.ktip b{font-weight:620}
.stgbar{display:flex;align-items:center;gap:7px;margin-bottom:4px}
.stgbar span.lb{width:46px;font-size:11px;color:#9ca3af;flex-shrink:0}
.stgbar .tr{flex:1}
.stgbar span.vv{width:30px;text-align:right;font-size:11.5px;font-weight:600}
.ft{margin-top:32px;padding:18px 22px;background:#fff;border:1px solid #e6e9ef;
 border-radius:12px;font-size:12px;color:#6b7280;line-height:1.8}
.empty{text-align:center;padding:50px;color:#9ca3af;background:#fff;
 border:1px solid #e6e9ef;border-radius:12px}
@media(max-width:900px){.topgrid{grid-template-columns:1fr}}
@media(max-width:640px){.grid{grid-template-columns:1fr}.hd{padding:22px}.wrap{padding:16px 12px 50px}}
"""

JS = """
var DATA = __DATA__;
var ORDER = ["ACCUMULATION","WASH","LAUNCH","DISTRIBUTION"];
var META = DATA.meta;
var fStage = 'ALL', fSort = 'opp', fKey = '';

function el(id){return document.getElementById(id);}
function cls(v){return v>0?'up':(v<0?'dn':'');}
function sgn(v,d){if(v===null||v===undefined)return '-';return (v>0?'+':'')+v.toFixed(d===undefined?2:d);}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}

function scoreBar(lb, val, color){
  return '<div class="mt"><div class="mt-l"><span>'+lb+'</span><span>'+val+'</span></div>'+
    '<div class="tr"><div class="fl" style="width:'+Math.max(val,2)+'%;background:'+color+'"></div></div></div>';
}

/* ---------- 首页关注榜 ---------- */
function flatten(){
  var out=[];
  DATA.industries.forEach(function(ind){
    ind.leaders.forEach(function(L){ out.push({L:L, ind:ind.label}); });
  });
  return out;
}

function topRow(x, i, kind){
  var L = x.L, m = META[L.stage];
  var rkCls = i===0 ? (kind==='buy'?'hot':'cold') : '';
  return '<div class="trow" onclick="openModal(\\''+L.code+'\\')">'+
    '<span class="rk '+rkCls+'">'+(i+1)+'</span>'+
    '<span class="tn">'+L.name+' <span class="tcd">'+L.code+'</span></span>'+
    '<span class="tind">'+x.ind+'</span>'+
    '<span class="bg" style="background:'+m.color+'">'+m.name+'</span>'+
    '<span class="tsc">'+Math.round(L.score)+'分 · 机会'+L.opportunity+' / 风险'+L.risk+'</span>'+
    '<span class="px '+cls(L.chg)+'">'+L.price.toFixed(2)+'</span>'+
    '<span class="tact" style="color:'+L.tone+'">'+L.action+'</span></div>';
}

function renderTop(){
  var all = flatten();
  // 买入榜：机会分优先，风险过高(<60分安全线以下)剔除；不足则放宽
  var buys = all.filter(function(x){return x.L.risk<60;})
    .sort(function(a,b){return b.L.opportunity-a.L.opportunity;}).slice(0,5);
  if(buys.length<3){
    buys = all.slice().sort(function(a,b){return b.L.opportunity-a.L.opportunity;}).slice(0,5);
  }
  // 卖出榜：撤离期优先，其次按风险分
  var sells = all.slice().sort(function(a,b){
    var da=a.L.stage==='DISTRIBUTION'?1:0, db=b.L.stage==='DISTRIBUTION'?1:0;
    if(db!==da) return db-da;
    return b.L.risk-a.L.risk;
  }).slice(0,5);
  el('buybody').innerHTML = buys.map(function(x,i){return topRow(x,i,'buy');}).join('') ||
    '<div style="padding:18px;color:#9ca3af;font-size:12.5px">暂无候选</div>';
  el('sellbody').innerHTML = sells.map(function(x,i){return topRow(x,i,'sell');}).join('') ||
    '<div style="padding:18px;color:#9ca3af;font-size:12.5px">暂无候选</div>';
}

/* ---------- 行业网格 ---------- */
function render(){
  var kw = fKey.trim().toLowerCase();
  var cards = DATA.industries.map(function(ind){
    var ls = ind.leaders.filter(function(L){
      if(fStage!=='ALL' && L.stage!==fStage) return false;
      if(kw && (L.name+L.code+ind.label).toLowerCase().indexOf(kw)<0) return false;
      return true;
    });
    if(!ls.length) return '';
    if(fSort==='opp') ls.sort(function(a,b){return b.opportunity-a.opportunity;});
    else if(fSort==='risk') ls.sort(function(a,b){return b.risk-a.risk;});
    else if(fSort==='score') ls.sort(function(a,b){return b.score-a.score;});
    else if(fSort==='chg') ls.sort(function(a,b){return (b.chg||0)-(a.chg||0);});

    var rows = ls.map(function(L){
      var m = META[L.stage];
      return '<div class="lr" onclick="openModal(\\'' + L.code + '\\')">'+
        '<div class="lr-t"><span class="nm">'+L.name+'<span class="cd">'+L.code+'</span></span>'+
        '<span class="bg" style="background:'+m.color+'">'+m.name+'</span>'+
        '<span class="sc">'+Math.round(L.score)+'\\u5206</span>'+
        '<span class="px '+cls(L.chg)+'">'+L.price.toFixed(2)+' <span style="font-size:11.5px">'+sgn(L.chg)+'%</span></span></div>'+
        '<div class="lr-b">'+ scoreBar('\\u673a\\u4f1a', L.opportunity, '#c62828') +
          scoreBar('\\u98ce\\u9669', L.risk, '#6b7280') +
          '<span class="act" style="color:'+L.tone+'">'+L.action+'</span></div></div>';
    }).join('');

    return '<div class="ind"><div class="ind-hd"><div>'+
      '<div class="ind-nm">'+ind.label+'</div>'+
      '<div class="ind-sub">'+ind.board_name+' \\u00b7 '+ind.member_count+'\\u53ea\\u6210\\u5206\\u80a1</div></div>'+
      '<div class="ind-rt"><div class="'+cls(ind.chg)+'">'+sgn(ind.chg)+'%</div>'+
      '<div style="color:#9ca3af;font-size:11px;margin-top:2px">\\u4e3b\\u529b '+
      (ind.main_net>0?'+':'')+ind.main_net.toFixed(1)+'\\u4ebf</div></div></div>'+
      rows+'</div>';
  }).filter(Boolean).join('');

  el('grid').innerHTML = cards || '<div class="empty">\\u6ca1\\u6709\\u7b26\\u5408\\u7b5b\\u9009\\u6761\\u4ef6\\u7684\\u6807\\u7684</div>';
}

function setF(v,f){
  if(f==='stage') fStage=v;
  else if(f==='sort') fSort=v;
  document.querySelectorAll('[data-f]').forEach(function(b){
    b.classList.toggle('on', b.dataset.f===f && b.dataset.v===(f==='stage'?fStage:fSort));
  });
  render();
}
document.querySelectorAll('[data-f]').forEach(function(b){
  b.onclick=function(){setF(b.dataset.v,b.dataset.f);};
});
el('kw').oninput=function(){fKey=this.value;render();};

/* ---------- K线 + 成交量图（纯 SVG，可交互） ---------- */
function fmtVol(v){
  if(v>=1e8) return (v/1e8).toFixed(2)+'亿手';
  if(v>=1e4) return (v/1e4).toFixed(1)+'万手';
  return Math.round(v)+'手';
}
function fmtAmt(a){
  if(a>=1e8) return (a/1e8).toFixed(2)+'亿';
  if(a>=1e4) return (a/1e4).toFixed(1)+'万';
  return String(Math.round(a));
}

var CHART = {};   // 每只股票的图数据缓存（供 mousemove 用）

function drawK(container, code){
  var kd = (typeof KDATA!=='undefined') && KDATA && KDATA[code];
  if(!kd || kd.length<3){
    container.innerHTML = '<div class="empty" style="padding:30px">暂无K线数据</div>';
    return;
  }
  var bars = kd.slice(-100);
  var n = bars.length;
  var W = 880, H = 330;
  var padL = 6, padR = 58, padT = 12;
  var priceH = 210, gap = 24;
  var volTop = padT + priceH + gap, volH = H - volTop - 24;
  var step = (W - padL - padR) / n;
  var cw = Math.max(1.3, step*0.66);

  var closes = bars.map(function(b){return b[2];});
  function ma(idx, p){
    if(idx < p-1) return null;
    var s=0; for(var i=idx-p+1;i<=idx;i++) s+=closes[i];
    return s/p;
  }
  var hi = -Infinity, lo = Infinity, vmax = 0;
  for(var i=0;i<n;i++){
    hi = Math.max(hi, bars[i][3]); lo = Math.min(lo, bars[i][4]);
    vmax = Math.max(vmax, bars[i][5]);
    [5,10,20].forEach(function(p){var m=ma(i,p); if(m!==null){hi=Math.max(hi,m);lo=Math.min(lo,m);}});
  }
  var padP = (hi-lo)*0.07 || 0.1; hi+=padP; lo-=padP;
  function Y(p){ return padT + (hi-p)/(hi-lo)*priceH; }
  function X(i){ return padL + step*i + step/2; }

  var s = '';
  // 价格网格与刻度
  for(var t=0;t<=4;t++){
    var p = lo + (hi-lo)*t/4, y = Y(p);
    s += '<line x1="'+padL+'" y1="'+y.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+y.toFixed(1)+'" stroke="#eef0f4"/>';
    s += '<text x="'+(W-padR+6)+'" y="'+(y+4).toFixed(1)+'" font-size="10.5" fill="#9ca3af">'+p.toFixed(2)+'</text>';
  }
  s += '<line x1="'+padL+'" y1="'+volTop+'" x2="'+(W-padR)+'" y2="'+volTop+'" stroke="#eef0f4"/>';
  s += '<text x="'+padL+'" y="'+(volTop+11)+'" font-size="10" fill="#9ca3af">量 '+fmtVol(vmax)+'</text>';
  // K线 + 成交量
  for(var i=0;i<n;i++){
    var b = bars[i], up = b[2]>=b[1], col = up ? '#c62828' : '#2e7d32';
    var x = X(i).toFixed(1);
    s += '<line x1="'+x+'" y1="'+Y(b[3]).toFixed(1)+'" x2="'+x+'" y2="'+Y(b[4]).toFixed(1)+'" stroke="'+col+'" stroke-width="1"/>';
    var y1 = Y(Math.max(b[1],b[2])), y2 = Y(Math.min(b[1],b[2]));
    s += '<rect x="'+(X(i)-cw/2).toFixed(1)+'" y="'+y1.toFixed(1)+'" width="'+cw.toFixed(1)+'" height="'+Math.max(1,y2-y1).toFixed(1)+'" fill="'+col+'"/>';
    var vy = volTop + volH - (vmax ? b[5]/vmax*volH : 0);
    s += '<rect x="'+(X(i)-cw/2).toFixed(1)+'" y="'+vy.toFixed(1)+'" width="'+cw.toFixed(1)+'" height="'+(volTop+volH-vy).toFixed(1)+'" fill="'+col+'" opacity="0.72"/>';
  }
  // 均线
  var maCols = {5:'#f59e0b',10:'#6366f1',20:'#10b981'};
  [5,10,20].forEach(function(p){
    var pts=[];
    for(var i=0;i<n;i++){var m=ma(i,p); if(m!==null) pts.push(X(i).toFixed(1)+','+Y(m).toFixed(1));}
    if(pts.length>1) s += '<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+maCols[p]+'" stroke-width="1.2" opacity="0.92"/>';
  });
  // 日期刻度
  var tick = Math.max(1, Math.ceil(n/7));
  for(var i=0;i<n;i+=tick){
    s += '<text x="'+X(i).toFixed(1)+'" y="'+(H-7)+'" font-size="10" fill="#9ca3af" text-anchor="middle">'+bars[i][0].slice(5)+'</text>';
  }
  // 十字光标
  s += '<line id="kch_'+code+'" x1="0" y1="'+padT+'" x2="0" y2="'+(volTop+volH)+'" stroke="#94a3b8" stroke-dasharray="3,3" visibility="hidden"/>';

  container.innerHTML =
    '<div class="klegend"><b>最近 '+n+' 个交易日（红涨绿跌）</b>'+
    '<span style="color:#f59e0b">— MA5</span><span style="color:#6366f1">— MA10</span>'+
    '<span style="color:#10b981">— MA20</span>'+
    '<span style="margin-left:auto;color:#9ca3af">鼠标悬停查看每日价格与成交量</span></div>'+
    '<div style="position:relative">'+
    '<svg id="ksvg_'+code+'" width="100%" viewBox="0 0 '+W+' '+H+'" style="display:block">'+s+'</svg>'+
    '<div class="ktip" id="ktip_'+code+'"></div></div>';

  CHART[code] = {bars:bars, n:n, W:W, padL:padL, step:step,
                 Y:Y, volTop:volTop, volH:volH, vmax:vmax};
  bindHover(code);
}

function bindHover(code){
  var svg = el('ksvg_'+code), tip = el('ktip_'+code), ch = el('kch_'+code);
  var C = CHART[code];
  if(!svg || !C) return;
  svg.onmousemove = function(ev){
    var rect = svg.getBoundingClientRect();
    var sx = (ev.clientX - rect.left) * (C.W / rect.width);
    var idx = Math.floor((sx - C.padL) / C.step);
    if(idx < 0) idx = 0;
    if(idx >= C.n) idx = C.n - 1;
    var b = C.bars[idx];
    var xc = (C.padL + C.step*idx + C.step/2) / C.W * rect.width;
    ch.setAttribute('x1', (C.padL + C.step*idx + C.step/2).toFixed(1));
    ch.setAttribute('x2', (C.padL + C.step*idx + C.step/2).toFixed(1));
    ch.setAttribute('visibility','visible');
    var up = b[2]>=b[1];
    tip.innerHTML =
      '<b>'+b[0]+'</b><br/>'+
      '开盘 '+b[1].toFixed(2)+'　收盘 <b style="color:'+(up?'#c62828':'#2e7d32')+'">'+b[2].toFixed(2)+'</b><br/>'+
      '最高 '+b[3].toFixed(2)+'　最低 '+b[4].toFixed(2)+'<br/>'+
      '涨跌 <b style="color:'+(up?'#c62828':'#2e7d32')+'">'+sgn(b[7])+'%</b>　换手 '+(b[8]!==undefined&&b[8]!==null?b[8].toFixed(2)+'%':'-')+'<br/>'+
      '成交量 <b>'+fmtVol(b[5])+'</b>　成交额 '+fmtAmt(b[6]);
    tip.style.display = 'block';
    tip.style.left = (xc + 16 > rect.width - 200) ? (xc - 186)+'px' : (xc + 14)+'px';
  };
  svg.onmouseleave = function(){
    tip.style.display = 'none';
    ch.setAttribute('visibility','hidden');
  };
}

/* ---------- 详情弹窗 ---------- */
function openModal(code){
  var L = null, indLabel = '';
  for(var i=0;i<DATA.industries.length;i++){
    var ls = DATA.industries[i].leaders;
    for(var j=0;j<ls.length;j++){
      if(ls[j].code===code){ L=ls[j]; indLabel=DATA.industries[i].label; break; }
    }
    if(L) break;
  }
  if(!L) return;
  var m = META[L.stage];
  el('m_name').innerHTML = L.name+'<span class="cd">'+L.code+'</span>';
  el('m_ind').textContent = indLabel;
  el('m_badge').style.background = m.color;
  el('m_badge').textContent = m.name;
  el('m_score').textContent = Math.round(L.score)+'分 · 置信'+L.conf_label;
  el('m_px').innerHTML = '<span class="'+cls(L.chg)+'">'+L.price.toFixed(2)+'  '+sgn(L.chg)+'%</span>';
  el('m_act').innerHTML = '<span style="color:'+L.tone+';font-weight:620">'+L.action+'</span>'+
    '　机会 '+L.opportunity+' / 风险 '+L.risk;

  drawK(el('m_chart'), code);

  var sc = L.scores||{};
  var bars = ORDER.map(function(st){
    return '<div class="stgbar"><span class="lb">'+META[st].name+'</span>'+
      '<div class="tr"><div class="fl" style="width:'+Math.max(sc[st]||0,1.5)+'%;background:'+META[st].color+'"></div></div>'+
      '<span class="vv">'+Math.round(sc[st]||0)+'</span></div>';
  }).join('');
  var evs = (L.evidence||[]).map(function(e){
    return e.hit ? '<span class="evi y">\\u2713 '+e.label+'</span>'
                 : '<span class="evi n">\\u2717 '+e.label+'</span>';
  }).join('');
  el('m_detail').innerHTML =
    '<div class="m-sec">四阶段得分</div>'+bars+
    '<div class="m-sec">证据链</div><div class="evwrap">'+evs+'</div>'+
    '<div class="evd">'+(L.reason||'')+'</div>';
  el('modal').classList.add('on');
  document.body.style.overflow = 'hidden';
}
function closeModal(){
  el('modal').classList.remove('on');
  document.body.style.overflow = '';
}
el('mclose').onclick = closeModal;
el('modal').onclick = function(ev){ if(ev.target===this) closeModal(); };
document.addEventListener('keydown', function(ev){ if(ev.key==='Escape') closeModal(); });

renderTop();
render();
"""

CSS = CSS  # placeholder to keep linters calm


def _evidences(res) -> List[Dict]:
    out = []
    for e in res.evidences[res.stage]:
        if e.hit is None:
            continue
        out.append({"label": e.label, "hit": bool(e.hit), "desc": e.desc})
    return out


def build_payload(universe: List[Dict], analyses: Dict[str, Dict],
                  as_of: str) -> Dict:
    """把行业清单 + 分析结果组装成网站数据。"""
    industries = []
    stage_count = {s: 0 for s in ORDER}
    total = 0

    for ind in universe:
        leaders = []
        for m in ind["leaders"]:
            a = analyses.get(m["code"])
            if not a:
                continue
            res = a["result"]
            F = a["features"]
            act = action_scores(F, res)
            stage_count[res.stage] = stage_count.get(res.stage, 0) + 1
            total += 1
            leaders.append({
                "code": a["code"],
                "name": a["name"],
                "price": F.get("price") or 0,
                "chg": m.get("chg") or 0,
                "turnover": F.get("turnover5"),
                "mktcap": m.get("mktcap"),
                "leader_score": m.get("leader_score"),
                "stage": res.stage,
                "stage_name": res.stage and STAGE_META[res.stage]["name"],
                "score": res.score,
                "scores": {k: round(v) for k, v in res.scores.items()},
                "confidence": res.confidence,
                "conf_label": confidence_label(res.confidence),
                "opportunity": act["opportunity"],
                "risk": act["risk"],
                "action": act["action"],
                "tone": act["tone"],
                "reason": act["reason"],
                "evidence": _evidences(res),
            })
        if leaders:
            industries.append({
                "label": ind["label"],
                "board": ind["board"],
                "board_name": ind["board_name"],
                "chg": ind.get("chg") or 0,
                "main_net": round(ind.get("main_net") or 0, 2),
                "member_count": ind.get("member_count", 0),
                "leaders": leaders,
            })

    return {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "as_of": as_of,
        "industry_count": len(industries),
        "leader_count": total,
        "stage_count": stage_count,
        "industries": industries,
    }


def build_kdata(analyses: Dict[str, Dict], bars: int = KLINE_BARS) -> Dict:
    """从分析结果提取每只股票的最近日线量价数据，供 K 线图使用。

    每根K线: [日期, 开, 收, 高, 低, 成交量(手), 成交额(元), 涨跌幅%, 换手率%]
    """
    out: Dict[str, List] = {}
    for code, a in analyses.items():
        raw = a.get("kline_raw") or []
        if len(raw) < 3:
            continue
        rows = []
        for b in raw[-bars:]:
            try:
                rows.append([
                    b["date"],
                    round(float(b["open"]), 2),
                    round(float(b["close"]), 2),
                    round(float(b["high"]), 2),
                    round(float(b["low"]), 2),
                    round(float(b["volume"])),
                    round(float(b["amount"])),
                    round(float(b.get("chg", 0)), 2),
                    round(float(b.get("turnover", 0)), 2),
                ])
            except (KeyError, TypeError, ValueError):
                continue
        if rows:
            out[code] = rows
    return out


def render_site(payload: Dict) -> str:
    """渲染 index.html。"""
    meta = {k: {"name": v["name"], "color": v["color"]} for k, v in STAGE_META.items()}
    data_json = json.dumps(
        {"meta": meta, "industries": payload["industries"]},
        ensure_ascii=False)
    data_json = (data_json.replace("</", "<\\/"))

    st = payload["stage_count"]
    stat_cards = "".join(
        f'<div class="st"><div class="lb"><span class="dot" '
        f'style="background:{STAGE_META[s]["color"]}"></span>{STAGE_META[s]["name"]}</div>'
        f'<div class="vl" style="color:{STAGE_META[s]["color"]}">{st.get(s,0)}</div></div>'
        for s in ORDER)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>行业龙头 · 每日阶段评分看板</title>
<style>{CSS}</style></head><body><div class="wrap">
<div class="hd">
  <h1>行业龙头 · 每日阶段评分看板</h1>
  <div class="sub">按行业追踪龙头企业，每日更新机构行为阶段判定与操作评分
       （建仓 → 洗盘 → 启动 → 撤离）</div>
  <div class="hd-meta">
    <span><b>更新时间</b> {payload['updated']}</span>
    <span><b>数据基准日</b> {payload['as_of']}</span>
    <span><b>覆盖行业</b> {payload['industry_count']} 个</span>
    <span><b>龙头标的</b> {payload['leader_count']} 只</span>
    <span><b>数据源</b> 东方财富 / 腾讯 / 新浪</span>
  </div>
</div>
<div class="stats">
  <div class="st"><div class="lb">追踪龙头总数</div>
    <div class="vl">{payload['leader_count']}</div></div>
  {stat_cards}
</div>
<div class="topgrid">
  <div class="topbox">
    <div class="top-hd"><span class="ic" style="background:#c62828">买</span>
      近期最值得关注买入
      <span class="top-sub">按机会分排序 · 已剔除高风险标的</span></div>
    <div class="topbody" id="buybody"></div>
  </div>
  <div class="topbox">
    <div class="top-hd"><span class="ic" style="background:#2e7d32">卖</span>
      最值得卖出 / 撤离
      <span class="top-sub">撤离期优先 · 其余按风险分排序</span></div>
    <div class="topbody" id="sellbody"></div>
  </div>
</div>
<div class="bar-wrap">
  <button class="btn on" data-f="stage" data-v="ALL">全部阶段</button>
  <button class="btn" data-f="stage" data-v="ACCUMULATION">建仓期</button>
  <button class="btn" data-f="stage" data-v="WASH">洗盘期</button>
  <button class="btn" data-f="stage" data-v="LAUNCH">启动期</button>
  <button class="btn" data-f="stage" data-v="DISTRIBUTION">撤离期</button>
  <div class="sep"></div>
  <button class="btn on" data-f="sort" data-v="opp">按机会分</button>
  <button class="btn" data-f="sort" data-v="risk">按风险分</button>
  <button class="btn" data-f="sort" data-v="score">按阶段分</button>
  <button class="btn" data-f="sort" data-v="chg">按涨幅</button>
  <div class="sep"></div>
  <input class="inp" id="kw" placeholder="搜索行业 / 股票名称">
  <span class="hint">共 {payload['leader_count']} 只 · 点击任一行查看K线图、成交量与证据链</span>
</div>
<div class="grid" id="grid"></div>
<div class="ft">
<b>阶段判定</b>：由量价、资金、筹码、形态四维指标加权打分得出，
每只标的输出四阶段得分，取最高分为判定结果；
置信度 = 最高分 − 次高分，差值小说明处于阶段切换的模糊带。<br/>
<b>机会分</b>：值不值得介入（越高越好）；<b>风险分</b>：危险程度（越高越危险）。
两者正交 —— 一只票可能同时高机会、高风险，这类标的需格外注意仓位。<br/>
<b>买入榜</b>：全行业按机会分降序取前 5，已剔除风险分 ≥ 60 的高危标的；
<b>卖出榜</b>：撤离期标的优先，其余按风险分降序取前 5。
两榜均为模型自动筛选，<b>买入榜 ≠ 推荐立刻买入</b>，仍需结合K线确认关键位。<br/>
<b>K线图</b>：点击任意标的弹出最近 {KLINE_BARS} 个交易日K线与成交量，
悬停可查看每日开高低收、涨跌幅、换手率与量额（红涨绿跌）。<br/>
<b>龙头选取</b>：每个行业按「市值排名 40% + 主力资金排名 35% + 涨幅排名 25%」加权，
取前 3 只。用排名分位而非绝对值，避免行业体量差异造成扭曲。<br/>
<b>操作建议</b>：风险分≥65 减仓离场；≥50 谨慎持有；机会分≥65 且风险&lt;45 重点介入；
机会分≥55 且风险&lt;50 逢低关注；否则跟踪观望。<br/><br/>
<b>免责声明</b>：本看板由量化模型自动生成，基于公开数据与历史统计规律，
<b>仅供研究参考，不构成任何投资建议</b>，过往规律不预示未来走势。
股市有风险，投资需谨慎，决策请结合自身风险承受能力独立判断。
</div>
<div class="mov" id="modal"><div class="mpanel">
  <div class="m-hd">
    <span class="nm" id="m_name"></span>
    <span class="indlab" id="m_ind"></span>
    <span class="bg" id="m_badge"></span>
    <span class="sc" id="m_score"></span>
    <span class="px" id="m_px"></span>
    <span class="act" id="m_act" style="min-width:0"></span>
    <button class="mclose" id="mclose">✕</button>
  </div>
  <div class="m-body">
    <div id="m_chart"></div>
    <div id="m_detail"></div>
  </div>
</div></div>
</div>
<script src="klines.js"></script>
<script>
{JS.replace('__DATA__', data_json)}
</script>
</body></html>"""


def generate(universe: List[Dict], analyses: Dict[str, Dict], as_of: str,
             out_dir: str = "site") -> str:
    """生成站点文件，返回 index.html 路径。"""
    os.makedirs(out_dir, exist_ok=True)
    payload = build_payload(universe, analyses, as_of)

    html = render_site(payload)
    idx = os.path.join(out_dir, "index.html")
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)

    # K线量价数据独立成 js 文件：file:// 协议下经典 <script> 无跨域限制，
    # 且让 index.html 保持轻量、K线数据可独立更新。
    kdata = build_kdata(analyses)
    with open(os.path.join(out_dir, "klines.js"), "w", encoding="utf-8") as f:
        f.write("/* 自动生成：个股最近%d个交易日K线量价数据 */\n" % KLINE_BARS)
        f.write("var KDATA = ")
        f.write(json.dumps(kdata, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")

    # 完整数据落盘，供后续时间序列分析或对接其他前端
    payload_full = dict(payload)
    payload_full["meta"] = {k: {"name": v["name"], "color": v["color"]}
                            for k, v in STAGE_META.items()}
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload_full, f, ensure_ascii=False, indent=1, default=str)

    return idx
