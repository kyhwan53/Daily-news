"""The weekly email "부동산 주간 브리핑": Claude's note, a week of real estate news, optional MOLIT deal prices
with a 12-month trend chart, and study cards. Runs after build_daily.py in the same workflow every day and
shares state.json, but only sends on [estate_settings].weekday (retrying until Sunday if that run failed).

Usage:
    python build_estate.py                  # dry run: writes out/estate.html (any day)
    python build_estate.py --send           # sends if today is the send day and this week's email has not gone out
    python build_estate.py --send --force   # sends now regardless (manual test)
    python build_estate.py --date 2026-11-20
"""
import argparse
import json
import os
import tomllib
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

import estate
import estate_deals
import indicators
from build_daily import OUT, STATE, load_state, send_email
from sources import CARDS_START, ESTATE, ESTATE_SETTINGS

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
NOTE_STALE_DAYS = 14
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PLOT_H = 64          # trend chart plot height (px)
DOT = 8

HEAD = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
CARD = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
SUB = "font-size:12px;color:#6b7280"
ACCENT = "#b45309"   # amber: distinguishes this email from Daily study's blue
LINK = f"color:{ACCENT};text-decoration:none"
LINKS = [("부동산원 주간 동향 (R-ONE)", "https://www.reb.or.kr/r-one/"), ("국토부 실거래가", "https://rt.molit.go.kr/"),
         ("청약홈", "https://www.applyhome.co.kr/"), ("서울 정비사업 정보몽땅", "https://cleanup.seoul.go.kr/"),
         ("서울부동산정보광장", "https://land.seoul.go.kr/")]


def _toml(name):
    with open(CONTENT / name, "rb") as f:
        return tomllib.load(f)


def study_cards(day):
    """This week's cards: `cards` per email, advancing one email per week."""
    cards = _toml("real_estate.toml")["card"]
    k = ESTATE_SETTINGS.get("cards", 2)
    n = max((day - date.fromisoformat(CARDS_START)).days, 0) // 7 * k
    return [cards[(n + i) % len(cards)] for i in range(k)]


def render_note(day):
    try:
        n = _toml("estate_note.toml")
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"  (estate note unreadable: {e})")
        return ""
    age = (day - date.fromisoformat(n["date"])).days
    stale = (f"<div style='{SUB};margin-top:8px;color:{ACCENT}'>작성 {age}일 전입니다. Claude Code에게 "
             f"\"부동산 코멘트 업데이트해줘\"라고 요청하면 새로 씁니다.</div>") if age >= NOTE_STALE_DAYS else ""
    points = "".join(f"<div style='margin:0 0 9px'><div style='font-size:14px;font-weight:700'>{escape(p['head'])}</div>"
                     f"<div style='font-size:13.5px;color:#374151;line-height:1.6'>{escape(p['text'])}</div></div>"
                     for p in n.get("point", []))
    watch = "".join(f"<tr><td style='padding:2px 10px 2px 0;white-space:nowrap;color:{ACCENT};font-weight:600;vertical-align:top'>"
                    f"{escape(w['when'])}</td><td style='padding:2px 0'>{escape(w['what'])}</td></tr>" for w in n.get("watch", []))
    src = " · ".join(f"<a style='{LINK}' href='{escape(s['url'])}'>{escape(s['label'])}</a>" for s in n.get("source", []))
    return (f"<div style='{HEAD}'>CLAUDE · 이번 주 시장 코멘트</div>"
            f"<div style='{CARD};border-color:#fcd9a8;background:#fffaf2'>"
            f"<div style='font-size:16px;font-weight:700;margin-bottom:2px'>{escape(n['title'])}</div>"
            f"<div style='{SUB};margin-bottom:10px'>{escape(n['date'])} 작성</div>{points}"
            + (f"<div style='font-size:13px;font-weight:700;margin:4px 0 2px'>다가오는 체크 포인트</div>"
               f"<table style='font-size:13px;border-collapse:collapse'>{watch}</table>" if watch else "")
            + (f"<div style='{SUB};margin-top:8px;line-height:1.6'>근거: {src}</div>" if src else "")
            + f"{stale}</div>")


