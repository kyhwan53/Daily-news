"""Build today's listening queue, the personal podcast feed (docs/feed.xml) and the morning email.

Usage:
    python build_daily.py              # dry run: writes docs/feed.xml and out/email.html
    python build_daily.py --send       # also sends the email (needs GMAIL_USER / GMAIL_APP_PASSWORD)
    python build_daily.py --date 2026-10-12
"""
import argparse
import json
import os
import smtplib
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime
import re
from html import escape, unescape
from pathlib import Path

import indicators
import cards
import news_english
import portfolio
import reports
from sources import ARTICLES, BASE_URL, FEED_DAYS, MAX_MINUTES, MEETINGS, RECIPIENT, REPORTS, SCHEDULE, SOURCES

ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
DOCS = ROOT / "docs"
OUT = ROOT / "out"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def fetch_episodes(rss):
    req = urllib.request.Request(rss, headers={"User-Agent": "daily-news/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    eps = []
    show = (root.find("channel").findtext("title") or "").strip()
    for item in root.find("channel").findall("item"):
        enc = item.find("enclosure")
        if enc is None:
            continue
        pub = item.findtext("pubDate")
        eps.append({
            "guid": item.findtext("guid") or enc.get("url"),
            "show": show,
            "title": (item.findtext("title") or "").strip(),
            "audio": enc.get("url"),
            "mime": enc.get("type") or "audio/mpeg",
            "page": item.findtext("link") or "",
            "minutes": parse_minutes(item.findtext(ITUNES + "duration")),
            "pub": parsedate_to_datetime(pub) if pub else None,
        })
    return eps


def parse_minutes(raw):
    if not raw:
        return None
    try:
        parts = [int(float(p)) for p in raw.split(":")]
    except ValueError:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return round(secs / 60)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"used": {}, "days": {}}


def pick(source, eps, used):
    pool = [e for e in eps if e["guid"] not in used]
    pool.sort(key=lambda e: e["pub"] or datetime.min.astimezone(), reverse=(source["mode"] == "newest"))
    return pool[0] if pool else None


def build_queue(day, state):
    if str(day) in state["days"]:  # idempotent: re-running the same day keeps the same queue
        return state["days"][str(day)]
    labels = {s["key"]: s for s in SOURCES}
    queue, total = [], 0
    for key in SCHEDULE[day.weekday()]:
        src = labels[key]
        used = set(state["used"].setdefault(key, []))
        ep = pick(src, fetch_episodes(src["rss"]), used)
        if ep is None:
            continue
        if total + (ep["minutes"] or 0) > MAX_MINUTES and queue:
            continue
        total += ep["minutes"] or 0
        state["used"][key].append(ep["guid"])
        queue.append({"key": key, "label": src["label"], **{k: ep[k] for k in ("guid", "show", "title", "audio", "mime", "page", "minutes")},
                      "pub": ep["pub"].isoformat() if ep["pub"] else ""})
    state["days"][str(day)] = queue
    return queue


def write_feed(state, today):
    days = sorted(state["days"])[-FEED_DAYS:]
    ET.register_namespace("itunes", ITUNES[1:-1])
    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "Daily news"
    ET.SubElement(ch, "link").text = BASE_URL
    ET.SubElement(ch, "language").text = "en"
    ET.SubElement(ch, "description").text = "Personal daily listening queue (links to original podcasts)."
    for d in reversed(days):
        stamp = datetime.fromisoformat(d).astimezone()
        for i, ep in enumerate(state["days"][d]):
            it = ET.SubElement(ch, "item")
            ET.SubElement(it, "title").text = f"[{d[5:]} {i + 1}] {ep['label']} | {ep['title']}"
            ET.SubElement(it, "guid", isPermaLink="false").text = f"{d}:{ep['guid']}"
            ET.SubElement(it, "pubDate").text = format_datetime(stamp.replace(hour=6 - i if i < 6 else 0))
            ET.SubElement(it, "link").text = ep["page"] or BASE_URL
            ET.SubElement(it, "enclosure", url=ep["audio"], type=ep["mime"], length="0")
            if ep["minutes"]:
                ET.SubElement(it, ITUNES + "duration").text = str(ep["minutes"] * 60)
    DOCS.mkdir(exist_ok=True)
    ET.indent(rss)
    ET.ElementTree(rss).write(DOCS / "feed.xml", encoding="utf-8", xml_declaration=True)


def fetch_articles(rss):
    req = urllib.request.Request(rss, headers={"User-Agent": "daily-news/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for item in root.find("channel").findall("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        summary = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))).strip()
        pub = item.findtext("pubDate")
        out.append({
            "guid": item.findtext("guid") or link,
            "title": title,
            "link": link,
            "summary": summary[:240] + ("…" if len(summary) > 240 else ""),
            "pub": parsedate_to_datetime(pub) if pub else None,
        })
    return out


