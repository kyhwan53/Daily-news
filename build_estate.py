"""The separate morning email "부동산 브리핑": Claude's note, real estate news, optional MOLIT deal prices,
and a daily study card. Runs after build_daily.py in the same workflow and shares state.json.

Usage:
    python build_estate.py              # dry run: writes out/estate.html
    python build_estate.py --send       # also sends (GMAIL_USER / GMAIL_APP_PASSWORD; extra: ESTATE_RECIPIENTS)
    python build_estate.py --date 2026-11-15
"""
import argparse
import json
import os
import tomllib
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import estate
import estate_deals
import indicators
from build_daily import OUT, STATE, load_state, send_email
from sources import CARDS_START, ESTATE

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
NOTE_STALE_DAYS = 14

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


def study_card(day):
    cards = _toml("real_estate.toml")["card"]
    return cards[max((day - date.fromisoformat(CARDS_START)).days, 0) % len(cards)]


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


def render_deals(snap):
    if not snap:
        return ""
    parts = []
    nb = snap.get("nearby")
    if nb:
        rows = "".join(_deal_row(d, (escape(d["date"][5:].replace("-", "/")), f"{escape(d['apt'])} <span style='{SUB}'>{escape(d['dong'])}</span>",
                                     f"{d['area']:g}㎡ · {escape(d['floor'])}층", estate_deals.won(d["price"]))) for d in nb["new"])
        what = f"최근 {snap.get('months', 3)}개월 계약" if nb["first"] else "어제 이후 새로 신고된 거래"
        parts.append(f"<div style='font-size:13px;font-weight:700;margin:0 0 4px'>{escape(nb['label'])} · {what} {nb['n_new']}건"
                     f"<span style='{SUB};font-weight:400'> (최근 {snap.get('months', 3)}개월 총 {nb['total']}건)</span></div>"
                     + (f"<table style='width:100%;font-size:13px;border-collapse:collapse'>{rows}</table>" if rows
                        else f"<div style='{SUB}'>새로 신고된 거래가 없습니다.</div>"))
    wrows = []
    for w in snap.get("watch", []):
        name = f"{escape(w['label'])}" + (f" <span style='{SUB}'>{w['area']}㎡</span>" if w.get("area") else "")
        last, prev = w["last"], w["prev"]
        if not last:
            wrows.append(f"<tr><td style='padding:4px 8px 4px 0'>{name}</td><td colspan='2' style='{SUB}'>최근 거래 없음</td></tr>")
            continue
        chg = ""
        if prev:
            pct = (last["price"] / prev["price"] - 1) * 100
            color = "#d93025" if pct >= 0 else "#1a73e8"
            chg = f"<span style='color:{color}'>{pct:+.1f}%</span> <span style='{SUB}'>직전 {estate_deals.won(prev['price'])}</span>"
        wrows.append(f"<tr><td style='padding:4px 8px 4px 0;border-top:1px solid #eef0f2'>{name}<div style='{SUB}'>"
                     f"{escape(last['date'][2:].replace('-', '.'))} · {escape(last['floor'])}층 · {w['n']}건</div></td>"
                     f"<td style='text-align:right;font-weight:700;white-space:nowrap;border-top:1px solid #eef0f2'>{estate_deals.won(last['price'])}</td>"
                     f"<td style='text-align:right;padding-left:8px;font-size:12.5px;border-top:1px solid #eef0f2'>{chg}</td></tr>")
    if wrows:
        parts.append(f"<div style='font-size:13px;font-weight:700;margin:12px 0 4px'>관심 단지 최근 거래</div>"
                     f"<table style='width:100%;font-size:13.5px;border-collapse:collapse'>{''.join(wrows)}</table>")
    note = f"<div style='{SUB};margin-top:8px'>국토부 실거래가 · 계약 후 30일 내 신고라 최근 거래는 늦게 채워집니다 · 해제 거래 제외 · 단위 만원→억</div>"
    return f"<div style='{HEAD}'>실거래 · 시세</div><div style='{CARD}'>{''.join(parts)}{note}</div>"