def render_news(sec, items):
    if not items:
        body = f"<div style='{SUB}'>오늘은 새 기사가 없습니다.</div>"
    else:
        rows = []
        for i, a in enumerate(items):
            many = (f" · <b style='color:{ACCENT}'>{a['outlets']}개 매체 보도</b>" if a["outlets"] >= 3
                    else f" · {a['outlets']}개 매체" if a["outlets"] > 1 else "")
            rows.append(f"<div style='padding:8px 0;{'border-top:1px solid #eef0f2' if i else ''}'>"
                        f"<a style='color:#111;text-decoration:none;font-size:15px;font-weight:600;line-height:1.45' "
                        f"href='{escape(a['link'])}'>{escape(a['title'])}</a>"
                        f"<div style='{SUB};margin-top:2px'>{escape(a['outlet'])} · {escape(a['date'])}{many}</div></div>")
        body = "".join(rows)
    return f"<div style='{HEAD}'>{escape(sec['label'])}</div><div style='{CARD};padding:6px 16px'>{body}</div>"


def _deal_row(d, cols):
    return "<tr>" + "".join(f"<td style='padding:4px 8px 4px 0;{s}'>{v}</td>" for v, s in zip(cols, (
        "white-space:nowrap;color:#6b7280", "", "white-space:nowrap", "white-space:nowrap;text-align:right;font-weight:600"))) + "</tr>"


def _watch_row(w):
    last, prev = w["last"], w["prev"]
    size = f"{last['area']:g}㎡" if last else (f"{w['area']}㎡" if w.get("area") else "")
    name = f"{escape(w['label'])}" + (f" <span style='{SUB}'>{size}</span>" if size else "")
    if not last:
        return f"<tr><td style='padding:4px 8px 4px 0;border-top:1px solid #eef0f2'>{name}</td><td colspan='2' style='{SUB};border-top:1px solid #eef0f2'>최근 거래 없음</td></tr>"
    chg = ""
    if prev:
        pct = (last["price"] / prev["price"] - 1) * 100
        color = "#d93025" if pct >= 0 else "#1a73e8"
        chg = f"<span style='color:{color}'>{pct:+.1f}%</span> <span style='{SUB}'>직전 {estate_deals.won(prev['price'])}</span>"
    return (f"<tr><td style='padding:4px 8px 4px 0;border-top:1px solid #eef0f2'>{name}<div style='{SUB}'>"
            f"{escape(last['date'][2:].replace('-', '.'))} · {escape(last['floor'])}층 · {w['n']}건</div></td>"
            f"<td style='text-align:right;font-weight:700;white-space:nowrap;border-top:1px solid #eef0f2'>{estate_deals.won(last['price'])}</td>"
            f"<td style='text-align:right;padding-left:8px;font-size:12.5px;border-top:1px solid #eef0f2'>{chg}</td></tr>")


def _eok(v):
    return f"{v / 10000:.1f}억"


def render_trend(trend, day):
    """12-month dot chart in plain HTML tables (email clients run no JS / SVG / positioning).
    Dots, not bars: prices sit on a zoomed scale, and bars would have to start at zero."""
    cur = f"{day.year}-{day.month:02d}"                    # this month: still being reported
    pts = [p for p in trend if p["v"]]
    full = [p for p in pts if p["ym"] != cur]
    if len(full) < 3:
        return ""
    hi, lo = max(p["v"] for p in pts), min(p["v"] for p in pts)
    span = (hi - lo) or 1
    cells, labels = [], []
    for i, p in enumerate(trend):
        partial = p["ym"] == cur
        dot = ""
        if p["v"]:
            gap = round((hi - p["v"]) / span * (PLOT_H - DOT)) if hi != lo else (PLOT_H - DOT) // 2
            fill = "#fff" if partial else ACCENT
            dot = (f"<div style='height:{gap}px;font-size:0;line-height:0'></div>"
                   f"<div title='{p['ym']} · {_eok(p['v'])} · {p['n']}건{' (집계 중)' if partial else ''}' "
                   f"style='width:{DOT}px;height:{DOT}px;margin:0 auto;border-radius:50%;background:{fill};"
                   f"border:2px solid {ACCENT};box-sizing:border-box;font-size:0;line-height:0'></div>")
        cells.append(f"<td style='height:{PLOT_H}px;vertical-align:top;padding:0;border-bottom:1px solid #e5e7eb'>{dot}</td>")
        m = int(p["ym"][5:])
        show = i == 0 or i == len(trend) - 1 or m in (1, 4, 7, 10)
        text = (f"{p['ym'][2:4]}.{m}" if (m == 1 or i == 0) else f"{m}월") if show else ""
        labels.append(f"<td style='font-size:10.5px;color:#9ca3af;text-align:center;padding-top:3px;white-space:nowrap'>{text}</td>")
    axis = (f"<td rowspan='2' style='width:40px;font-size:10.5px;color:#9ca3af;vertical-align:top;padding-right:4px'>"
            f"<div style='height:{PLOT_H - 6}px'>{_eok(hi)}</div><div>{_eok(lo)}</div></td>")
    first, last = full[0], full[-1]
    chg = (last["v"] / first["v"] - 1) * 100
    color = "#d93025" if chg >= 0 else "#1a73e8"
    done = [p for p in trend if p["ym"] != cur]
    avg = round(sum(p["n"] for p in done) / max(len(done), 1))
    hollow = " · 빈 점 = 이번 달 집계 중" if trend[-1]["ym"] == cur and trend[-1]["v"] else ""
    caption = (f"<div style='font-size:12.5px;margin:4px 0 0'>84㎡ 환산 중위가 <b>{_eok(last['v'])}</b>"
               f" <span style='{SUB}'>({last['ym'][2:].replace('-', '.')})</span> · "
               f"{first['ym'][2:].replace('-', '.')} 대비 <b style='color:{color}'>{chg:+.1f}%</b>"
               f" <span style='{SUB}'>· 월평균 {avg}건{hollow}</span></div>")
    return (f"<table style='width:100%;border-collapse:collapse;table-layout:fixed;margin:4px 0 2px'>"
            f"<tr>{axis}{''.join(cells)}</tr><tr>{''.join(labels)}</tr></table>{caption}")