# Not a story to read: live blogs, video/audio, quizzes, galleries, newsletters
SKIP_TITLE = re.compile(r"\blive\b|as it happened|\bvideo\b|\bwatch:|\bquiz\b|in pictures|newsletter|podcast|crossword", re.I)
SKIP_LINK = re.compile(r"/live/|/videos?/|/audio/|/sounds/|/av/|/gallery/|/picture/|/commentisfree/", re.I)
OPINION_TITLE = re.compile(r" \| [A-Z][\w'’.-]+( [A-Z][\w'’.-]+)+$")  # Guardian columns: "Headline | Author Name"
BUSINESS_LINK = re.compile(r"/(business|money|economy|markets)/", re.I)
STOPWORDS = {"says", "said", "with", "from", "that", "this", "will", "have", "over", "after", "into", "about", "what",
             "their", "they", "more", "than", "were", "been", "amid", "first", "year", "years", "news", "could", "would"}
FRESH_HOURS = 36
# Importance signal only (never linked): a top story counts once per feed below that runs the same story
SIGNAL_FEEDS = {
    "top": ["https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en"],
    "business": ["https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
                 "https://www.cnbc.com/id/100003114/device/rss/rss.html"],
}


def _words(title):
    title = re.sub(r" - [^-]+$", "", title)  # Google News appends " - Publisher"
    return {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOPWORDS}


def _same_story(a, b):
    return len(_words(a) & _words(b)) >= 2


def build_articles(day, state):
    """One article per section: the most important unseen story, not the newest.

    Importance = how many other outlets in the section run the same story (plus Google News US/UK top stories for
    top news, Google News Business and CNBC for business), then the outlet's own placement in its feed. Live
    blogs, video, quizzes, opinion columns and items older than 36 h are skipped. Top news draws on both the front pages and the world desks. Business is picked first so top news can exclude business stories and the same story; environment
    then excludes both. Shown in config order with top news first.
    """
    cache = state.setdefault("articles", {})
    if str(day) in cache:
        return cache[str(day)]
    seen = set(state.setdefault("articles_used", []))
    sections, feeds = {}, {}
    for src in ARTICLES:
        sections.setdefault(src["section"], []).append(src)
        try:
            feeds[src["key"]] = fetch_articles(src["rss"])
        except Exception as e:  # noqa: BLE001 - one dead outlet must not break the whole email
            print(f"  (article source {src['key']} failed: {e})")
    send_time = datetime(day.year, day.month, day.day, 6, tzinfo=indicators.KST)
    business_links = {a["link"] for src in sections.get("business", []) for a in feeds.get(src["key"], [])}
    signals = {}
    for name, urls in SIGNAL_FEEDS.items():
        for url in urls:
            try:
                signals.setdefault(name, []).append([a["title"] for a in fetch_articles(url)[:20]])
            except Exception as e:  # noqa: BLE001 - signal only
                print(f"  (signal feed failed: {url[:40]}: {e})")

    def choose(name, avoid):
        outlets = sections[name]
        lead = outlets[day.toordinal() % len(outlets)]["key"]  # ties go to the day's outlet, for variety
        cands = []
        for src in outlets:
            for rank, a in enumerate(feeds.get(src["key"], [])):
                if a["guid"] in seen or SKIP_TITLE.search(a["title"]) or SKIP_LINK.search(a["link"]) or OPINION_TITLE.search(a["title"]):
                    continue
                if any(_same_story(a["title"], t) for t in avoid):
                    continue
                if name == "top" and (a["link"] in business_links or BUSINESS_LINK.search(a["link"])):
                    continue
                fresh = a["pub"] is None or send_time - timedelta(hours=FRESH_HOURS) <= a["pub"] <= send_time + timedelta(hours=6)
                others = [[b["title"] for b in feeds.get(o["key"], [])[:20]] for o in outlets if o["key"] != src["key"]]
                others += signals.get(name, [])
                coverage = sum(any(_same_story(a["title"], t) for t in titles) for titles in others)
                cands.append(((not fresh, -coverage, rank, src["key"] != lead), src, a))
        if not cands:
            return None
        _, src, a = min(cands, key=lambda c: c[0])
        seen.add(a["guid"])
        return {"label": src["label"], "section": name, **{k: a[k] for k in ("guid", "title", "link", "summary")}}

    chosen = {}
    for name in sorted(sections, key=lambda n: (n != "business", n != "top")):  # business, top, then the rest
        if pick := choose(name, [c["title"] for c in chosen.values()]):
            chosen[name] = pick
    picks = [chosen[n] for n in sorted(sections, key=lambda n: n != "top") if n in chosen]  # top news first
    state["articles_used"] = sorted(seen)[-500:]
    cache[str(day)] = picks
    return picks


