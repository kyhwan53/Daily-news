"""Apartment sale prices from the MOLIT real transaction API (data.go.kr, free key) for the real estate email.

Optional: without the MOLIT_API_KEY environment variable (GitHub Secret) the block is simply left out.
API: 국토교통부_아파트 매매 실거래가 상세 자료 (getRTMSDataSvcAptTradeDev), one call per district and contract month.
Prices in the API are in 만원. Contracts must be reported within 30 days, so the latest month fills in slowly.
"""
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

from sources import ESTATE_DEALS

API = ("https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
       "?serviceKey={key}&LAWD_CD={code}&DEAL_YMD={ym}&numOfRows=1000&pageNo={page}")


def _key():
    k = "".join(c for c in os.environ.get("MOLIT_API_KEY", "") if c.isprintable() and not c.isspace())
    return k if "%" in k else urllib.parse.quote(k, safe="")  # accept both the encoded and the decoded key


def _t(it, *names):
    for n in names:
        v = it.findtext(n)
        if v and v.strip():
            return v.strip()
    return ""


def parse(xml_bytes, code):
    root = ET.fromstring(xml_bytes)
    rc = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
    if rc not in ("00", "000"):
        raise RuntimeError(f"MOLIT API error {rc}: {root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg')}")
    out = []
    for it in root.iter("item"):
        try:
            d = {
                "code": code,
                "apt": _t(it, "aptNm", "아파트"),
                "dong": _t(it, "umdNm", "법정동"),
                "area": round(float(_t(it, "excluUseAr", "전용면적")), 1),
                "floor": _t(it, "floor", "층"),
                "price": int(_t(it, "dealAmount", "거래금액").replace(",", "")),
                "date": str(date(int(_t(it, "dealYear", "년")), int(_t(it, "dealMonth", "월")), int(_t(it, "dealDay", "일")))),
                "cancel": bool(_t(it, "cdealType", "해제여부")),
            }
        except ValueError:
            continue
        d["id"] = "|".join(str(d[k]) for k in ("code", "apt", "area", "floor", "date", "price"))
        out.append(d)
    return out, int(root.findtext(".//totalCount") or 0)


def _fetch(code, ym, key):
    deals, page = [], 1
    while True:
        url = API.format(key=key, code=code, ym=ym, page=page)
        for i in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "daily-news/1.0"}), timeout=30) as r:
                    raw = r.read()
                break
            except Exception:  # noqa: BLE001
                if i == 2:
                    raise
                time.sleep(3 * (i + 1))
        got, total = parse(raw, code)
        deals += got
        if not got or len(deals) >= total:
            return deals
        page += 1


def _months(day, n):
    y, m = day.year, day.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def _norm(s):
    return s.replace(" ", "").lower()


def _area_ok(d, area):
    return area is None or abs(d["area"] - area) < 3


def summarize(deals, cfg, seen):
    """Pure part (testable without the API): per area, new deals in its dongs + one line per watched complex."""
    live = [d for d in deals if not d["cancel"]]
    out = []
    for a in cfg.get("area", []):
        dongs = a.get("dongs", [])
        near = [d for d in live if d["code"] == a["code"] and (not dongs or any(d["dong"].startswith(x) for x in dongs))]
        new = sorted((d for d in near if d["id"] not in seen), key=lambda d: (d["date"], d["price"]), reverse=True)
        watch = []
        for w in a.get("watch", []):
            named = sorted((d for d in near if _norm(w["apt"]) in _norm(d["apt"])), key=lambda d: d["date"], reverse=True)
            # the chosen size if it traded, otherwise any size (shown with its real area)
            mine = [d for d in named if _area_ok(d, w.get("area"))] or named
            last = mine[0] if mine else None
            prev = next((d for d in mine[1:] if abs(d["area"] - last["area"]) < 1), None) if last else None
            watch.append({"label": w["label"], "area": w.get("area"), "last": last, "prev": prev, "n": len(mine)})
        out.append({"label": a["label"], "total": len(near), "new": new[:a.get("show", 3)], "n_new": len(new),
                    "first": not seen, "watch": watch,
                    "empty": not any(d["code"] == a["code"] for d in deals)})  # no deal at all: wrong code?
    return out


def snapshot(day, state):
    """Today's deal summary (cached per day), or None when there is no key or the API fails."""
    cache = state.setdefault("estate_deals", {})
    if str(day) in cache:
        return cache[str(day)]
    if not os.environ.get("MOLIT_API_KEY") or not ESTATE_DEALS.get("area"):
        return None
    key = _key()
    codes = sorted({a["code"] for a in ESTATE_DEALS["area"]})
    deals = []
    for code in codes:
        try:
            for ym in _months(day, ESTATE_DEALS.get("months", 3)):
                deals += _fetch(code, ym, key)
        except Exception as e:  # noqa: BLE001 - that district is shown as empty, the rest still go out
            print(f"  (MOLIT deals for {code} failed: {type(e).__name__}: {e})")
    if not deals:
        return None
    seen = set(state.get("estate_deals_seen", []))
    out = {"areas": summarize(deals, ESTATE_DEALS, seen), "months": ESTATE_DEALS.get("months", 3)}
    state["estate_deals_seen"] = sorted(seen | {d["id"] for d in deals})[-8000:]
    cache.clear()
    cache[str(day)] = out
    print(f"  MOLIT: {len(deals)} deals from {len(codes)} districts")
    return out


def won(p):
    """만원 -> '14억 5,000' / '9,800만'."""
    if p >= 10000:
        return f"{p // 10000}억" + (f" {p % 10000:,}" if p % 10000 else "")
    return f"{p:,}만"