def render_deals(snap, day):
    """One part per area (영등포 first and with the most rows): new deals in its dongs, then its watched complexes."""
    if not snap or "areas" not in snap:   # "areas" missing: a cache from the old single-area format
        return ""
    months = snap.get("months", 3)
    parts = []
    for i, a in enumerate(snap["areas"]):
        what = f"최근 {months}개월 계약" if a["first"] else "지난 메일 이후 새로 신고"
        head = (f"<div style='font-size:14px;font-weight:700;margin:{'0' if i == 0 else '16px'} 0 4px'>{escape(a['label'])}"
                f"<span style='{SUB};font-weight:400'> · {what} {a['n_new']}건 (최근 {months}개월 총 {a['total']}건)</span></div>")
        if a.get("empty"):
            parts.append(head + f"<div style='{SUB}'>거래 자료가 없습니다. config.toml의 시군구 코드를 확인하세요.</div>")
            continue
        chart = render_trend(a.get("trend", []), day)
        rows = "".join(_deal_row(d, (escape(d["date"][5:].replace("-", "/")), f"{escape(d['apt'])} <span style='{SUB}'>{escape(d['dong'])}</span>",
                                     f"{d['area']:g}㎡ · {escape(d['floor'])}층", estate_deals.won(d["price"]))) for d in a["new"])
        body = (f"<table style='width:100%;font-size:13px;border-collapse:collapse'>{rows}</table>" if rows
                else f"<div style='{SUB}'>새로 신고된 거래가 없습니다.</div>")
        watch = "".join(_watch_row(w) for w in a["watch"])
        if watch:
            body += (f"<div style='font-size:12px;font-weight:700;color:#6b7280;margin:8px 0 2px'>관심 단지</div>"
                     f"<table style='width:100%;font-size:13.5px;border-collapse:collapse'>{watch}</table>")
        sub = f"<div style='font-size:12px;font-weight:700;color:#6b7280;margin:10px 0 2px'>새로 신고된 거래</div>" if chart else ""
        parts.append(head + chart + sub + body)
    note = (f"<div style='{SUB};margin-top:10px;line-height:1.5'>국토부 실거래가 · 전용 59~84㎡형만 · 해제 거래 제외 · "
            "계약 후 30일 내 신고라 최근 거래는 늦게 채워집니다. 84㎡ 환산 중위가 = 그달 거래의 ㎡당 가격 중앙값 × 84</div>")
    return f"<div style='{HEAD}'>실거래 · 관심 지역 시세</div><div style='{CARD}'>{''.join(parts)}{note}</div>"


def _card_link(c):
    if c.get("link"):
        return c["link"], c.get("link_label") or "관련 자료"
    if c.get("term"):
        return f"https://terms.naver.com/search.naver?query={quote(c['term'])}&searchType=text", f"네이버 지식백과: {c['term']}"
    return None, None