def render_email(queue, articles, day, markets_html="", reports_html="", cards_html="", weekly_html="", global_html="",
                 portfolio_html="", earnings_html=""):
    total = sum(e["minutes"] or 0 for e in queue)
    card = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
    tag = "display:inline-block;font-size:11px;font-weight:600;color:#fff;background:#2f6fed;border-radius:4px;padding:2px 7px"
    link = "color:#2f6fed;text-decoration:none"
    listen = "".join(
        f"<div style='{card}'><span style='{tag}'>{escape(e['label'])}</span>"
        f"<div style='font-size:16px;font-weight:600;margin:8px 0 4px'>{escape(e['title'])}</div>"
        f"<div style='font-size:13px;color:#6b7280'>{str(e['minutes']) + ' min' if e['minutes'] else 'length n/a'}</div>"
        f"<div style='font-size:13px;margin-top:8px'>"
        f"{escape(e.get('show') or '')}"
        f"{' &nbsp;|&nbsp; <a style=' + repr(link) + ' href=' + repr(escape(e['page'])) + '>Page &amp; transcript</a>' if e['page'] else ''}"
        "</div></div>"
        for e in queue
    )
    def article_cards(items):
        return "".join(
            f"<div style='{card}'><span style='{tag.replace('#2f6fed', '#0f9d58')}'>{escape(a['label'])}</span>"
            f"<div style='font-size:16px;font-weight:600;margin:8px 0 4px'>"
            f"<a style='color:#111;text-decoration:none' href='{escape(a['link'])}'>{escape(a['title'])}</a></div>"
            f"<div style='font-size:13px;color:#4b5563;line-height:1.5'>{escape(a['summary'])}</div>"
            f"<div style='font-size:13px;margin-top:8px'><a style='{link}' href='{escape(a['link'])}'>Read the article →</a></div></div>"
            for a in items
        )
    read = article_cards([a for a in articles if a.get("section") != "business"])
    english_article = article_cards([a for a in articles if a.get("section") == "business"])
    # Two blocks under banners: STUDY (the English business article is reading practice, next to the phrase
    # cards drawn from articles) and ECONOMY (data, reports, earnings; earnings last)
    def banner(text, color):
        return (f"<div style='font-size:15px;font-weight:700;color:#fff;background:{color};border-radius:8px;"
                f"padding:8px 14px;margin:26px 0 4px'>{text}</div>")
    study = banner("STUDY · 영어·일본어 공부", "#2f6fed") + english_article + cards_html if (english_article or cards_html) else ""
    economy = (banner("ECONOMY · 경제", "#1f2937") + global_html + reports_html + markets_html + earnings_html) if (
        global_html or reports_html or markets_html or earnings_html) else ""
    return (
        "<div style='max-width:600px;margin:0 auto;background:#f4f6f8;padding:18px;"
        "font-family:Segoe UI,Arial,sans-serif;color:#111'>"
        f"<div style='font-size:20px;font-weight:700'>Daily Study</div>"
        f"<div style='font-size:13px;color:#6b7280;margin:2px 0 16px'>{day}</div>"
        f"{weekly_html}"
        + (("<div style='font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px'>LISTEN"
            f" · about {total} min</div>{listen}") if queue else "")
        + "<div style='font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px'>READ</div>"
        f"{read or '<div style=color:#6b7280>No new articles today.</div>'}"
        f"{study}"
        f"{economy}"
        f"{portfolio_html}"
        "<div style='font-size:12px;color:#6b7280;margin-top:14px;line-height:1.5'>"
        "Tip: while reading, note 3 phrases you could reuse in a meeting or presentation.</div></div>"
    )