def render_card(c):
    lines = "".join(f"<li style='margin:0 0 4px'>{escape(x)}</li>" for x in c["body"])
    return (f"<div style='{HEAD}'>CLAUDE 추천 · 오늘의 투자 공부</div><div style='{CARD}'>"
            f"<span style='display:inline-block;font-size:11px;font-weight:600;color:#fff;background:{ACCENT};border-radius:4px;padding:2px 7px'>"
            f"{escape(c['tag'])}</span><div style='font-size:16px;font-weight:700;margin:8px 0 6px'>{escape(c['title'])}</div>"
            f"<ul style='font-size:13.5px;color:#374151;line-height:1.6;margin:0;padding-left:18px'>{lines}</ul>"
            f"<div style='font-size:13px;margin-top:8px;background:#f8f9fa;border-radius:6px;padding:8px 10px'>"
            f"<b>체크</b> · {escape(c['check'])}</div></div>")


def render_weekly(state, day):
    days = [str(day - timedelta(days=i)) for i in range(7, 0, -1)]  # the past 7 days (today's news is below anyway)
    parts = []
    for sec in ESTATE:
        items = [a for d in days for a in state.get("estate", {}).get(d, {}).get(sec["key"], [])]
        if items:
            li = "".join(f"<li style='margin:0 0 3px'><a style='color:#111' href='{escape(a['link'])}'>{escape(a['title'])}</a>"
                         f" <span style='color:#6b7280'>· {escape(a['date'])}</span></li>" for a in items)
            parts.append(f"<div style='font-size:13px;font-weight:700;margin:10px 0 4px'>{escape(sec['label'])}</div>"
                         f"<ul style='font-size:13px;margin:0;padding-left:18px'>{li}</ul>")
    if not parts:
        return ""
    return (f"<div style='{HEAD}'>WEEKLY · 이번 주 부동산 기사 ({escape(days[0][5:])} ~ {escape(days[-1][5:])})</div>"
            f"<div style='{CARD};border-color:#fcd9a8;background:#fffaf2'>{''.join(parts)}</div>")


def render_email(day, state, news, deals):
    blocks = []
    for i, sec in enumerate(ESTATE):
        blocks.append(render_news(sec, news.get(sec["key"], [])))
        if i == 0:
            blocks.append(render_deals(deals))  # prices right after the 영등포 news
    links = " · ".join(f"<a style='{LINK}' href='{u}'>{escape(t)}</a>" for t, u in LINKS)
    return (
        "<div style='max-width:600px;margin:0 auto;background:#f4f6f8;padding:18px;font-family:Segoe UI,Arial,sans-serif;color:#111'>"
        "<div style='font-size:20px;font-weight:700'>부동산 브리핑</div>"
        f"<div style='{SUB};font-size:13px;margin:2px 0 16px'>{day} · 영등포역 일대 · 수도권 시세 · 투자 체크</div>"
        f"{render_weekly(state, day) if day.weekday() == 6 else ''}"
        f"{render_note(day)}{''.join(blocks)}{render_card(study_card(day))}"
        f"<div style='font-size:12px;color:#6b7280;margin-top:14px;line-height:1.7'>바로가기: {links}<br>"
        "기사는 Google News 검색 결과의 제목·링크만 사용합니다. 투자 판단의 근거가 아닌 참고용입니다.</div></div>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--skip-if-sent", action="store_true")
    ap.add_argument("--date", default=str(datetime.now(indicators.KST).date()))
    args = ap.parse_args()
    day = date.fromisoformat(args.date)

    state = load_state()
    if args.skip_if_sent and str(day) in state.get("estate_sent", []):
        print(f"{day}: real estate email already sent, nothing to do")
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
        send_email(html, day, ["me"] + extra, subject=f"부동산 브리핑 {day}")
        state["estate_sent"] = sorted(set(state.get("estate_sent", [])) | {str(day)})[-14:]
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{day}: real estate briefing, {sum(len(v) for v in news.values())} articles")


if __name__ == "__main__":
    main()
