# -*- coding: utf-8 -*-
"""临时验证：ETF 数据接口可用性测试。"""
import sys, os
sys.path.insert(0, r"E:\wb_jobs\finance")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(r"E:\wb_jobs\finance")

from dragon.datasource import EMClient

client = EMClient(cache_dir=".cache/etf_test", verbose=True, min_interval=0.4)

# 1. ETF 榜单（沪+深场内基金，按成交额）
url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=15&po=1&np=1"
       "&fltt=2&invt=2&fid=f6&fs=m:1+t:5,m:0+t:5"
       "&fields=f12,f14,f2,f3,f6,f8,f62,f184")
d = client.get_json(url)
rows = (d.get("data") or {}).get("diff") or []
if isinstance(rows, dict):
    rows = list(rows.values())
print("\n=== ETF 榜单 top15（按成交额）===")
for r in rows:
    print(r.get("f12"), r.get("f14"), "额", r.get("f6"), "涨", r.get("f3"),
          "主力", r.get("f62"), "主力占比", r.get("f184"), "换手", r.get("f8"))

# 2. 510300 K线 + 资金流
print("\n=== 510300 沪深300ETF ===")
k = client.kline("510300", beg="20240101")
print("kline source:", (k or {}).get("source"), "bars:",
      len(((k or {}).get("data") or {}).get("klines") or []))
if k and k.get("data"):
    print("last kline:", k["data"]["klines"][-1])
f = client.fflow("510300")
kl = ((f or {}).get("data") or {}).get("klines") or []
print("fflow bars:", len(kl), "source:", (f or {}).get("source"))
if kl:
    print("last fflow:", kl[-1])