def send_email(html, day, to, subject=None):
    # Strip BOM / zero-width chars / whitespace that sneak in when secrets are pasted or piped.
    clean = lambda v: "".join(c for c in v if c.isprintable() and not c.isspace() and c != "﻿")  # noqa: E731
    user, pw = clean(os.environ["GMAIL_USER"]), clean(os.environ["GMAIL_APP_PASSWORD"])
    msg = EmailMessage()
    to = [a if a != "me" else (RECIPIENT or user) for a in to]
    msg["Subject"] = subject or f"Daily study {day}"
    msg["From"], msg["To"] = user, ", ".join(to)
    msg.set_content("HTML email")
    msg.add_alternative(html, subtype="html")
    # Gmail sometimes drops logins from cloud IPs: retry, alternating SSL(465) and STARTTLS(587).
    last = None
    for attempt in range(1, 7):
        use_ssl = attempt % 2 == 1
        try:
            ctx = ssl.create_default_context()
            if use_ssl:
                s = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30)
            else:
                s = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
                s.starttls(context=ctx)
            with s:
                s.login(user, pw)
                s.send_message(msg)
            print(f"  email sent (attempt {attempt}, {'465 SSL' if use_ssl else '587 STARTTLS'})")
            return
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused):
            raise  # wrong credentials / address: retrying will not help
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  email attempt {attempt} failed: {type(e).__name__}: {e}")
            time.sleep(10 * attempt)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--skip-if-sent", action="store_true")  # automatic runs: the first one of the day sends, later ones stop
    ap.add_argument("--date", default=str(datetime.now(indicators.KST).date()))  # KST, also on UTC runners
    args = ap.parse_args()
    day = date.fromisoformat(args.date)

    state = load_state()
    if args.skip_if_sent and str(day) in state.get("sent", []):
        print(f"{day}: email already sent, nothing to do")
        return
    queue = build_queue(day, state)
    articles = build_articles(day, state)
    korea = reports.pick(REPORTS, day, state)
    write_feed(state, day)
    markets = indicators.snapshot(day, state.setdefault("calendar_cache", {}), MEETINGS)
    hist = state.setdefault("markets_history", {})  # for the Sunday recap
    hist[str(day)] = {n: v for key in ("korea", "yields", "fx", "world", "commodities") if markets.get(key) for n, v, _, _ in markets[key][1]}
    for old in sorted(hist)[:-21]:
        del hist[old]
    cards.write_study_page(day)
    news_en = news_english.pick(articles, markets.get("headlines") or [])
    cards_html = (cards.render_english(cards.english(day)) + news_english.render(news_en)
                  + cards.render_japanese(cards.japanese(day), day))
    weekly_html = cards.render_weekly(state, day) if day.weekday() == 6 else ""
    global_html = indicators.render_global(markets, reports.render(korea, "overnight"))
    parts = (queue, articles, day, indicators.render(markets), reports.render(korea), cards_html, weekly_html, global_html)
    earnings_html = indicators.render_earnings(markets)
    html = render_email(*parts, earnings_html=earnings_html)
    # Portfolio buy candidates go only into the owner's copy (never to EXTRA_RECIPIENTS, never printed: public repo)
    mine_html = portfolio.render(portfolio.load(day))
    html_me = render_email(*parts, portfolio_html=mine_html, earnings_html=earnings_html) if mine_html else html
    print(f"  portfolio section: {'included (owner only)' if mine_html else 'none'}")
    OUT.mkdir(exist_ok=True)
    (OUT / "email.html").write_text(html_me, encoding="utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.send:
        # Extra recipients come from the EXTRA_RECIPIENTS secret (comma-separated), never from the public config.
        extra = [a.strip() for a in os.environ.get("EXTRA_RECIPIENTS", "").split(",") if a.strip()]
        if mine_html and extra:
            send_email(html_me, day, ["me"])
            send_email(html, day, extra)
        else:
            send_email(html_me, day, ["me"] + extra)
        state["sent"] = sorted(set(state.get("sent", [])) | {str(day)})[-14:]
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{day}: {len(queue)} items, {sum(e['minutes'] or 0 for e in queue)} min")
    for e in queue:
        print(f"  [{e['label']}] {e['title']} ({e['minutes']} min)")
    for a in articles:
        print(f"  [READ {a['label']}] {a['title']}")
    for r in korea:
        print(f"  [REPORT {r['label']}] {r['title']}")


if __name__ == "__main__":
    main()
