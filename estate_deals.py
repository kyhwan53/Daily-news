"""Apartment sale prices from the MOLIT real transaction API (data.go.kr, free key) for the real estate email.

Optional: without the MOLIT_API_KEY environment variable (GitHub Secret) the block is simply left out.
API: 국토교통부_아파트 매매 실거래가 상세 자료 (getRTMSDataSvcAptTradeDev), one call per district and contract month.
Prices in the API are in 만원. Contracts must be reported within 30 days, so the latest month fills in slowly.
Only sizes between min_area and max_area (전용 ㎡) are used. A 12-month trend per area is the median price per ㎡
converted to an 84㎡ unit, so 59㎡ and 84㎡ deals can be pooled into one line. The current month is
left out of the trend: with the 30-day reporting lag its few early deals would distort the scale.
"""
import hashlib
import os
import statistics
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


def _hid(d):
    return hashlib.sha1(d["id"].encode()).hexdigest()[:12]


def _match(w, d):
    return _norm(w["apt"]) == _norm(d["apt"]) if w.get("exact") else _norm(w["apt"]) in _norm(d["apt"])


def trend(deals, months):
    """[{ym, v, n}] oldest first: median price per ㎡ × 84 for each contract month (v None when nothing traded)."""
    out = []
    for ym in reversed(months):
        per = [d["price"] / d["area"] for d in deals if d["date"][:7].replace("-", "") == ym]
        out.append({"ym": f"{ym[:4]}-{ym[4:]}", "v": round(statistics.median(per) * 84) if per else None, "n": len(per)})
    return out


def summarize(deals, cfg, seen, day):
    """Pure part (testable without the API): per area, new deals in its dongs, watched complexes and the trend."""
    lo, hi = cfg.get("min_area", 0), cfg.get("max_area", 1000)
    recent = set(_months(day, cfg.get("months", 3)))
    live = [d for d in deals if not d["cancel"] and lo <= d["area"] <= hi]
    out = []
    for a in cfg.get("area", []):
        dongs = a.get("dongs", [])
        district = [d for d in live if d["code"] == a["code"] and d["date"][:7].replace("-", "") in recent]
        area_all = [d for d in live if d["code"] == a["code"] and (not dongs or any(d["dong"].startswith(x) for x in dongs))]
        near = [d for d in area_all if d["date"][:7].replace("-", "") in recent]
        new = sorted((d for d in near if _hid(d) not in seen), key=lambda d: (d["date"], d["price"]), reverse=True)
        watch = []
        for w in a.get("watch", []):
            # by name: anywhere in the district, not only the dongs above
            named = sorted((d for d in district if _match(w, d)), key=lambda d: d["date"], reverse=True)
            # the chosen size if it traded, otherwise another size in the range (shown with its real area)
            mine = [d for d in named if _area_ok(d, w.get("area"))] or named
            last = mine[0] if mine else None
            prev = next((d for d in mine[1:] if abs(d["area"] - last["area"]) < 1), None) if last else None
            watch.append({"label": w["label"], "area": w.get("area"), "last": last, "prev": prev, "n": len(mine)})
        out.append({"label": a["label"], "total": len(near), "new": new[:a.get("show", 3)], "n_new": len(new),
                    "first": not seen, "watch": watch, "trend": trend(area_all, _months(day, cfg.get("trend_months", 12) + 1)[1:]),
                    "empty": not any(d["code"] == a["code"] for d in deals)})  # no deal at all: wrong code?
    return out


def snapshot(day, state):
    """This run's deal summary (cached per day), or None when there is no key or the API fails."""
    cache = state.setdefault("estate_deals", {})
    if str(day) in cache and "areas" in cache[str(day)] and "trend" in cache[str(day)]["areas"][0]:
        return cache[str(day)]
    if not os.environ.get("MOLIT_API_KEY") or not ESTATE_DEALS.get("area"):
        return None
    key = _key()
    codes = sorted({a["code"] for a in ESTATE_DEALS["area"]})
    n_months = max(ESTATE_DEALS.get("months", 3), ESTATE_DEALS.get("trend_months", 12) + 1)  # +1: this month (not in the trend)
    deals = []
    for code in codes:
        try:
            for ym in _months(day, n_months):
                deals += _fetch(code, ym, key)
        except Exception as e:  # noqa: BLE001 - that district is shown as empty, the rest still go out
            print(f"  (MOLIT deals for {code} failed: {type(e).__name__}: {e})")
    if not deals:
        return None
    state.pop("estate_deals_seen", None)          # old format (full ids)
    seen = set(state.get("estate_deals_seen2", []))
    out = {"areas": summarize(deals, ESTATE_DEALS, seen, day), "months": ESTATE_DEALS.get("months", 3)}
    recent = set(_months(day, ESTATE_DEALS.get("months", 3)))
    # only deals inside the recent window can still be "new" later, so only they are remembered
    state["estate_deals_seen2"] = sorted({_hid(d) for d in deals if d["date"][:7].replace("-", "") in recent})
    cache.clear()
    cache[str(day)] = out
    print(f"  MOLIT: {len(deals)} deals from {len(codes)} districts, {n_months} months")
    return out


def won(p):
    """만원 -> '14억 5,000' / '9,800만'."""
    if p >= 10000:
        return f"{p // 10000}억" + (f" {p % 10000:,}" if p % 10000 else "")
    return f"{p:,}만"
