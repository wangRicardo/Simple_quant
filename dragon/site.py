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
/* ---- 头部即时查询框 ---- */
.qbox{display:flex;align-items:center;gap:10px;margin-top:18px;flex-wrap:wrap}
.qbox input{flex:1;min-width:230px;max-width:420px;border:1px solid rgba(255,255,255,.35);
 background:rgba(255,255,255,.12);border-radius:9px;padding:10px 15px;font-size:14px;
 color:#fff;outline:none;font-family:inherit;transition:.15s}
.qbox input::placeholder{color:rgba(255,255,255,.62)}
.qbox input:focus{background:rgba(255,255,255,.2);border-color:rgba(255,255,255,.72)}
.qbox button{border:none;background:#fff;color:#1e3a5f;border-radius:9px;padding:10px 22px;
 font-size:14px;font-weight:640;cursor:pointer;font-family:inherit;transition:.15s;flex-shrink:0}
.qbox button:hover{background:#e8effa}
.qbox .qhint{font-size:11.5px;color:rgba(255,255,255,.78);flex:1;min-width:220px;line-height:1.5}
.evi i{font-style:normal;opacity:.72;margin-left:5px;font-size:10.5px}
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
function renderLeaderModal(L, indLabel){
  var m = META[L.stage];
  el('m_name').innerHTML = L.name+'<span class="cd">'+L.code+'</span>';
  el('m_ind').textContent = indLabel;
  el('m_badge').style.background = m.color;
  el('m_badge').textContent = m.name;
  el('m_score').textContent = Math.round(L.score)+'分 · 置信'+L.conf_label;
  el('m_px').innerHTML = '<span class="'+cls(L.chg)+'">'+L.price.toFixed(2)+'  '+sgn(L.chg)+'%</span>';
  el('m_act').innerHTML = '<span style="color:'+L.tone+';font-weight:620">'+L.action+'</span>'+
    '　机会 '+L.opportunity+' / 风险 '+L.risk;

  drawK(el('m_chart'), L.code);

  var sc = L.scores||{};
  var bars = ORDER.map(function(st){
    return '<div class="stgbar"><span class="lb">'+META[st].name+'</span>'+
      '<div class="tr"><div class="fl" style="width:'+Math.max(sc[st]||0,1.5)+'%;background:'+META[st].color+'"></div></div>'+
      '<span class="vv">'+Math.round(sc[st]||0)+'</span></div>';
  }).join('');
  var evs = (L.evidence||[]).map(function(e){
    var d = e.desc ? '<i>'+esc(e.desc)+'</i>' : '';
    return e.hit ? '<span class="evi y">\\u2713 '+e.label+d+'</span>'
                 : '<span class="evi n">\\u2717 '+e.label+d+'</span>';
  }).join('');
  el('m_detail').innerHTML =
    '<div class="m-sec">四阶段得分</div>'+bars+
    '<div class="m-sec">证据链</div><div class="evwrap">'+evs+'</div>'+
    '<div class="evd">'+(L.reason||'')+'</div>';
  el('modal').classList.add('on');
  document.body.style.overflow = 'hidden';
}
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
  renderLeaderModal(L, indLabel);
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

# 即时查询引擎：浏览器端 JSONP 取数 + 四阶段打分卡 JS 移植。
# 原理：GitHub Pages 为纯静态站，无后端 API。页面通过 <script> 标签直接向
# 行情服务器取数（JSONP 免 CORS），随后在本页现场计算特征与阶段评分。
# 数据源与后端 Python 一致：东财 push2his K线（push2delay 兜底 → 腾讯行情再兜底）、
# 东财 fflow 资金流（push2 / push2delay 兜底，取不到则相关规则自动降权）。
# 打分卡为 dragon/stage.py 的移植快照；后端阈值调整后需同步本文件（VERSION 标注日期）。
QUERY_JS = r"""
var DQ = (function(){
'use strict';
var VERSION = '2026-09-11';

/* ---------- 基础工具（对应 stage.py 的 cmpf/and/or 语义） ---------- */
function num(v){ return (typeof v==='number'&&isFinite(v))?v:null; }
function cmp(v,op,t){ var x=num(v),y=num(t); if(x===null||y===null)return null;
  if(op==='>')return x>y; if(op==='>=')return x>=y; if(op==='<')return x<y; if(op==='<=')return x<=y; return null; }
function AND(a,b){ return a===true? b : a; }   /* Python `and` 短路语义 */
function OR(a,b){ return a===true? true : b; } /* Python `or` 短路语义 */
function mean(a){ if(!a||!a.length)return null; var s=0;for(var i=0;i<a.length;i++)s+=a[i];return s/a.length; }
function fnum(v,d){ if(v===null||v===undefined||isNaN(v))return '无'; return Number(v).toFixed(d===undefined?2:d); }
function cumsum(a){ var s=0,out=[]; for(var i=0;i<a.length;i++){s+=a[i];out.push(s);} return out; }

/* ---------- JSONP 加载器（script 标签，免 CORS） ---------- */
var CBSEQ=0;
function jsonp(url,timeout){
  return new Promise(function(resolve,reject){
    var name='__dqc'+(++CBSEQ)+'_'+Date.now();
    var s=document.createElement('script'); var settled=false;
    function cleanup(){ try{delete window[name];}catch(e){window[name]=undefined;}
      if(s.parentNode)s.parentNode.removeChild(s); }
    window[name]=function(data){ if(settled)return; settled=true; cleanup(); resolve(data); };
    s.src=url.replace('__CB__',name);
    s.onerror=function(){ if(settled)return; settled=true; cleanup(); reject(new Error('网络错误')); };
    setTimeout(function(){ if(!settled){settled=true;cleanup();reject(new Error('请求超时'));} }, timeout||9000);
    document.head.appendChild(s);
  });
}

/* ---------- 代码解析：600519 / sh600519 / SZ000001 / bj920xxx ---------- */
function resolveCode(raw){
  var s=String(raw||'').trim().toLowerCase();
  var m=s.match(/^(sh|sz|bj)?(\d{6})$/);
  if(!m)return null;
  var pfx=m[1], code=m[2];
  if(!pfx){
    if(/^(60|68|9)/.test(code))pfx='sh';
    else if(/^(43|83|87|82|92)/.test(code))pfx='bj';
    else pfx='sz';
  }
  return {code:code, sym:pfx+code, secid:(pfx==='sh'?1:0)+'.'+code};
}

/* ---------- 数据抓取（多源兜底，与后端 datasource.py 同源同参数） ---------- */
var EM_HIS=['https://push2his.eastmoney.com','https://push2delay.eastmoney.com'];
var EM_P2=['https://push2.eastmoney.com','https://push2delay.eastmoney.com'];

function fetchChain(hosts,build,validate){
  var i=0;
  function attempt(){
    if(i>=hosts.length)return Promise.reject(new Error('全部数据源失败'));
    var url=build(hosts[i++]);
    return jsonp(url).then(function(d){ if(!validate(d))throw new Error('empty'); return d; })
                     .catch(attempt);
  }
  return attempt();
}

function fetchEMKline(secid){
  return fetchChain(EM_HIS, function(h){
    return h+'/api/qt/stock/kline/get?cb=__CB__&secid='+secid+
      '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'+
      '&klt=101&fqt=1&beg=0&end=20500101&lmt=320';
  }, function(d){ return !!(d&&d.data&&d.data.klines&&d.data.klines.length>60); });
}

function fetchFflow(secid){
  return fetchChain(EM_P2, function(h){
    return h+'/api/qt/stock/fflow/daykline/get?cb=__CB__&lmt=120&klt=101&secid='+secid+
      '&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63';
  }, function(d){ return !!(d&&d.data&&d.data.klines&&d.data.klines.length); })
  .catch(function(){ return null; });   /* 资金流取不到 → 相关规则自动降权 */
}

function fetchTxKline(sym){
  return jsonp('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+
      sym+',day,,,320,qfq&_var=__CB__')
    .then(function(d){
      var node=d&&d.data&&d.data[sym]; if(!node)throw new Error('tx empty');
      var arr=node.qfqday||node.day||[]; if(arr.length<60)throw new Error('tx short');
      return arr;
    });
}

function fetchQqProfile(sym){
  return new Promise(function(resolve){
    var done=false;
    function finish(){ if(done)return; done=true;
      var v=window['v_'+sym], name=null, fc=null;
      if(typeof v==='string'){ var p=v.split('~');
        if(p.length>1)name=p[1];
        if(p.length>45){var x=parseFloat(p[44]); if(!isNaN(x))fc=x;}
      }
      resolve({name:name,float_cap:fc});
    }
    try{
      var s=document.createElement('script');
      s.src='https://qt.gtimg.cn/q='+sym+'&r='+Math.random();
      s.onload=finish; s.onerror=finish;
      setTimeout(finish,5000);
      document.head.appendChild(s);
    }catch(e){ finish(); }
  });
}

/* ---------- 解析（与 datasource.parse_kline / parse_fflow 同口径） ---------- */
function parseEMKline(raw){
  var d=raw.data, kline=[], kdata=[];
  for(var i=0;i<d.klines.length;i++){
    var p=d.klines[i].split(',');
    var b={date:p[0],open:+p[1],close:+p[2],high:+p[3],low:+p[4],volume:+p[5],
           amount:+p[6],amplitude:+p[7],chg:+p[8],chg_amt:+p[9],turnover:+p[10]};
    kline.push(b);
    kdata.push([b.date,b.open,b.close,b.high,b.low,Math.round(b.volume),
                Math.round(b.amount),+b.chg.toFixed(2),+b.turnover.toFixed(2)]);
  }
  return {name:d.name||'', kline:kline, kdata:kdata};
}

function parseTxKline(arr){
  var kline=[],kdata=[],prevClose=null;
  for(var i=0;i<arr.length;i++){
    var r=arr[i];
    var chg=prevClose? (+r[2]-prevClose)/prevClose*100 : 0;
    if(isNaN(chg))chg=0;
    var amt=(r.length>6&&!isNaN(parseFloat(r[6])))?+r[6]:null;
    var b={date:r[0],open:+r[1],close:+r[2],high:+r[3],low:+r[4],volume:+r[5],
           amount:amt,amplitude:null,chg:chg,chg_amt:null,turnover:null};
    kline.push(b);
    kdata.push([r[0],+r[1],+r[2],+r[3],+r[4],Math.round(+r[5]),amt||0,+chg.toFixed(2)]);
    prevClose=+r[2];
  }
  return {name:'', kline:kline, kdata:kdata};
}

function parseEMFflow(raw){
  var out=[],ks=(raw&&raw.data&&raw.data.klines)||[];
  function f(s){ return (s==='-'||s===''||s===undefined||s===null)?null:+s; }
  for(var i=0;i<ks.length;i++){
    var p=ks[i].split(',');
    out.push({date:p[0],main:f(p[1]),small:f(p[2]),mid:f(p[3]),big:f(p[4]),huge:f(p[5]),
              main_pct:f(p[6])});
  }
  return out;
}

/* ---------- 指标层（indicators.py 的 JS 移植，纯函数） ---------- */
function emaList(vals,n){ if(!vals.length)return[]; var a=2/(n+1),out=[vals[0]];
  for(var i=1;i<vals.length;i++)out.push(a*vals[i]+(1-a)*out[i-1]); return out; }

function macdCalc(closes){
  var N={dif:null,dea:null,hist:null,hist_prev:null};
  if(closes.length<35)return N;
  var ef=emaList(closes,12),es=emaList(closes,26),dif=[],i;
  for(i=0;i<closes.length;i++)dif.push(ef[i]-es[i]);
  var dea=emaList(dif,9),hist=[];
  for(i=0;i<dif.length;i++)hist.push(2*(dif[i]-dea[i]));
  return {dif:dif[dif.length-1],dea:dea[dea.length-1],hist:hist[hist.length-1],
          hist_prev:hist[hist.length-2]};
}

function volumeRatio(vols,n){ if(vols.length<n+1)return null;
  var s=0; for(var i=vols.length-1-n;i<vols.length-1;i++)s+=vols[i];
  var base=s/n; return base>0?vols[vols.length-1]/base:null; }

function volumeTrend(vols,n){ if(vols.length<2*n)return null;
  var r=mean(vols.slice(-n)),p=mean(vols.slice(-2*n,-n)); return (r!==null&&p>0)?r/p:null; }

function upDownVol(kline,n){ var seg=kline.slice(-n),ups=[],downs=[];
  seg.forEach(function(b){ if(b.chg>0)ups.push(b.volume); else if(b.chg<0)downs.push(b.volume); });
  if(!ups.length||!downs.length)return null; return mean(ups)/mean(downs); }

function obvSlope(closes,vols,n){ if(closes.length<n+1)return null;
  var o=0,obvArr=[0],i;
  for(i=1;i<closes.length;i++){ o+=closes[i]>closes[i-1]?vols[i]:(closes[i]<closes[i-1]?-vols[i]:0); obvArr.push(o); }
  var tot=0; for(i=vols.length-n;i<vols.length;i++)tot+=vols[i];
  if(tot<=0)return null;
  return (obvArr[obvArr.length-1]-obvArr[obvArr.length-1-n])/tot; }

function biasToMa(closes,n){ if(closes.length<n)return null; var s=0;
  for(var i=closes.length-n;i<closes.length;i++)s+=closes[i]; var m=s/n;
  return m>0?(closes[closes.length-1]-m)/m*100:null; }

function drawdown(closes,n){ if(closes.length<2)return null;
  var seg=closes.slice(-n),hi=Math.max.apply(null,seg);
  return hi>0?(closes[closes.length-1]-hi)/hi*100:null; }

function posPercentile(closes,n){ if(closes.length<2)return null;
  var seg=closes.length>=n?closes.slice(-n):closes;
  var lo=Math.min.apply(null,seg),hi=Math.max.apply(null,seg);
  if(hi<=lo)return 50;
  return (closes[closes.length-1]-lo)/(hi-lo)*100; }

function maAlign(closes){ if(closes.length<60)return null;
  function ma2(n){var s=0;for(var i=closes.length-n;i<closes.length;i++)s+=closes[i];return s/n;}
  var m5=ma2(5),m10=ma2(10),m20=ma2(20),m60=ma2(60);
  if(m5>m10&&m10>m20&&m20>m60)return '多头排列';
  if(m5<m10&&m10<m20&&m20<m60)return '空头排列';
  return '均线纠缠'; }

function bandCalc(kline,n){ if(kline.length<n)return null; var seg=kline.slice(-n);
  var hi=-Infinity,lo=Infinity; seg.forEach(function(b){hi=Math.max(hi,b.high);lo=Math.min(lo,b.low);});
  return lo>0?(hi-lo)/lo*100:null; }

function locusOf(b){ var rng=b.high-b.low; return rng<=0?0.5:(b.close-b.low)/rng; }
function upperShadow(b){ var rng=b.high-b.low; if(rng<=0)return 0;
  return (b.high-Math.max(b.close,b.open))/rng; }
function lowerShadow(b){ var rng=b.high-b.low; if(rng<=0)return 0;
  return (Math.min(b.close,b.open)-b.low)/rng; }

function ampAvg(kline,n){ if(kline.length<n)return null;
  var s=0,ok=true; kline.slice(-n).forEach(function(b){
    if(b.amplitude===null||b.amplitude===undefined)ok=false; else s+=b.amplitude; });
  return ok?s/n:null; }

function tAvg(kline,n){ if(kline.length<n)return null;
  var s=0,ok=true; kline.slice(-n).forEach(function(b){
    if(b.turnover===null||b.turnover===undefined)ok=false; else s+=b.turnover; });
  return ok?s/n:null; }

function limitThreshold(code){ var c=String(code);
  if(/^(30|68)/.test(c))return 19.5; if(/^(83|87|82|43|92)/.test(c))return 29.5; return 9.5; }

function limitUpCount(kline,window,code){ var lim=limitThreshold(code),cnt=0,height=0,i;
  kline.slice(-window).forEach(function(b){ if(b.chg>=lim)cnt++; });
  for(i=kline.length-1;i>=0;i--){ if(kline[i].chg>=lim)height++; else break; }
  return [cnt,height]; }

function breakoutStrength(kline,n){ if(kline.length<n+1)return {breakout:false,volume_ratio:null};
  var closes=[],vols=[],i;
  for(i=0;i<kline.length;i++){closes.push(kline[i].close);vols.push(kline[i].volume);}
  var priorHi=-Infinity;
  for(i=closes.length-1-n;i<closes.length-1;i++)priorHi=Math.max(priorHi,closes[i]);
  var last=kline[kline.length-1];
  var base=mean(vols.slice(vols.length-6,vols.length-1));
  return {breakout:last.close>priorHi, volume_ratio:(base&&base>0)?last.volume/base:null};
}

function divergence(closes,indicator,n){
  if(closes.length<n||indicator.length<n)return null;
  var c=closes.slice(-n),ind=indicator.slice(-n),i;
  var mx=-Infinity; for(i=0;i<n-1;i++) if(c[i]>mx)mx=c[i];
  var ci=0; for(i=0;i<n;i++) if(c[i]>c[ci])ci=i;
  if(c[n-1]>=mx*0.995 && ind[n-1]<ind[ci]*0.95) return '顶背离';
  var mn=Infinity; for(i=0;i<n-1;i++) if(c[i]<mn)mn=c[i];
  var cj=0; for(i=0;i<n;i++) if(c[i]<c[cj])cj=i;
  if(c[n-1]<=mn*1.005 && ind[n-1]>ind[cj]*1.05) return '底背离';
  return null;
}

function fagg(fflow,ws){
  var res={main:{},huge:{},big:{},mid:{},small:{}};
  ws.forEach(function(w){
    Object.keys(res).forEach(function(k){
      if(fflow.length<w){res[k][w]=null;return;}
      var s=0,ok=true;
      for(var i=fflow.length-w;i<fflow.length;i++){
        var v=fflow[i][k]; if(v===null||v===undefined){ok=false;break;} s+=v;
      }
      res[k][w]=ok? s/1e8 : null;
    });
  });
  return res;
}

function fflowPctAvg(fflow,key,n){ if(fflow.length<n)return null;
  var s=0,ok=true; fflow.slice(-n).forEach(function(r){
    if(r[key]===null||r[key]===undefined)ok=false; else s+=r[key]; });
  return ok?s/n:null; }

function hugeDominance(fflow,n){ if(fflow.length<n)return null;
  var main=0,huge=0,ok=true;
  for(var i=fflow.length-n;i<fflow.length;i++){
    if(fflow[i].main===null||fflow[i].huge===null){ok=false;break;}
    main+=fflow[i].main; huge+=fflow[i].huge; }
  if(!ok||Math.abs(main)<1e6)return null;
  return huge/main; }

/* ---------- 筹码模型（ChipModel 的 JS 移植：三角形分布 + 换手衰减） ---------- */
function ChipModel(kline,windowN,bins){
  windowN=windowN||140; bins=bins||200;
  this.valid=false;
  var seg=kline.length>windowN? kline.slice(kline.length-windowN):kline.slice();
  if(seg.length<2)return;
  var loMin=Infinity,hiMax=-Infinity,i,j,b;
  for(i=0;i<seg.length;i++){ loMin=Math.min(loMin,seg[i].low); hiMax=Math.max(hiMax,seg[i].high); }
  if(hiMax<=loMin)return;
  /* 换手率或成交额缺失 → 筹码族整体降权（返回无效模型，所有衍生指标为 null） */
  for(i=0;i<seg.length;i++){
    b=seg[i];
    if(b.turnover===null||b.turnover===undefined||b.amount===null||b.amount===undefined)return;
  }
  var step=(hiMax-loMin)/(bins-1);
  var prices=new Array(bins),chip=new Array(bins);
  for(i=0;i<bins;i++){prices[i]=loMin+step*i;chip[i]=0;}
  for(i=0;i<seg.length;i++){
    b=seg[i];
    if(b.volume<=0||b.high<=b.low)continue;
    var avg=b.amount/(b.volume*100.0);
    avg=Math.min(Math.max(avg,b.low),b.high);
    var w=b.turnover/100.0, decay=Math.max(0,1-w);
    for(j=0;j<bins;j++)chip[j]*=decay;
    var lo=b.low,hi=b.high;
    for(j=0;j<bins;j++){
      var p=prices[j];
      if(p>=lo&&p<=avg)chip[j]+=(p-lo+step)/(avg-lo+step);
      else if(p>avg&&p<=hi)chip[j]+=(hi-p+step)/(hi-avg+step);
    }
    var s=0,block=new Array(bins);
    for(j=0;j<bins;j++){
      var p2=prices[j],v2=0;
      if(p2>=lo&&p2<=avg)v2=(p2-lo+step)/(avg-lo+step);
      else if(p2>avg&&p2<=hi)v2=(hi-p2+step)/(hi-avg+step);
      block[j]=v2;s+=v2;
    }
    if(s>0)for(j=0;j<bins;j++)chip[j]+=block[j]/s*w;
  }
  var tot=0; for(j=0;j<bins;j++)tot+=chip[j];
  if(tot<=0)return;
  for(j=0;j<bins;j++)chip[j]/=tot;
  this.prices=prices;this.chip=chip;this.bins=bins;this.valid=true;
}
ChipModel.prototype.avgCost=function(){ if(!this.valid)return null;
  var s=0;for(var i=0;i<this.bins;i++)s+=this.prices[i]*this.chip[i];return s; };
ChipModel.prototype.profitRatio=function(price){ if(!this.valid)return null;
  var s=0;for(var i=0;i<this.bins;i++)if(this.prices[i]<=price)s+=this.chip[i];return s; };
ChipModel.prototype.peakPrice=function(){ if(!this.valid)return null;
  var mi=0;for(var i=1;i<this.bins;i++)if(this.chip[i]>this.chip[mi])mi=i;
  return this.prices[mi]; };
ChipModel.prototype.concentration=function(ratio){ if(!this.valid)return null;
  ratio=ratio||0.9; var cum=0,cumArr=[],i;
  for(i=0;i<this.bins;i++){cum+=this.chip[i];cumArr.push(cum);}
  var loT=(1-ratio)/2,hiT=1-loT,loI=0,hiI=this.bins-1;
  for(i=0;i<this.bins;i++)if(cumArr[i]>=loT){loI=i;break;}
  for(i=0;i<this.bins;i++)if(cumArr[i]>=hiT){hiI=Math.min(i,this.bins-1);break;}
  var width=this.prices[hiI]-this.prices[loI];
  var mid=this.prices[(loI+hiI)>>1];
  return mid>0?width/mid:null; };
ChipModel.prototype.bottomLocked=function(price){ if(!this.valid)return null;
  var s=0,thr=price*0.85;
  for(var i=0;i<this.bins;i++)if(this.prices[i]<=thr)s+=this.chip[i];return s; };
ChipModel.prototype.overhead=function(price){ if(!this.valid)return null;
  var s=0;
  for(var i=0;i<this.bins;i++)if(this.prices[i]>price&&this.prices[i]<=price*1.20)s+=this.chip[i];
  return s; };

function chipCentroidShift(kline,lookback,windowN){
  if(kline.length<lookback+30)return null;
  var cur=new ChipModel(kline,windowN);
  var prev=new ChipModel(kline.slice(0,kline.length-lookback),windowN);
  if(!cur.valid||!prev.valid)return null;
  var c1=cur.avgCost(),c0=prev.avgCost();
  if(c0===null||c1===null||c0<=0)return null;
  return (c1-c0)/c0*100;
}

/* ---------- 特征工程（analyzer.compute_features 的 JS 移植） ---------- */
function computeFeatures(kline,fflow,code){
  if(kline.length<30)return null;
  var closes=[],vols=[],i;
  for(i=0;i<kline.length;i++){closes.push(kline[i].close);vols.push(kline[i].volume);}
  var last=kline[kline.length-1];
  function ma(n){ if(closes.length<n)return null;
    var s=0;for(var j=closes.length-n;j<closes.length;j++)s+=closes[j];return s/n; }
  var m=macdCalc(closes);
  var agg=(fflow&&fflow.length)?fagg(fflow,[1,3,5,10,20]):null;
  var chip=new ChipModel(kline,Math.min(140,kline.length));
  var chipShift=chipCentroidShift(kline,20,Math.min(140,kline.length));

  var upShadow=0,lowShadow=0;
  kline.slice(-10).forEach(function(b){
    if(upperShadow(b)>0.5)upShadow++; if(lowerShadow(b)>0.5)lowShadow++; });
  var dumpDays=0,prevBase=mean(vols.slice(-11,-1));
  if(prevBase!==null)kline.slice(-10).forEach(function(b){
    if(b.chg<-2&&b.volume>prevBase*1.5)dumpDays++; });
  var bo=breakoutStrength(kline,20);

  function dist(n){ var v=ma(n); if(v===null||v===0)return null;
    return (closes[closes.length-1]-v)/v*100; }
  function pct100(v){ return (v===null||v===undefined)?null:v*100; }

  var F={code:code, price:closes[closes.length-1], last_chg:last.chg,
    turnover5:tAvg(kline,5), turnover10:tAvg(kline,10), amp10:ampAvg(kline,10),
    vr:volumeRatio(vols,5), vol_trend5:volumeTrend(vols,5),
    up_down_vol20:upDownVol(kline,20), obv_slope20:obvSlope(closes,vols,20),
    ma5:ma(5),ma10:ma(10),ma20:ma(20),ma60:ma(60),ma120:ma(120),
    dist_ma10:dist(10),dist_ma20:dist(20),dist_ma60:dist(60),
    bias20:biasToMa(closes,20),
    dd20:drawdown(closes,20), dd60:drawdown(closes,60),
    pos250:posPercentile(closes,250), ma_align:maAlign(closes), band20:bandCalc(kline,20),
    macd_dif:m.dif, macd_dea:m.dea, macd_hist:m.hist, macd_hist_prev:m.hist_prev,
    divergence:divergence(closes,cumsum(vols),30),
    breakout:bo.breakout===true,
    breakout_info:'创20日新高，量能 '+(bo.volume_ratio!==null?Math.round(bo.volume_ratio*100)/100:'-')+'倍',
    up_shadow_days10:upShadow, low_shadow_days10:lowShadow, dump_days10:dumpDays,
    limitup10:limitUpCount(kline,10,code)[0], consec_up:0,
    chip_concentration:chip.concentration(),
    profit_ratio:pct100(chip.profitRatio(closes[closes.length-1])),
    peak_price:chip.peakPrice(), avg_cost:chip.avgCost(),
    bottom_locked:pct100(chip.bottomLocked(closes[closes.length-1])),
    overhead:pct100(chip.overhead(closes[closes.length-1])),
    chip_shift20:chipShift,
    lhb_net:null, margin_pctile:null, float_cap:null, locus5:null};
  var loci=kline.slice(-5).map(locusOf);
  F.locus5=loci.length?mean(loci):null;

  if(agg){
    F.main5=agg.main[5];F.main3=agg.main[3];F.main10=agg.main[10];F.main20=agg.main[20];
    F.huge5=agg.huge[5];F.huge3=agg.huge[3];
    F.big5=agg.big[5];F.big3=agg.big[3];
    F.mid5=agg.mid[5];F.mid3=agg.mid[3];
    F.small5=agg.small[5];F.small3=agg.small[3];
    F.main_pct5=fflowPctAvg(fflow,'main_pct',5);
    F.huge_dom3=hugeDominance(fflow,3);
    var amt5=0,amt10=0;
    kline.slice(-5).forEach(function(b){amt5+=(b.amount||0);}); amt5/=1e8;
    kline.slice(-10).forEach(function(b){amt10+=(b.amount||0);}); amt10/=1e8;
    F.main5_amt_ratio=(amt5>0&&num(agg.main[5])!==null)?agg.main[5]/amt5*100:null;
    F.main10_amt_ratio=(amt10>0&&num(agg.main[10])!==null)?agg.main[10]/amt10*100:null;
  }else{
    ['main5','main3','main10','main20','huge5','huge3','big5','big3','mid5','mid3',
     'small5','small3','main_pct5','huge_dom3','main5_amt_ratio','main10_amt_ratio']
      .forEach(function(k){F[k]=null;});
  }
  return F;
}

/* ---------- 打分卡（stage.py RULES/GATES 的 JS 移植快照） ---------- */
var RULES={
ACCUMULATION:[
 {k:'vol_ratio',l:'温和放量',w:1.5,e:'1.2 ~ 2.5',t:function(F){var h=AND(cmp(F.vr,'>=',1.15),cmp(F.vr,'<=',2.5));return [h,'量比 '+fnum(F.vr)];}},
 {k:'turnover_mild',l:'换手温和',w:1.2,e:'1.2% ~ 6%',t:function(F){return [AND(cmp(F.turnover5,'>=',1.2),cmp(F.turnover5,'<=',6.0)),'5日换手 '+fnum(F.turnover5)+'%'];}},
 {k:'obv_up',l:'OBV 抬升',w:2.0,e:'> 0.05（资金净蓄积）',t:function(F){return [cmp(F.obv_slope20,'>',0.05),'OBV 20日斜率 '+fnum(F.obv_slope20)];}},
 {k:'up_down_vol',l:'阳放阴缩',w:1.5,e:'> 1.2',t:function(F){return [cmp(F.up_down_vol20,'>',1.2),'涨跌量比 '+fnum(F.up_down_vol20)];}},
 {k:'main_inflow',l:'主力温和净流入',w:2.0,e:'净额>0 且 占比≥1.5%',t:function(F){return [AND(cmp(F.main5,'>',0),cmp(F.main_pct5,'>=',1.5)),'5日主力 '+fnum(F.main5)+'亿，占比均值 '+fnum(F.main_pct5)+'%'];}},
 {k:'low_position',l:'位置处于中低位',w:1.5,e:'回撤>12% 或 年内分位<55',t:function(F){return [OR(cmp(F.dd60,'<',-12),cmp(F.pos250,'<',55)),'距60日高点 '+fnum(F.dd60)+'%，年内分位 '+fnum(F.pos250)];}},
 {k:'chip_dense',l:'筹码低位密集',w:1.5,e:'集中度<0.38 且 获利盘<60%',t:function(F){if(num(F.chip_concentration)===null||num(F.profit_ratio)===null)return [null,'筹码数据不足'];return [(F.chip_concentration<0.38&&F.profit_ratio<60),'集中度 '+fnum(F.chip_concentration)+'，获利盘 '+fnum(F.profit_ratio,1)+'%'];}},
 {k:'narrow_band',l:'横盘整理',w:1.0,e:'< 28%',t:function(F){return [cmp(F.band20,'<',28),'20日振幅带 '+fnum(F.band20)+'%'];}},
 {k:'inst_buy',l:'机构席位净买入',w:1.5,e:'机构净额 > 0',t:function(F){return [null,'前端不可得（龙虎榜），自动降权'];}},
 {k:'huge_support',l:'超大单参与',w:1.0,e:'> 0.3',t:function(F){return [cmp(F.huge_dom3,'>',0.3),'超大单占主力 '+fnum(F.huge_dom3)];}},
 {k:'vol_trend_up',l:'量能趋势抬升',w:1.0,e:'> 1.1',t:function(F){return [cmp(F.vol_trend5,'>',1.1),'近5日/前5日量能 '+fnum(F.vol_trend5)];}},
 {k:'capital_momentum',l:'资金流出动能收敛',w:1.5,e:'近5日资金强于近10日',t:function(F){var h=(num(F.main5)!==null&&num(F.main10)!==null)?F.main5>F.main10:null;return [h,'5日主力 '+fnum(F.main5)+'亿 vs 10日 '+fnum(F.main10)+'亿'];}},
 {k:'capital_contra',l:'资金逆势回流',w:2.0,e:'占成交额>3%（价滞而钱进）',t:function(F){return [cmp(F.main5_amt_ratio,'>',3),'5日主力占成交额 '+fnum(F.main5_amt_ratio)+'%'];}},
 {k:'deep_oversold',l:'深度超跌（有修复空间）',w:1.2,e:'< -30%',t:function(F){return [cmp(F.dd60,'<',-30),'距60日高点 '+fnum(F.dd60)+'%'];}},
 {k:'not_yet_launch',l:'尚未进入拉升',w:0.8,e:'乖离 < 12%（未过热）',t:function(F){return [cmp(F.bias20,'<',12),'MA20 乖离 '+fnum(F.bias20)+'%'];}}
],
WASH:[
 {k:'shrink_vol',l:'缩量下跌',w:2.0,e:'< 0.95',t:function(F){return [cmp(F.vr,'<',0.95),'当日量比 '+fnum(F.vr)];}},
 {k:'vol_contract',l:'量能持续萎缩',w:1.5,e:'< 0.9',t:function(F){return [cmp(F.vol_trend5,'<',0.9),'近5/前5量能 '+fnum(F.vol_trend5)];}},
 {k:'mild_drawdown',l:'跌幅可控',w:1.2,e:'≥ -26%（过深则趋势破坏）',t:function(F){return [cmp(F.dd20,'>=',-26),'20日回撤 '+fnum(F.dd20)+'%'];}},
 {k:'hold_key_level',l:'未破关键位',w:2.0,e:'MA60 上方或微幅跌破',t:function(F){return [OR(cmp(F.dist_ma60,'>',-6),cmp(F.dist_ma20,'>',-12)),'距MA60 '+fnum(F.dist_ma60)+'%，距MA20 '+fnum(F.dist_ma20)+'%'];}},
 {k:'bottom_chip_locked',l:'底部筹码锁定',w:2.0,e:'> 18%',t:function(F){return [cmp(F.bottom_locked,'>',18),'低位锁定筹码 '+fnum(F.bottom_locked,1)+'%'];}},
 {k:'main_not_flee',l:'主力未大规模出逃',w:1.8,e:'流出占成交额 <5%/3.5%',t:function(F){if(num(F.main5_amt_ratio)===null)return [null,'资金流数据缺失'];return [AND(cmp(F.main5_amt_ratio,'>=',-5),cmp(F.main10_amt_ratio,'>=',-3.5)),'5日主力占成交额 '+fnum(F.main5_amt_ratio)+'%，10日 '+fnum(F.main10_amt_ratio)+'%'];}},
 {k:'turnover_cool',l:'换手降温',w:1.0,e:'< 9%',t:function(F){return [cmp(F.turnover5,'<',9),'5日换手 '+fnum(F.turnover5)+'%'];}},
 {k:'lower_shadow',l:'长下影承接',w:1.2,e:'≥ 2 天',t:function(F){return [cmp(F.low_shadow_days10,'>=',2),'近10日长下影 '+F.low_shadow_days10+' 天'];}},
 {k:'close_locus',l:'收盘重心不弱',w:1.0,e:'> 0.42',t:function(F){return [cmp(F.locus5,'>',0.42),'5日收盘位置均值 '+fnum(F.locus5)];}},
 {k:'no_dump_day',l:'无放量出货日',w:1.2,e:'≤ 1 天',t:function(F){return [cmp(F.dump_days10,'<=',1),'近10日放量下跌天数 '+F.dump_days10];}},
 {k:'consolidating',l:'整理期未拉升',w:0.8,e:'乖离 < 8%',t:function(F){return [cmp(F.bias20,'<',8),'MA20 乖离 '+fnum(F.bias20)+'%'];}}
],
LAUNCH:[
 {k:'vol_expand',l:'放量',w:2.0,e:'> 1.5',t:function(F){return [cmp(F.vr,'>',1.5),'当日量比 '+fnum(F.vr)];}},
 {k:'breakout',l:'突破平台',w:2.0,e:'收盘创20日新高',t:function(F){return [F.breakout===true,'突破:'+(F.breakout_info||'-')];}},
 {k:'above_ma20',l:'站上 MA20',w:1.5,e:'> 0',t:function(F){return [cmp(F.dist_ma20,'>',0),'距MA20 '+fnum(F.dist_ma20)+'%'];}},
 {k:'bull_align',l:'均线多头排列',w:1.5,e:'MA5>MA10>MA20>MA60',t:function(F){return [F.ma_align==='多头排列'?true:(F.ma_align?false:null),F.ma_align||'未知'];}},
 {k:'macd_golden',l:'MACD 多头且红柱放大',w:1.5,e:'DIF>DEA 且红柱持续放大',t:function(F){if(num(F.macd_dif)===null||num(F.macd_hist_prev)===null)return [null,'MACD 数据不足'];return [AND(AND(cmp(F.macd_dif,'>',F.macd_dea),cmp(F.macd_hist,'>',0)),cmp(F.macd_hist,'>=',F.macd_hist_prev)),'DIF '+fnum(F.macd_dif)+' / DEA '+fnum(F.macd_dea)+'，红柱 '+fnum(F.macd_hist)];}},
 {k:'macd_above_water',l:'DIF 站上零轴（水上）',w:1.0,e:'DIF > 0',t:function(F){return [cmp(F.macd_dif,'>',0),'DIF '+fnum(F.macd_dif)];}},
 {k:'capital_inflow',l:'资金大幅净流入',w:2.0,e:'净额>0 且 占比>5%',t:function(F){return [AND(cmp(F.main3,'>',0),cmp(F.main_pct5,'>',5)),'3日主力 '+fnum(F.main3)+'亿，占比均值 '+fnum(F.main_pct5)+'%'];}},
 {k:'huge_lead',l:'超大单主导',w:1.2,e:'> 0.45',t:function(F){return [cmp(F.huge_dom3,'>',0.45),'超大单占主力 '+fnum(F.huge_dom3)];}},
 {k:'strong_bar',l:'强势 K 线',w:1.5,e:'涨幅>5% 或 有涨停',t:function(F){return [OR(cmp(F.last_chg,'>',5),cmp(F.limitup10,'>=',1)),'当日涨幅 '+fnum(F.last_chg)+'%，近10日涨停 '+(F.limitup10===null?'无数据':F.limitup10)+' 次'];}},
 {k:'profit_moderate',l:'获利盘未过热',w:1.2,e:'35% ~ 92%',t:function(F){if(num(F.profit_ratio)===null)return [null,'筹码数据不足'];return [AND(cmp(F.profit_ratio,'>=',35),cmp(F.profit_ratio,'<',92)),'获利盘 '+fnum(F.profit_ratio,1)+'%'];}},
 {k:'low_overhead',l:'上方抛压有限',w:1.2,e:'< 22%',t:function(F){return [cmp(F.overhead,'<',22),'上方套牢盘 '+fnum(F.overhead,1)+'%'];}},
 {k:'active_turnover',l:'换手活跃',w:1.0,e:'3% ~ 20%',t:function(F){return [AND(cmp(F.turnover5,'>=',3),cmp(F.turnover5,'<=',20)),'5日换手 '+fnum(F.turnover5)+'%'];}},
 {k:'resonance',l:'资金共振',w:1.2,e:'机构净买 > 0',t:function(F){return [null,'前端不可得（龙虎榜），自动降权'];}},
 {k:'obv_rising',l:'OBV 同步走强',w:1.0,e:'> 0',t:function(F){return [cmp(F.obv_slope20,'>',0),'OBV 斜率 '+fnum(F.obv_slope20)];}}
],
DISTRIBUTION:[
 {k:'vol_stagnant',l:'放量滞涨',w:2.0,e:'放量但涨幅<2.5%',t:function(F){if(num(F.vr)===null||num(F.last_chg)===null)return [null,'数据不足'];return [AND(cmp(F.vr,'>',1.5),cmp(F.last_chg,'<',2.5)),'量比 '+fnum(F.vr)+'，当日涨幅 '+fnum(F.last_chg)+'%'];}},
 {k:'turnover_hot',l:'换手过热',w:1.8,e:'> 12%',t:function(F){return [cmp(F.turnover5,'>',12),'5日换手 '+fnum(F.turnover5)+'%'];}},
 {k:'upper_shadow_days',l:'反复长上影',w:1.5,e:'≥ 2 天',t:function(F){return [cmp(F.up_shadow_days10,'>=',2),'近10日长上影 '+F.up_shadow_days10+' 天'];}},
 {k:'chip_shift_up',l:'底部筹码上移 / 消失',w:2.2,e:'< 25% 且 重心上移>4%',t:function(F){if(num(F.bottom_locked)===null||num(F.chip_shift20)===null)return [null,'筹码数据不足'];return [AND(cmp(F.bottom_locked,'<',25),cmp(F.chip_shift20,'>',4)),'低位锁定 '+fnum(F.bottom_locked,1)+'%，20日重心迁移 '+fnum(F.chip_shift20)+'%'];}},
 {k:'main_outflow',l:'主力净流出',w:2.0,e:'净流出占成交额>2%',t:function(F){if(num(F.main5_amt_ratio)===null&&num(F.main10_amt_ratio)===null)return [null,'资金流数据缺失'];return [OR(cmp(F.main5_amt_ratio,'<',-2),cmp(F.main10_amt_ratio,'<',-1.5)),'5日主力占成交额 '+fnum(F.main5_amt_ratio)+'%，10日 '+fnum(F.main10_amt_ratio)+'%'];}},
 {k:'blow_off',l:'加速赶顶（乖离失控）',w:2.2,e:'乖离>22% 且 位置分位>88',t:function(F){if(num(F.bias20)===null||num(F.pos250)===null)return [null,'数据不足'];return [AND(cmp(F.bias20,'>',22),cmp(F.pos250,'>',88)),'MA20乖离 '+fnum(F.bias20)+'%，位置分位 '+fnum(F.pos250)];}},
 {k:'limitup_crowd',l:'连板透支',w:1.5,e:'≥3次 且 位置>85',t:function(F){if(num(F.limitup10)===null||num(F.pos250)===null)return [null,'数据不足'];return [AND(cmp(F.limitup10,'>=',3),cmp(F.pos250,'>',85)),'近10日涨停 '+F.limitup10+' 次，位置分位 '+fnum(F.pos250)];}},
 {k:'extreme_turnover',l:'换手极端放大',w:1.5,e:'> 18%',t:function(F){return [cmp(F.turnover5,'>',18),'5日换手 '+fnum(F.turnover5)+'%'];}},
 {k:'huge_out_small_in',l:'大单出、散户接',w:2.0,e:'超大单净流出 + 小单净流入',t:function(F){if(num(F.huge3)===null||num(F.small3)===null)return [null,'资金流数据缺失'];return [AND(cmp(F.huge3,'<',0),cmp(F.small3,'>',0)),'3日超大单 '+fnum(F.huge3)+'亿，小单 '+fnum(F.small3)+'亿'];}},
 {k:'macd_divergence',l:'顶背离',w:1.5,e:'出现顶背离',t:function(F){return [F.divergence==='顶背离'?true:(F.divergence?false:null),F.divergence||'无显著背离'];}},
 {k:'inst_sell',l:'机构席位净卖出',w:1.5,e:'< 0',t:function(F){return [null,'前端不可得（龙虎榜），自动降权'];}},
 {k:'margin_high',l:'融资余额高位',w:1.2,e:'> 75 分位',t:function(F){return [null,'前端不可得（两融），自动降权'];}},
 {k:'break_ma10',l:'跌破 MA10',w:1.2,e:'< 0',t:function(F){return [cmp(F.dist_ma10,'<',0),'距MA10 '+fnum(F.dist_ma10)+'%'];}},
 {k:'weak_rebound',l:'反抽缩量',w:1.2,e:'回撤>8% 且 量能萎缩',t:function(F){return [AND(cmp(F.dd20,'<',-8),cmp(F.vol_trend5,'<',0.95)),'20日回撤 '+fnum(F.dd20)+'%，量能趋势 '+fnum(F.vol_trend5)];}},
 {k:'high_swing',l:'高位宽幅震荡',w:1.0,e:'> 5.5%',t:function(F){return [cmp(F.amp10,'>',5.5),'10日振幅均值 '+fnum(F.amp10)+'%'];}},
 {k:'high_position',l:'所处位置偏高',w:1.5,e:'> 70',t:function(F){return [cmp(F.pos250,'>',70),'年内位置分位 '+fnum(F.pos250)];}},
 {k:'overheated_profit',l:'获利盘极度膨胀',w:1.2,e:'> 88%',t:function(F){return [cmp(F.profit_ratio,'>',88),'获利盘 '+fnum(F.profit_ratio,1)+'%'];}}
]};

var GATES={
 ACCUMULATION:[function(F){return cmp(F.pos250,'<',78);}],
 WASH:[function(F){return cmp(F.dd20,'<',-4);},
       function(F){return F.ma_align?(F.ma_align==='空头排列'?false:true):null;}],
 LAUNCH:[function(F){return (F.breakout===true)?true:cmp(F.dist_ma20,'>',-1);},
         function(F){return cmp(F.bias20,'<',30);}],
 DISTRIBUTION:[function(F){return cmp(F.pos250,'>',55);}]
};
var GATE_PENALTY=0.62;
var STAGE_ORDER=['ACCUMULATION','WASH','LAUNCH','DISTRIBUTION'];
var STAGE_INFO={ACCUMULATION:{name:'建仓期',color:'#185FA5'},
                WASH:{name:'洗盘期',color:'#e65100'},
                LAUNCH:{name:'启动期',color:'#c62828'},
                DISTRIBUTION:{name:'撤离期',color:'#5d4037'}};

function confLabel(c){ return c>=25?'高置信':(c>=12?'中等置信':(c>=5?'弱信号':'模糊区间')); }

function evaluateStage(stage,F){
  var evs=[],tot=0,hit=0,i;
  for(i=0;i<RULES[stage].length;i++){
    var r=RULES[stage][i],out;
    try{ out=r.t(F); }catch(e){ out=[null,'计算异常']; }
    var ho=(typeof out[0]==='boolean')?out[0]:null;
    if(ho!==null){ tot+=r.w; if(ho)hit+=r.w; }
    evs.push({key:r.k,label:r.l,hit:ho,desc:out[1],weight:r.w,expect:r.e});
  }
  var base=(tot>0)?hit/tot*100:0;
  var gres=[];
  (GATES[stage]||[]).forEach(function(g){ try{gres.push(g(F));}catch(e){gres.push(null);} });
  var app=gres.filter(function(g){return typeof g==='boolean';});
  var gateOk=(!app.length)||app.every(function(g){return g;});
  return {score: gateOk?base:base*GATE_PENALTY, evs:evs, gateOk:gateOk};
}

function detectStage(F){
  var scores={},evs={},gates={},cov={};
  STAGE_ORDER.forEach(function(st){
    var r=evaluateStage(st,F);
    scores[st]=Math.round(r.score*10)/10;
    evs[st]=r.evs; gates[st]={ok:r.gateOk};
    cov[st]=r.evs.filter(function(e){return e.hit!==null;}).length;
  });
  var ranked=STAGE_ORDER.slice().sort(function(a,b){return scores[b]-scores[a];});
  var top=ranked[0], second=ranked.length>1?scores[ranked[1]]:0;
  return {stage:top,scores:scores,evidences:evs,gates:gates,
          confidence:Math.round((scores[top]-second)*10)/10,coverage:cov};
}

/* ---------- 操作评分（stage.action_scores 的 JS 移植） ---------- */
function actionScores(F,res){
  function cl(v){return Math.max(0,Math.min(100,v));}
  var st=res.stage;
  var ratio=F.main5_amt_ratio,pos=F.pos250,bias=F.bias20,to5=F.turnover5,
      pr=F.profit_ratio,shift=F.chip_shift20,locked=F.bottom_locked;
  var opp=50.0;
  opp+=({LAUNCH:20,ACCUMULATION:12,WASH:4,DISTRIBUTION:-18}[st]||0);
  if(num(ratio)!==null) opp+= ratio>3?10:(ratio>0?5:(ratio<-3?-10:0));
  if(num(pos)!==null) opp+= pos<40?8:(pos>85?-8:0);
  if(F.vr&&F.vol_trend5&&F.vr>1.2&&F.vol_trend5>1.1)opp+=6;
  if(num(pr)!==null) opp+= pr>90?-6:(pr<30?4:0);
  if(!res.gates[st].ok)opp-=5;
  if(res.confidence<5)opp-=5;
  opp=cl(opp);
  var risk=25.0;
  risk+=({DISTRIBUTION:35,LAUNCH:12,WASH:5,ACCUMULATION:0}[st]||0);
  if(num(bias)!==null) risk+= bias>30?20:(bias>20?12:(bias>12?5:0));
  if(num(to5)!==null) risk+= to5>18?15:(to5>12?8:0);
  if(num(shift)!==null&&num(locked)!==null&&shift>8&&locked<15)risk+=12;
  if(num(ratio)!==null&&ratio<-5)risk+=12;
  if(num(pos)!==null&&pos>90)risk+=8;
  if(num(pr)!==null&&pr>92)risk+=8;
  risk=cl(risk);
  var act,tone;
  if(risk>=65){act='减仓离场';tone='#c62828';}
  else if(risk>=50){act='谨慎持有';tone='#e65100';}
  else if(opp>=65&&risk<45){act='重点介入';tone='#c62828';}
  else if(opp>=55&&risk<50){act='逢低关注';tone='#185FA5';}
  else if(opp>=45){act='跟踪观察';tone='#5d4037';}
  else{act='暂避观望';tone='#6b7280';}
  return {opportunity:Math.round(opp),risk:Math.round(risk),action:act,tone:tone,
    reason:'阶段为'+STAGE_INFO[st].name+'（'+Math.round(res.scores[st])+'分/'+confLabel(res.confidence)+
      '），机会分 '+Math.round(opp)+'、风险分 '+Math.round(risk)+'；'+
      '资金'+((ratio||0)>0?'净流入':'净流出')+Math.abs(ratio||0).toFixed(1)+
      '%，年内位置 '+(pos===null?0:Math.round(pos))+' 分位。'};
}

/* ---------- 判定基准日（analyzer.need_trim_today 的移植） ---------- */
function localDateStr(d){ function p(x){return (x<10?'0':'')+x;}
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate()); }
function trimToday(kline,fflow){
  var k=kline,f=fflow||[],trimmed=false;
  if(k.length){
    var today=localDateStr(new Date());
    if(k[k.length-1].date===today){
      var now=new Date();
      if(now.getHours()<15||(now.getHours()===15&&now.getMinutes()<5)){
        k=k.slice(0,-1); trimmed=true;
        var jd=k.length?k[k.length-1].date:'';
        f=f.filter(function(r){return r.date<=jd;});
      }
    }
  }
  return {k:k,f:f,date:k.length?k[k.length-1].date:'',trimmed:trimmed};
}

/* ---------- 单股完整分析 ---------- */
function analyze(kline,fflow,code){
  var t=trimToday(kline,fflow);
  var F=computeFeatures(t.k,t.f,code);
  if(!F)return null;
  var res=detectStage(F);
  var act=actionScores(F,res);
  var evidence=res.evidences[res.stage].filter(function(e){return e.hit!==null;});
  return {F:F,res:res,act:act,evidence:evidence,judge_date:t.date,trimmed:t.trimmed};
}

/* ---------- 查询编排：K线主源东财 → 腾讯兜底；资金流尽力而为 ---------- */
function queryStock(rc){
  return Promise.all([
    fetchEMKline(rc.secid)
      .then(function(raw){var p=parseEMKline(raw);p.src='eastmoney';return p;})
      .catch(function(){return fetchTxKline(rc.sym).then(function(arr){
        var p=parseTxKline(arr);p.src='tencent';return p;});}),
    fetchFflow(rc.secid),
    fetchQqProfile(rc.sym)
  ]).then(function(rs){
    var k=rs[0];
    if(!k||!k.kline||k.kline.length<60)throw new Error('无法获取该代码的行情数据');
    var r=analyze(k.kline,rs[1]||[],rc.code);
    if(!r)throw new Error('历史数据不足（需至少 30 个交易日）');
    r.name=k.name||(rs[2]&&rs[2].name)||rc.code;
    r.kdata=k.kdata; r.src=k.src;
    r.has_fflow=!!(rs[1]&&rs[1].length);
    return r;
  });
}

/* ---------- 导出（DOM 接线在下方浏览器守卫内，node 环境仅暴露纯计算） ---------- */
var API={resolveCode:resolveCode,computeFeatures:computeFeatures,detectStage:detectStage,
  actionScores:actionScores,analyze:analyze,parseEMKline:parseEMKline,
  parseEMFflow:parseEMFflow,parseTxKline:parseTxKline,queryStock:queryStock,
  trimToday:trimToday,ChipModel:ChipModel,chipCentroidShift:chipCentroidShift,
  VERSION:VERSION};

if(typeof document!=='undefined'&&typeof el==='function'&&typeof DATA!=='undefined'){

  function poolHits(raw){
    var s=String(raw||'').trim().toLowerCase(); if(!s)return [];
    var hits=[];
    DATA.industries.forEach(function(ind){
      ind.leaders.forEach(function(L){
        if(L.code===s||(s.length>=2&&L.name.toLowerCase().indexOf(s)>=0))
          hits.push(L.code);
      });
    });
    return hits;
  }

  function liveQuery(rc){
    el('modal').classList.add('on');
    document.body.style.overflow='hidden';
    el('m_name').innerHTML=rc.code;
    el('m_ind').textContent='即时查询';
    el('m_badge').style.background='#6b7280'; el('m_badge').textContent='抓取数据中…';
    el('m_score').textContent=''; el('m_px').innerHTML=''; el('m_act').innerHTML='';
    el('m_chart').innerHTML='<div class="empty" style="padding:44px">正在抓取行情与资金流数据，约需 2~6 秒 …</div>';
    el('m_detail').innerHTML='';

    DQ.queryStock(rc).then(function(r){
      var F=r.F,res=r.res,act=r.act;
      var L={code:rc.code,name:r.name,price:F.price,chg:F.last_chg||0,
        stage:res.stage,score:res.score,scores:res.scores,
        confidence:res.confidence,conf_label:confLabel(res.confidence),
        opportunity:act.opportunity,risk:act.risk,action:act.action,tone:act.tone,
        reason:act.reason,evidence:r.evidence};
      KDATA[rc.code]=r.kdata;
      renderLeaderModal(L,'即时查询');
      el('m_ind').textContent='即时查询 · '+
        (r.src==='eastmoney'?'东财行情':'腾讯行情（降级源，无换手/成交额）')+
        (r.has_fflow?' + 东财资金流':'（资金流未取到，相关规则已降权）');
      var note=document.createElement('div');
      note.className='m-sec';
      note.innerHTML='判定基准日 <b>'+r.judge_date+'</b>'+
        (r.trimmed?'（盘中查询，自动剔除未收盘的当日K线，与每日看板口径一致）':'')+
        ' · 打分卡为 dragon/stage.py 的前端移植快照（'+DQ.VERSION+'），'+
        '龙虎榜 / 融资余额数据前端不可得，相关证据自动降权。';
      el('m_detail').appendChild(note);
    }).catch(function(e){
      el('m_badge').textContent='查询失败';
      el('m_chart').innerHTML='<div class="empty" style="padding:44px">数据抓取失败：'+
        esc(e&&e.message||String(e))+
        '<br/><br/>可能是网络限制、接口变更或代码不存在，可稍后重试。'+
        '<br/>示例：600519（沪）/ 000001（深）/ 300750（创业）</div>';
    });
  }

  function doQuery(){
    var raw=(el('qcode').value||'').trim();
    if(!raw)return;
    var rc=DQ.resolveCode(raw);
    /* 1. 看板内精确命中 → 直接展示后端完整数据 */
    var hits=poolHits(raw);
    if(rc){
      for(var i=0;i<hits.length;i++){
        var c=hits[i];
        if(c===rc.code){ openModal(c); return; }
      }
    }else if(hits.length){
      openModal(hits[0]);
      if(hits.length>1)el('qhint').textContent='找到 '+hits.length+' 只匹配标的，已展示第一只';
      return;
    }
    /* 2. 看板外代码 → 浏览器现场抓取 + 现场判定 */
    if(rc){ liveQuery(rc); return; }
    el('qhint').textContent='未识别「'+raw+'」：请输入 6 位股票代码，或看板内的股票/行业名称';
  }

  el('qbtn').onclick=doQuery;
  el('qcode').addEventListener('keydown',function(ev){
    if(ev.key==='Enter'){ev.preventDefault();doQuery();}
  });
}

return API;
})();
"""


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
  <div class="qbox">
    <input id="qcode" placeholder="输入股票代码即时查询，如 600519 / 000001 / 300750">
    <button id="qbtn">查 询</button>
    <span class="qhint" id="qhint">看板内标的直接展示详情；看板外的任意 A 股代码，
      浏览器现场抓取行情并计算四阶段评分（约 3~6 秒）</span>
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
<b>即时查询</b>：顶部搜索框输入任意 A 股代码（如 600519），浏览器端通过 JSONP
直接向东财 / 腾讯行情服务器取数，并在前端移植的同一套打分卡上现场计算四阶段评分。
看板外标的缺龙虎榜与融资余额数据，相关证据自动降权（不计入分母）；
判定基准日口径与每日看板一致（盘中查询自动剔除未收盘的当日K线）。<br/>
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
<script>
{QUERY_JS}
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