def render_cards(cards):
    return f"<div style='{HEAD}'>CLAUDE 추천 · 이번 주 투자 공부</div>" + "".join(render_card(c) for c in cards)


def render_card(c):
    url, label = _card_link(c)
    more = (f"<div style='margin-top:8px'><a style='{LINK};font-size:13px' href='{escape(url)}'>더 알아보기 · {escape(label)} →</a></div>"
            if url else "")
    lines = "".join(f"<li style='margin:0 0 4px'>{escape(x)}</li>" for x in c["body"])
    return (f"<div style='{CARD}'>"
            f"<span style='display:inline-block;font-size:11px;font-weight:600;color:#fff;background:{ACCENT};border-radius:4px;padding:2px 7px'>"
            f"{escape(c['tag'])}</span><div style='font-size:16px;font-weight:700;margin:8px 0 6px'>{escape(c['title'])}</div>"
            f"<ul style='font-size:13.5px;color:#374151;line-height:1.6;margin:0;padding-left:18px'>{lines}</ul>"
            f"<div style='font-size:13px;margin-top:8px;background:#f8f9fa;border-radius:6px;padding:8px 10px'>"
            f"<b>체크</b> · {escape(c['check'])}</div>{more}</div>")


def render_email(day, state, news, deals):
    blocks = []
    for i, sec in enumerate(ESTATE):
        blocks.append(render_news(sec, news.get(sec["key"], [])))
        if i == 0:
            blocks.append(render_deals(deals, day))  # prices right after the 영등포 news
    links = " · ".join(f"<a style='{LINK}' href='{u}'>{escape(t)}</a>" for t, u in LINKS)
    return (
        "<div style='max-width:600px;margin:0 auto;background:#f4f6f8;padding:18px;font-family:Segoe UI,Arial,sans-serif;color:#111'>"
        "<div style='font-size:20px;font-weight:700'>부동산 주간 브리핑</div>"
        f"<div style='{SUB};font-size:13px;margin:2px 0 16px'>{day - timedelta(days=6):%m/%d} ~ {day:%m/%d} · "
        "영등포역 일대 · 사당/이수 · 동탄2 · 수도권 시세 · 투자 체크</div>"
        f"{render_note(day)}{''.join(blocks)}{render_cards(study_cards(day))}"
        f"<div style='font-size:12px;color:#6b7280;margin-top:14px;line-height:1.7'>바로가기: {links}<br>"
        "기사는 Google News 검색 결과의 제목·링크만 사용합니다. 투자 판단의 근거가 아닌 참고용입니다.</div></div>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--skip-if-sent", action="store_true")  # accepted for the workflow; the weekly gate applies anyway
    ap.add_argument("--force", action="store_true")         # send now whatever the weekday (manual test)
    ap.add_argument("--date", default=str(datetime.now(indicators.KST).date()))
    args = ap.parse_args()
    day = date.fromisoformat(args.date)

    state = load_state()
    if args.send and not args.force:
        send_wd = DAYS.index(ESTATE_SETTINGS.get("weekday", "fri"))
        if day.weekday() < send_wd:
            print(f"{day}: the weekly real estate email goes out on {DAYS[send_wd]}, nothing to do")
            return
        week_start = str(day - timedelta(days=day.weekday() - send_wd))   # this week's send day
        if any(d >= week_start for d in state.get("estate_sent", [])):
            print(f"{day}: this week's real estate email already went out, nothing to do")
            return
    news = estate.pick(day, state)
    deals = estate_deals.snapshot(day, state)
    print(f"  deals section: {'included' if deals else 'none (no MOLIT_API_KEY or API failed)'}")
    html = render_email(day, state, news, deals)
    OUT.mkdir(exist_ok=True)
    (OUT / "estate.html").write_text(html, encoding="utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.send:
        # Extra recipients only from the ESTATE_RECIPIENTS secret (comma-separated), never from the public config.
        extra = [a.strip() for a in os.environ.get("ESTATE_RECIPIENTS", "").split(",") if a.strip()]
        send_email(html, day, ["me"] + extra, subject=f"부동산 주간 브리핑 {day}")
        state["estate_sent"] = sorted(set(state.get("estate_sent", [])) | {str(day)})[-14:]
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{day}: real estate briefing, {sum(len(v) for v in news.values())} articles")


if __name__ == "__main__":
    main()
