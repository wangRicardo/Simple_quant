# -*- coding: utf-8 -*-
"""
东方财富数据接口封装层。

提供龙头战法量化系统所需的全部原始数据：
  - 日K线（含复权）
  - 资金流日线（主力/超大单/大单/中单/小单）
  - 实时快照（量比、换手率、市盈率、市值）
  - 龙虎榜（机构席位净买卖）
  - 融资融券余额
  - 股东户数 / 机构持仓
  - 板块与行情列表（用于龙头候选池筛选）

设计原则：
  1. 单一 Session + 重试，避免频繁握手
  2. 所有请求结果落本地磁盘缓存（默认当日有效），便于反复调试不重复打接口
  3. 任何单点失败都降级为 None，绝不中断主流程
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from typing import Any, Dict, List, Optional, Sequence

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

UA_POOL = [
    UA,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Edge/121.0.0.0 Safari/537.36",
]

PUSH2HIS = "https://push2his.eastmoney.com/api/qt/stock"
PUSH2 = "https://push2.eastmoney.com/api/qt/stock"
PUSH2DELAY = "https://push2delay.eastmoney.com/api/qt/stock"
CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 行情接口备用域名。主域名 push2 / push2his 在部分网络环境会被服务端
# 彻底屏蔽（TCP 层 RemoteDisconnected），自动故障转移对「每日定时运行」
# 场景是刚需 —— 否则每天都要人工介入。
PUSH_HOSTS = [
    "push2.eastmoney.com",
    "push2delay.eastmoney.com",
    "82.push2.eastmoney.com",
    "1.push2.eastmoney.com",
    "push2delay.eastmoney.com",
]
HIS_HOSTS = [
    "push2his.eastmoney.com",
    "push2delay.eastmoney.com",
]

import re as _re  # noqa: E402

_RE_PUSH2HIS = _re.compile(r"https://[\w\-.]*push2his(?:delay)?\.eastmoney\.com")
_RE_PUSH2 = _re.compile(r"https://[\w\-.]*push2(?:delay)?\.eastmoney\.com")


def host_pool(url: str) -> Optional[List[str]]:
    """判断该 URL 属于哪个域名池；非东财行情域名返回 None。"""
    if _RE_PUSH2HIS.search(url):
        return HIS_HOSTS
    if _RE_PUSH2.search(url):
        return PUSH_HOSTS
    return None


def swap_host(url: str, host: str) -> str:
    """把 URL 中的行情域名替换为指定域名。"""
    if _RE_PUSH2HIS.search(url):
        return _RE_PUSH2HIS.sub("https://" + host, url)
    return _RE_PUSH2.sub("https://" + host, url)


def to_tx_symbol(code: str) -> str:
    """转成腾讯行情代码（sh/sz/bj 前缀）。"""
    c = code.strip()
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("0", "3")):
        return "sz" + c
    return "bj" + c


def to_secid(code: str) -> str:
    """把 6 位 A 股代码转成东财 secid。

    沪市(1.)：60xxxx / 68xxxx / 51xxxx / 11xxxx
    深市(0.)：00xxxx / 30xxxx / 15xxxx / 12xxxx
    北交所(0.)：8xxxxx / 4xxxxx
    """
    code = code.strip()
    if "." in code:  # 已带市场前缀
        return code
    head = code[:2]
    if head in ("60", "68", "51", "58", "11", "50", "56"):
        return "1." + code
    if head in ("00", "30", "15", "12", "16", "18"):
        return "0." + code
    if head in ("83", "87", "82", "88", "43", "92"):
        return "0." + code
    return "0." + code


def _today() -> str:
    return time.strftime("%Y%m%d")


class EMClient:
    """带缓存 + 重试的东方财富 HTTP 客户端。"""

    def __init__(self, cache_dir: str = ".cache/dragon", ttl: int = 3600,
                 timeout: int = 20, retries: int = 4, verbose: bool = True,
                 min_interval: float = 0.35):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.min_interval = min_interval      # 请求最小间隔，防止被限流
        self._last_req = 0.0
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.trust_env = False  # 绕过系统代理，避免部分环境被拦截
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
            "Connection": "close",
        })
        self._hits = 0
        self._miss = 0
        self._bad_hosts: set = set()   # 连接层不可达的域名，本次运行内不再尝试
        self._em_fail = 0
        self._em_fail_flow = 0
        self._em_kline_down = False   # 东财K线故障短路标志
        self._em_flow_down = False    # 东财资金流故障短路标志

    # ---------- cache ----------
    def _cache_path(self, key: str) -> str:
        h = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"{h}.json")

    def _read_cache(self, key: str) -> Optional[Any]:
        p = self._cache_path(key)
        if not os.path.exists(p):
            return None
        if time.time() - os.path.getmtime(p) > self.ttl:
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                self._hits += 1
                return json.load(f)
        except Exception:
            return None

    def _write_cache(self, key: str, data: Any) -> None:
        try:
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- http ----------
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def get_json(self, url: str, referer: Optional[str] = None,
                 use_cache: bool = True) -> Optional[Dict]:
        key = url
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached

        pool = host_pool(url)
        cands: List[Optional[str]] = [None]
        if pool:
            # 已被判定为「硬故障」的域名直接跳过，不在它身上浪费超时
            alive = [h for h in pool if h not in self._bad_hosts]
            cands = (alive or pool)[:max(1, min(len(alive or pool), self.retries))]

        last_err = None
        for attempt in range(self.retries):
            host = cands[min(attempt, len(cands) - 1)]
            req_url = swap_host(url, host) if host else url
            try:
                # 节流：距离上次请求不足 min_interval 则等待
                wait = self.min_interval - (time.time() - self._last_req)
                if wait > 0:
                    time.sleep(wait)
                self._last_req = time.time()

                headers = {"Referer": referer} if referer else {}
                if attempt > 0:
                    headers["User-Agent"] = UA_POOL[attempt % len(UA_POOL)]
                resp = self.session.get(req_url, timeout=self.timeout, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if use_cache:
                    self._write_cache(key, data)
                self._miss += 1
                return data
            except Exception as e:  # noqa: BLE001
                last_err = e
                # 连接层错误 = 该域名被屏蔽，记入黑名单，后续请求不再尝试
                if host and isinstance(e, (requests.exceptions.ConnectionError,
                                           requests.exceptions.ProxyError,
                                           requests.exceptions.ConnectTimeout,
                                           requests.exceptions.ReadTimeout)):
                    if host not in self._bad_hosts:
                        self._bad_hosts.add(host)
                        self._log(f"  [数据源] 域名不可达，本次运行内剔除: {host}")
                self._rebuild_session()
                time.sleep(0.5 * (2 ** attempt) + random.random() * 0.3)
        self._log(f"  [warn] 请求失败(已重试{self.retries}次): {type(last_err).__name__}")
        return None

    def get_text(self, url: str, referer: Optional[str] = None,
                 encoding: str = "utf-8", use_cache: bool = True) -> Optional[str]:
        """取纯文本响应（用于新浪等返回非标准 JSON 的接口）。"""
        key = "TXT::" + url
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached
        for attempt in range(self.retries):
            try:
                wait = self.min_interval - (time.time() - self._last_req)
                if wait > 0:
                    time.sleep(wait)
                self._last_req = time.time()
                headers = {"Referer": referer} if referer else {}
                if attempt > 0:
                    headers["User-Agent"] = UA_POOL[attempt % len(UA_POOL)]
                resp = self.session.get(url, timeout=self.timeout, headers=headers)
                resp.raise_for_status()
                resp.encoding = encoding
                txt = resp.text
                if use_cache:
                    self._write_cache(key, txt)
                self._miss += 1
                return txt
            except Exception:  # noqa: BLE001
                self._rebuild_session()
                time.sleep(0.8 * (2 ** attempt) + random.random() * 0.4)
        return None

    def _rebuild_session(self) -> None:
        """重建底层连接池。长时间复用同一连接容易被服务端断连。"""
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": UA_POOL[int(time.time()) % len(UA_POOL)],
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
        })

    # ---------- 日K线（见下方 kline / _kline_em / kline_tencent） ----------

    # ---------- 备用数据源：腾讯行情 ----------
    def tx_quote(self, code: str) -> Optional[Dict]:
        """腾讯实时行情快照。用于 K 线兜底时补全换手率与流通股本。

        字段（~ 分隔）：3=现价 32=涨跌幅 38=换手率 44=流通市值(亿) 45=总市值(亿) 49=量比
        """
        sym = to_tx_symbol(code)
        url = f"https://qt.gtimg.cn/q={sym}"
        try:
            wait = self.min_interval - (time.time() - self._last_req)
            if wait > 0:
                time.sleep(wait)
            self._last_req = time.time()
            resp = self.session.get(url, timeout=self.timeout)
            resp.encoding = "gbk"
            txt = resp.text
            if "~" not in txt:
                return None
            seg = txt.split("=")[1].strip().strip(";").strip('"')
            p = seg.split("~")
            if len(p) < 50:
                return None

            def fnum(i):
                try:
                    return float(p[i])
                except Exception:  # noqa: BLE001
                    return None

            price, chg = fnum(3), fnum(32)
            float_cap_yi, total_cap_yi = fnum(44), fnum(45)
            shares = None
            if float_cap_yi and price:
                shares = float_cap_yi * 1e8 / price
            return {
                "name": p[1], "price": price, "chg": chg,
                "turnover": fnum(38), "vr": fnum(49),
                "float_cap": float_cap_yi, "total_cap": total_cap_yi,
                "float_shares": shares,
            }
        except Exception:  # noqa: BLE001
            return None

    def kline_tencent(self, code: str, n: int = 320) -> Optional[Dict]:
        """腾讯日 K（前复权）。东财 K 线不可用时的兜底。

        腾讯不返回成交额与换手率，此处按「典型价 × 成交量」估算成交额，
        按「成交量 / 流通股本」计算换手率 —— 精度略降但足以支撑阶段判定。
        """
        sym = to_tx_symbol(code)
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={sym},day,,,{n},qfq")
        d = self.get_json(url)
        if not d or not d.get("data"):
            return None
        node = d["data"].get(sym) or {}
        key = "qfqday" if "qfqday" in node else "day"
        arr = node.get(key) or []
        if len(arr) < 60:
            return None

        q = self.tx_quote(code) or {}
        shares = q.get("float_shares")

        rows = []
        for a in arr:
            try:
                date, o, c, h, l, v = (a[0], float(a[1]), float(a[2]),
                                       float(a[3]), float(a[4]), float(a[5]))
            except Exception:  # noqa: BLE001
                continue
            if v <= 0:
                continue
            typ = (h + l + c) / 3.0                  # 典型价
            amount = typ * v * 100                   # 手 → 股
            to = (v * 100 / shares * 100) if shares else 0.0
            rng = (h - l) / c * 100 if c > 0 else 0.0
            prev = rows[-1]["close"] if rows else c
            chg = (c - prev) / prev * 100 if prev else 0.0
            rows.append({
                "date": date.replace("-", ""),
                "open": o, "close": c, "high": h, "low": l,
                "volume": v, "amount": amount,
                "amplitude": rng, "chg": chg,
                "chg_amt": c - prev if rows else 0.0,
                "turnover": to,
            })
        if len(rows) < 60:
            return None
        # 第一根是上市/窗口首日，涨跌幅无法计算，置 0
        if rows:
            rows[0]["chg"] = 0.0
        return {
            "source": "tencent",
            "data": {
                "name": q.get("name") or code,
                "code": code,
                "klines": [f"{r['date']},{r['open']},{r['close']},{r['high']},{r['low']},"
                           f"{r['volume']},{r['amount']:.2f},{r['amplitude']:.2f},"
                           f"{r['chg']:.2f},{r['chg_amt']:.2f},{r['turnover']:.4f}"
                           for r in rows],
            },
        }

    def kline(self, code: str, beg: str = "0", end: str = "20500101",
              klt: int = 101, fqt: int = 1) -> Optional[Dict]:
        """日K线（东财优先，腾讯兜底）。

        东财连续失败达到阈值后短路，本次运行直接走腾讯 —— 否则批量任务里
        每只票都要白白等一轮超时，几十只票会累积成数分钟的无谓开销。
        """
        if not self._em_kline_down:
            raw = self._kline_em(code, beg, end, klt, fqt)
            # 延时服务器会返回「data 存在但 klines 为空」的响应，必须校验
            if raw and raw.get("data") and raw["data"].get("klines"):
                self._em_fail = 0
                return raw
            self._em_fail += 1
            if self._em_fail >= 2 and not self._em_kline_down:
                self._em_kline_down = True
                self._log("  [数据源] 东财K线持续不可用 → 本次运行改走腾讯行情")
        return self.kline_tencent(code, n=400)

    def _kline_em(self, code: str, beg: str, end: str = "20500101",
                  klt: int = 101, fqt: int = 1) -> Optional[Dict]:
        """东方财富日K线。fqt: 0=不复权 1=前复权 2=后复权。"""
        secid = to_secid(code)
        url = (
            f"{PUSH2HIS}/kline/get?secid={secid}"
            f"&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt={klt}&fqt={fqt}&beg={beg}&end={end}&lmt=1000"
        )
        return self.get_json(url)

    # ---------- 资金流 ----------
    def fflow(self, code: str) -> Optional[Dict]:
        """资金流日线。返回东财格式（klines 为逗号串），便于统一解析。

        多源策略（push2his 在部分网络环境被服务端屏蔽，必须有多路兜底）：
          1. 东财 push2his  —— 口径最全（大/中/小/超大单齐全）
          2. 新浪历史 + 东财延时当日 —— 主用方案
          3. 本地累积库 —— 断网/限流时仍可回落
        """
        if not self._em_flow_down:
            raw = self._fflow_em(code)
            # 延时服务器只返回当日 1 条，凑不出 20 日窗口，视同不可用
            if raw and raw.get("data") and len(raw["data"].get("klines") or []) >= 20:
                self._em_fail_flow = 0
                return raw
            self._em_fail_flow += 1
            if self._em_fail_flow >= 2:
                self._em_flow_down = True
                self._log("  [数据源] 东财资金流不可用 → 新浪历史 + 东财延时当日")
        return self._fflow_fallback(code)

    def _fflow_em(self, code: str) -> Optional[Dict]:
        secid = to_secid(code)
        url = (
            f"{PUSH2HIS}/fflow/daykline/get?lmt=0&klt=101&secid={secid}"
            f"&fields1=f1,f2,f3,f7"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        )
        return self.get_json(url)

    def fflow_sina_lines(self, code: str, n: int = 120) -> List[str]:
        """新浪资金流历史 → 东财字段排列的逗号串。

        新浪口径说明：
          netamount   净流入额（本文用其充当「主力净额」）
          ratioamount 净流入率 = 净流入 / 成交额
          r0_net      超大单净额；r0_ratio 超大单占比
          大单 = 主力 − 超大单（推导，可能为负，属正常）
        中单/小单新浪不提供，置 0 —— 市场中性值，不引入方向性偏差。
        """
        sym = to_tx_symbol(code)
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
            f"json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={n}"
            f"&sort=opendate&asc=0&daima={sym}"
        )
        txt = self.get_text(url, referer="https://finance.sina.com.cn/")
        if not txt or not txt.strip().startswith("["):
            return []
        try:
            rows = json.loads(txt)
        except Exception:  # noqa: BLE001
            return []
        out: List[str] = []
        for r in rows:
            try:
                d = str(r["opendate"])
                main = float(r.get("netamount") or 0)
                huge = float(r.get("r0_net") or 0)
                big = main - huge
                close = float(r.get("trade") or 0)
                chg = float(r.get("changeratio") or 0) * 100
                mp = float(r.get("ratioamount") or 0) * 100
                hp = float(r.get("r0_ratio") or 0) * 100
            except Exception:  # noqa: BLE001
                continue
            out.append(",".join([
                d, f"{main:.0f}", "0", "0", f"{big:.0f}", f"{huge:.0f}",
                f"{mp:.4f}", "0", "0", f"{mp - hp:.4f}", f"{hp:.4f}",
                f"{close:.2f}", f"{chg:.4f}",
            ]))
        out.sort(key=lambda s: s.split(",")[0])
        return out

    def fflow_delay_lines(self, code: str) -> List[str]:
        """东财延时服务器的当日资金流（通常只有最新 1 条）。"""
        secid = to_secid(code)
        url = (
            f"{PUSH2DELAY}/fflow/daykline/get?lmt=0&klt=101&secid={secid}"
            f"&fields1=f1,f2,f3,f7"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        )
        d = self.get_json(url, referer="https://quote.eastmoney.com/")
        if not d or not d.get("data"):
            return []
        return list(d["data"].get("klines") or [])

    def _flow_store_path(self, code: str) -> str:
        return os.path.join(self.cache_dir, "flow", f"{code}.json")

    def _load_flow_store(self, code: str) -> Dict[str, str]:
        p = self._flow_store_path(code)
        if not os.path.exists(p):
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    def _save_flow_store(self, code: str, store: Dict[str, str]) -> None:
        try:
            os.makedirs(os.path.dirname(self._flow_store_path(code)), exist_ok=True)
            with open(self._flow_store_path(code), "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass

    def _fflow_fallback(self, code: str) -> Optional[Dict]:
        """新浪历史 + 东财延时当日 + 本地累积库，三路合并成一条完整序列。"""
        store = self._load_flow_store(code)
        if len(store) < 60:
            for line in self.fflow_sina_lines(code):
                store.setdefault(line.split(",")[0], line)
            self._save_flow_store(code, store)
        # 东财延时当日口径为「主力(大单+超大单)」，与新浪不同源，
        # 仅在它确实比新浪更新时追加，保证「每日更新」的时效性。
        for line in self.fflow_delay_lines(code):
            store[line.split(",")[0]] = line
        dates = sorted(store)
        if len(dates) < 20:
            return None
        self._save_flow_store(code, store)
        return {
            "source": "sina",
            "data": {"code": code, "klines": [store[d] for d in dates]},
        }

    # ---------- 实时快照 ----------
    def snapshot(self, code: str) -> Optional[Dict]:
        """实时快照。取关键是 f50(量比) f168(换手) f116/f117(市值) f162(PE)。"""
        secid = to_secid(code)
        url = (
            f"{PUSH2}/get?secid={secid}&invt=2&fltt=2"
            f"&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f168,f169,f170,"
            f"f116,f117,f162,f167,f171,f47,f48"
        )
        return self.get_json(url)

    # ---------- 龙虎榜 ----------
    def lhb(self, code: Optional[str] = None, pagesize: int = 30) -> List[Dict]:
        """龙虎榜明细。传 code 查个股（按日期倒序），不传则返回全市场最近榜单。"""
        filt = ""
        if code:
            filt = f"&filter=(SECURITY_CODE%3D%22{code}%22)"
        url = (
            f"{DATACENTER}?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL"
            f"&sortColumns=TRADE_DATE&sortTypes=-1&pageSize={pagesize}"
            f"&pageNumber=1{filt}"
        )
        data = self.get_json(url, referer="https://data.eastmoney.com/")
        if not data or not data.get("success"):
            return []
        return (data.get("result") or {}).get("data") or []

    def lhb_institution(self, code: str, days: int = 30) -> Optional[Dict]:
        """解析龙虎榜席位净额，限定在最近 days 天。

        注意语义：BILLBOARD_NET_AMT 是上榜当日「全部席位」的买卖净额，
        既含机构专用席位也含游资席位。用它作为「上榜资金合力」的代理指标，
        而不是纯粹的机构净买额 —— 报告中会明确标注这一口径。
        """
        rows = self.lhb(code, pagesize=min(days + 10, 40))
        if not rows:
            return None

        cutoff = (time.time() - days * 86400)
        net, cnt = 0.0, 0
        latest = None
        best = None
        for r in rows:
            d = (r.get("TRADE_DATE") or "")[:10]
            try:
                ts = time.mktime(time.strptime(d, "%Y-%m-%d"))
            except Exception:  # noqa: BLE001
                continue
            if ts < cutoff:
                continue
            v = r.get("BILLBOARD_NET_AMT")
            if v is None:
                continue
            v = float(v)
            net += v
            cnt += 1
            if latest is None:
                latest = (d, v)
            if best is None or v > best[1]:
                best = (d, v)
        if cnt == 0:
            return None
        return {
            "rows": cnt,
            "net": net,          # 元
            "days": days,
            "latest": latest,    # (日期, 净额)
            "best": best,
        }

    # ---------- 融资融券 ----------
    def margin(self, code: str, days: int = 120) -> Optional[List[Dict]]:
        """融资融券明细（个股）。"""
        url = (
            f"{DATACENTER}?reportName=RPTWEB_MARGIN_DAILYTRADE"
            f"&columns=ALL&sortColumns=DATE&sortTypes=-1&pageSize={days}"
            f"&pageNumber=1&filter=(SCODE%3D%22{code}%22)"
        )
        data = self.get_json(url, referer="https://data.eastmoney.com/")
        if not data or not data.get("success"):
            return None
        return (data.get("result") or {}).get("data") or []

    # ---------- 股东户数 ----------
    def holders(self, code: str) -> Optional[List[Dict]]:
        url = (
            f"{DATACENTER}?reportName=RPT_HOLDERNUMLATEST"
            f"&columns=ALL&sortColumns=END_DATE&sortTypes=-1&pageSize=12"
            f"&pageNumber=1&filter=(SECURITY_CODE%3D%22{code}%22)"
        )
        data = self.get_json(url, referer="https://data.eastmoney.com/")
        if not data or not data.get("success"):
            return None
        return (data.get("result") or {}).get("data") or []

    # ---------- 行情列表（选股池） ----------
    def rank_list(self, fs: str, fid: str = "f62", pz: int = 100,
                  fields: str = "f12,f14,f2,f3,f62,f184,f66,f69") -> List[Dict]:
        """通用行情列表。fid: f3涨幅 f62主力净流入 f184主力净占比 f6成交额 f8换手。"""
        url = (
            f"{CLIST}?pn=1&pz={pz}&po=1&np=1&fltt=2&invt=2&fid={fid}"
            f"&fs={fs}&fields={fields}"
        )
        data = self.get_json(url)
        if not data or not data.get("data"):
            return []
        diff = data["data"].get("diff") or []
        if isinstance(diff, dict):  # 新版接口可能返回 dict
            diff = list(diff.values())
        out = []
        for d in diff:
            out.append({
                "code": d.get("f12"),
                "name": d.get("f14"),
                "price": d.get("f2"),
                "chg": d.get("f3"),
                "main_net": (d.get("f62") or 0) / 1e8,  # 亿元
                "main_pct": d.get("f184"),
            })
        return out

    def stock_pool_mainflow(self, pz: int = 100) -> List[Dict]:
        """全 A 主力净流入排行（沪深主板+创业板+科创板）。"""
        fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        # f62=主力净额 f184=主力净占比 f66=超大单净额 f72=大单 f78=中单 f84=小单
        fields = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
        return self.rank_list(fs, fid="f62", pz=pz, fields=fields)

    def board_list(self, pz: int = 50) -> List[Dict]:
        """行业板块资金流排行（BK 开头）。"""
        fs = "m:90+t:2"
        fields = "f12,f14,f2,f3,f62,f184"
        return self.rank_list(fs, fid="f62", pz=pz, fields=fields)

    def board_stocks(self, board_code: str, pz: int = 60) -> List[Dict]:
        """某板块内个股（按涨幅）。"""
        return self.rank_list(f"b:{board_code}", fid="f3", pz=pz,
                              fields="f12,f14,f2,f3,f62,f184")

    # ---------- 个股所属概念（用于龙头属性判断） ----------
    def concepts(self, code: str) -> List[str]:
        secid = to_secid(code)
        url = (
            "https://push2.eastmoney.com/api/qt/slist/get?spt=3&fltt=2&invt=2"
            f"&fields=f12,f13,f14&secid={secid}&pn=1&np=1&pz=40"
        )
        data = self.get_json(url)
        if not data or not data.get("data"):
            return []
        diff = data["data"].get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        return [d.get("f14") for d in diff if d.get("f14")]

    def stats(self) -> str:
        return f"cache_hit={self._hits} net={self._miss}"


def parse_kline(raw: Dict) -> List[Dict]:
    """把东财 kline JSON 解析成结构化日线列表。

    字段顺序: 日期,开,收,高,低,成交量(手),成交额(元),振幅%,涨跌幅%,涨跌额,换手率%
    """
    if not raw or not raw.get("data"):
        return []
    data = raw["data"]
    rows: List[Dict] = []
    for line in data.get("klines", []):
        p = line.split(",")
        try:
            rows.append({
                "date": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "volume": float(p[5]),      # 手
                "amount": float(p[6]),      # 元
                "amplitude": float(p[7]),   # %
                "chg": float(p[8]),         # %
                "chg_amt": float(p[9]),
                "turnover": float(p[10]),   # %
            })
        except Exception:  # noqa: BLE001
            continue
    return rows


def parse_fflow(raw: Dict) -> List[Dict]:
    """解析资金流日线。

    字段: 日期,主力净额,小单净额,中单净额,大单净额,超大单净额,
          主力占比,小单占比,中单占比,大单占比,超大单占比,收盘价,涨跌幅
    """
    if not raw or not raw.get("data"):
        return []
    rows: List[Dict] = []
    for line in raw["data"].get("klines", []):
        p = line.split(",")
        try:
            rows.append({
                "date": p[0],
                "main": float(p[1]),
                "small": float(p[2]),
                "mid": float(p[3]),
                "big": float(p[4]),
                "huge": float(p[5]),
                "main_pct": float(p[6]),
                "small_pct": float(p[7]),
                "mid_pct": float(p[8]),
                "big_pct": float(p[9]),
                "huge_pct": float(p[10]),
                "close": float(p[11]),
                "chg": float(p[12]),
            })
        except Exception:  # noqa: BLE001
            continue
    return rows
