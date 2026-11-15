"""Real estate news for the separate "부동산 브리핑" email.

News comes from Google News RSS search (free, no key; title / outlet / link only, articles are not copied).
Every query of a section is searched, off-topic titles are dropped, and articles about the same event are
grouped by title similarity: the number of outlets in a group is the main importance signal. A story that was
already shown on an earlier day (by any outlet) is not shown again. Picks are cached per day in state.json.
"""
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from sources import ESTATE, ESTATE_SETTINGS

GN = "https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko"
UA = {"User-Agent": "Mozilla/5.0 (daily-news/1.0)"}
SIMILAR = 0.6          # share of title bigrams two titles must have in common to count as the same story
SEEN_DAYS = 10         # a story shown within this many days is not shown again
KEEP_DAYS = 14         # daily picks kept in state.json (for the Sunday recap)
MEMBERS = 8            # titles per story compared against earlier stories


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def fetch(query, days):
    root = ET.fromstring(_get(GN.format(urllib.parse.quote(f"{query} when:{days}d"))))
    out = []
    for it in root.find("channel").findall("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        outlet = (src.text or "").strip() if src is not None else ""
        if outlet.startswith("http"):  # some outlets have no name, only a URL
            outlet = re.sub(r"^https?://(www\.)?|/.*$", "", outlet)
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3].strip()
        pub = it.findtext("pubDate")
        if title and link:
            out.append({"title": title, "outlet": outlet, "link": link,
                        "pub": parsedate_to_datetime(pub) if pub else None})
    return out


SHARED_WORDS = 3       # ... or this many distinctive words in common ("신통기획", "독산", "대림")
STOP = {"서울", "서울시", "수도권", "경기", "아파트", "아파트값", "부동산", "집값", "정부", "재개발", "재건축", "단독", "종합",
        "속보", "상승", "하락", "추가", "최대", "올해", "내년", "지난해", "시장", "가격", "주택"}
PARTICLE = re.compile(r"(으로|에서|에게|까지|부터|은|는|이|가|을|를|에|의|도|로|와|과|만)$")


def _grams(title):
    t = re.sub(r"^(\[[^\]]*\]|\([^)]*\)|【[^】]*】)\s*", "", title)    # [단독], (종합) ...
    words = set()
    for w in re.split(r"[^0-9A-Za-z가-힣%.]+", t):
        if m := re.match(r"\d[\d.,]*", w):
            words.add("#" + m.group().rstrip(".,"))      # "10곳서" / "1681가구" -> the number itself
        elif len(w) >= 2:
            w = PARTICLE.sub("", w) if len(w) > 2 else w
            if w not in STOP:
                words.add(w)
    flat = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
    return ({flat[i:i + 2] for i in range(len(flat) - 1)}, words)


def similar(a, b):
    (ga, wa), (gb, wb) = (_grams(x) if isinstance(x, str) else x for x in (a, b))
    return bool(ga and gb) and (len(ga & gb) / min(len(ga), len(gb)) >= SIMILAR or len(wa & wb) >= SHARED_WORDS)


def _ok(title, sec):
    topic = sec.get("topic", ESTATE_SETTINGS.get("topic", []))
    exclude = ESTATE_SETTINGS.get("exclude", []) + sec.get("exclude", [])
    must = sec.get("must", [])
    return ((not must or any(w in title for w in must)) and (not topic or any(w in title for w in topic))
            and not any(w in title for w in exclude))


def _clusters(sec, now):
    """Same-story groups for one section, best first."""
    items, links = [], set()
    for q in sec["queries"]:
        try:
            got = fetch(q, sec.get("days", 2))
        except Exception as e:  # noqa: BLE001 - one failing query must not break the section
            print(f"  (estate query '{q}' failed: {e})")
            continue
        for a in got:
            if a["link"] not in links and _ok(a["title"], sec):
                links.add(a["link"])
                items.append(a)
    items.sort(key=lambda a: a["pub"].timestamp() if a["pub"] else 0, reverse=True)
    groups = []
    for a in items:
        g = _grams(a["title"])
        for c in groups:  # same story if it matches any title already in the group
            if any(similar(g, m) for m in c["members"]):
                c["items"].append(a)
                c["members"].append(g)
                break
        else:
            groups.append({"members": [g], "items": [a]})
    major = ESTATE_SETTINGS.get("major", [])
    boost = sec.get("boost", [])
    for c in groups:
        c["outlets"] = len({a["outlet"] for a in c["items"]})
        newest = c["items"][0]["pub"]
        fresh = newest is not None and now - newest < timedelta(hours=24)
        # representative: a major outlet if one covered it, otherwise the newest
        c["rep"] = next((a for a in c["items"] if a["outlet"] in major), c["items"][0])
        c["score"] = c["outlets"] + 2 * sum(w in c["rep"]["title"] for w in boost) + (1 if fresh else 0)
    groups.sort(key=lambda c: (c["score"], c["items"][0]["pub"].timestamp() if c["items"][0]["pub"] else 0), reverse=True)
    return groups


def pick(day, state):
    """{section key: [items]} for `day`, cached so every run on the same day shows the same news."""
    cache = state.setdefault("estate", {})
    if str(day) in cache:
        return cache[str(day)]
    now = datetime.now().astimezone()
    seen = state.setdefault("estate_seen", [])   # [[date, title], ...]
    since = str(day - timedelta(days=SEEN_DAYS))
    old = [_grams(t) for d, t in seen if since <= d < str(day)]
    shown = []
    picks = {}
    for sec in ESTATE:
        out = []
        for c in _clusters(sec, now):
            if len(out) >= sec.get("count", 3):
                break
            mine = c["members"][:MEMBERS]
            if any(similar(m, g) for m in mine for g in old + shown):
                continue
            r = c["rep"]
            shown += mine
            out.append({"title": r["title"], "link": r["link"], "outlet": r["outlet"], "outlets": c["outlets"],
                        "date": r["pub"].astimezone(now.tzinfo).strftime("%m/%d") if r["pub"] else "",
                        "others": sorted({a["outlet"] for a in c["items"]} - {r["outlet"]})[:4]})
        picks[sec["key"]] = out
        print(f"  [{sec['label']}] {len(out)} picked")
    seen += [[str(day), x["title"]] for v in picks.values() for x in v]
    state["estate_seen"] = [s for s in seen if s[0] >= since][-600:]
    cache[str(day)] = picks
    for d in sorted(cache)[:-KEEP_DAYS]:
        del cache[d]
    return picks
