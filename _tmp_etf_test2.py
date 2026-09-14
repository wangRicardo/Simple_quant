# -*- coding: utf-8 -*-
"""临时验证2：ETF 板块 fs 过滤条件。"""
import sys, os
sys.path.insert(0, r"E:\wb_jobs\finance")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(r"E:\wb_jobs\finance")

from dragon.datasource import EMClient

client = EMClient(cache_dir=".cache/etf_test", verbose=False, min_interval=0.4)

for fs in ["b:MK0021,b:MK0022,b:MK0023,b:MK0024", "b:MK0021"]:
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1"
           "&fltt=2&invt=2&fid=f6&fs=" + fs +
           "&fields=f12,f14,f2,f3,f6,f8,f62,f184")
    d = client.get_json(url)
    rows = (d.get("data") or {}).get("diff") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    print("=== fs =", fs, " total:", (d.get("data") or {}).get("total"))
    for r in rows:
        print(" ", r.get("f12"), r.get("f14"), "额(亿)", round((r.get("f6") or 0)/1e8,1),
              "涨", r.get("f3"), "主力(亿)", round((r.get("f62") or 0)/1e8,2),
              "占比", r.get("f184"), "换手", r.get("f8"))
    print()
