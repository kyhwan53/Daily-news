"""News English: expressions from content/news_english.toml that actually appear in today's articles and
economy headlines, shown with the sentence they were used in (no paid APIs: plain matching, no generation).

Today's READ articles come first, then the global headlines, then a few extra business feeds so most
days have a match. Picks are cached per day in state.json and skip anything shown in the last 30 days.
"""
import re
import tomllib
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

import indicators

with open(Path(__file__).parent / "content" / "news_english.toml", "rb") as f:
    EXPRS = tomllib.load(f)["expr"]

PER_DAY = 2
REPEAT_DAYS = 30
EXTRA_FEEDS = [("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
               ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
               ("Guardian Business", "https://www.theguardian.com/uk/business/rss")]


def _forms(e):
    """Surface forms to look for: explicit `forms`, else the expression with its first word inflected."""
    if e.get("forms"):
        return {e["en"], *e["forms"]}
    first, _, rest = e["en"].partition(" ")
    stems = {first, first + "s", first + "es", first + "ed", first + "d", first + "ing"}
    if first.endswith("e"):
        stems.add(first[:-1] + "ing")
    if first.endswith("y") and first[-2:-1] not in "aeiou":
        stems |= {first[:-1] + "ies", first[:-1] + "ied"}
    if len(first) <= 4 and first[-1] not in "aeiouwy" and first[-2:-1] in "aeiou":
        stems |= {first + first[-1] + "ed", first + first[-1] + "ing"}  # stop -> stopped
    return {(s + " " + rest).strip() for s in stems}


PATTERNS = [(e, re.compile(r"\b(" + "|".join(sorted(map(re.escape, _forms(e)), key=len, reverse=True)) + r")\b", re.I))
            for e in EXPRS]


def _join(title, body):
    return f"{title}{' ' if title[-1:] in '.?!' else '. '}{body}".strip()


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z‘'\"“])", text) if len(s.strip()) > 20]


def _extra_texts():
    out = []
    for label, url in EXTRA_FEEDS:
        try:
            root = ET.fromstring(indicators._get(url))
        except Exception as e:  # noqa: BLE001 - extra corpus only
            print(f"  (news english feed {label} failed: {e})")
            continue
        for it in root.find("channel").findall("item")[:25]:
            title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
            desc = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))).strip()
            if title and link:
                out.append((_join(title, desc), link, label))
    return out


def pick(day, state, articles, headlines):
    """Up to PER_DAY expressions found in today's texts: [{en, ko, sentence, match, link, source}]."""
    cache = state.setdefault("news_english", {})
    if str(day) in cache:
        return cache[str(day)]
    recent = {x["en"] for d, xs in cache.items() if date.fromisoformat(d) >= day - timedelta(days=REPEAT_DAYS) for x in xs}
    texts = [(_join(a["title"], a["summary"].rstrip("…")), a["link"], a["label"]) for a in articles]
    texts += [(t, link, label) for label, t, link in headlines]
    found = []  # (rank, expression, sentence, matched text, link, source)
    for rank, (text, link, label) in enumerate(texts + _extra_texts()):
        for sent in _sentences(text) or [text]:
            for e, rx in PATTERNS:
                if e["en"] not in recent and (m := rx.search(sent)):
                    found.append((rank, e, sent, m.group(0), link, label))
    # Prefer today's articles, then multi-word expressions (more useful than single words), one per sentence
    found.sort(key=lambda f: (f[0] >= len(articles), " " not in f[1]["en"], f[0]))
    picks, used_sent, used_en = [], set(), set()
    for _, e, sent, match, link, label in found:
        if e["en"] in used_en or sent in used_sent:
            continue
        picks.append({"en": e["en"], "ko": e["ko"], "sentence": sent[:300], "match": match, "link": link, "source": label})
        used_en.add(e["en"])
        used_sent.add(sent)
        if len(picks) == PER_DAY:
            break
    cache[str(day)] = picks
    for old in sorted(cache)[:-60]:
        del cache[old]
    return picks


def render(picks):
    if not picks:
        return ""
    head = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
    items = []
    for p in picks:
        sent = escape(p["sentence"])
        sent = sent.replace(escape(p["match"]), f"<b style='color:#111;background:#fff3c4'>{escape(p['match'])}</b>", 1)
        q = re.sub(r"^to ", "", p["en"])
        items.append(
            f"<div style='font-size:16px;font-weight:700'>{escape(p['en'])} <span style='font-size:14px;font-weight:400;color:#374151'>· {escape(p['ko'])}</span></div>"
            f"<div style='font-size:14px;color:#4b5563;border-left:3px solid #e3e6ea;padding-left:10px;margin:6px 0'>{sent}</div>"
            f"<div style='font-size:13px'><a style='color:#6b7280;text-decoration:none' href='{escape(p['link'])}'>기사 원문 · {escape(p['source'])} →</a>"
            f" &nbsp;·&nbsp; <a style='color:#2f6fed;text-decoration:none' href='https://youglish.com/pronounce/{quote(q)}/english'>▶ 발음 (YouGlish)</a></div>"
        )
    sep = "<div style='border-top:1px solid #eef0f2;margin:12px 0'></div>"
    return f"<div style='{head}'>NEWS ENGLISH · 오늘 기사 속 표현</div><div style='{card}'>{sep.join(items)}</div>"
