"""Daily study cards (business English phrase, Japanese kana + travel phrase) and the Sunday weekly recap.

Cards come from content/*.toml and advance one step per calendar day from CARDS_START, so every run on
the same day shows the same card and nothing needs to be stored. The business English phrase is only shown in
the email. Japanese is studied on a page (docs/study.html, built from templates/study.html): letters, travel
phrases and a daily quiz.
"""
import json
import random
import re
import tomllib
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

from indicators import COMMODITIES, WORLD
from sources import BASE_URL, CARDS_START

CONTENT = Path(__file__).parent / "content"
KANA_PER_DAY = 3

with open(CONTENT / "business_english.toml", "rb") as f:
    PHRASES = tomllib.load(f)["phrase"]
with open(CONTENT / "japanese.toml", "rb") as f:
    _jp = tomllib.load(f)
KANA = [("히라가나", k, r) for k, r in _jp["hiragana"]] + [("가타카나", k, r) for k, r in _jp["katakana"]]
JP_PHRASES = _jp["phrase"]

HEAD = "font-size:12px;font-weight:700;letter-spacing:.06em;color:#6b7280;margin:16px 0 6px"
CARD = "background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin:0 0 10px"
LINK = "text-decoration:none;font-size:13px"
ROOT = Path(__file__).parent
STUDY_URL = BASE_URL.rstrip("/") + "/study.html"


def _n(day):
    return max((day - date.fromisoformat(CARDS_START)).days, 0)


def english(day):
    return PHRASES[_n(day) % len(PHRASES)]


def kana(day):
    start = _n(day) * KANA_PER_DAY % len(KANA)
    return [KANA[(start + i) % len(KANA)] for i in range(KANA_PER_DAY)]


def japanese(day):
    return {"kana": kana(day), "phrase": JP_PHRASES[_n(day) % len(JP_PHRASES)]}


def _learned(n):
    """Kana taught on days 0..n, in teaching order, without repeats."""
    out = []
    for i in range(n + 1):
        for j in range(KANA_PER_DAY):
            k = KANA[(i * KANA_PER_DAY + j) % len(KANA)]
            if k not in out:
                out.append(k)
    return out


def _kana_question(rng, item, kind, learned):
    script, glyph, ro = item
    same = [x for x in KANA if x[0] == script and x != item]
    pool = [x for x in learned if x[0] == script and x != item]
    rng.shuffle(pool)
    rng.shuffle(same)
    pick = (lambda x: x[2]) if kind == "kana2ro" else (lambda x: x[1])
    answer = pick(item)
    wrong = []
    for x in pool + same:  # prefer letters already taught, then the rest of the same script
        if pick(x) != answer and pick(x) not in wrong:
            wrong.append(pick(x))
        if len(wrong) == 2:
            break
    choices = wrong + [answer]
    rng.shuffle(choices)
    prompt = "이 글자는 어떻게 읽을까요?" if kind == "kana2ro" else f"“{ro}” 소리가 나는 글자는?"
    return {"prompt": prompt, "big": glyph if kind == "kana2ro" else "", "choices": choices,
            "answer": choices.index(answer), "explain": f"{glyph} = {ro}"}


def _phrase_question(rng, n):
    p = JP_PHRASES[n % len(JP_PHRASES)]
    taught = [JP_PHRASES[i % len(JP_PHRASES)] for i in range(n)]
    others = [x for x in taught + JP_PHRASES if x is not p]
    rng.shuffle(others)
    kind = "jp2ko" if n % 2 == 0 else "ko2ro"
    pick = (lambda x: x["ko"]) if kind == "jp2ko" else (lambda x: x["ro"])
    answer = pick(p)
    wrong = []
    for x in others:
        if pick(x) != answer and pick(x) not in wrong:
            wrong.append(pick(x))
        if len(wrong) == 2:
            break
    choices = wrong + [answer]
    rng.shuffle(choices)
    if kind == "jp2ko":
        prompt, big = "무슨 뜻일까요?", f"{p['jp']}\n{p['ro']}"
    else:
        prompt, big = "일본어로 어떻게 말할까요?", p["ko"]
    return {"prompt": prompt, "big": big, "choices": choices, "answer": choices.index(answer),
            "explain": f"{p['jp']} ({p['ro']}) = {p['ko']}", "phrase": p["jp"]}


def jp_quiz(day):
    """Today's Japanese quiz: 3 new letters, 1 review letter (from day 2), 1 travel phrase. Same questions every
    time for the same day (seeded), so the email, tomorrow's answer line and the quiz page always agree."""
    n = _n(day)
    rng = random.Random(f"jq-{n}")
    learned = _learned(n)
    today = kana(day)
    qs = [_kana_question(rng, item, ("kana2ro", "ro2kana", "kana2ro")[i], learned) for i, item in enumerate(today)]
    older = [x for x in _learned(n - 1)] if n > 0 else []
    older = [x for x in older if x not in today]
    if older:
        qs.append(_kana_question(rng, rng.choice(older), rng.choice(["kana2ro", "ro2kana"]), learned))
    qs.append(_phrase_question(rng, n))
    return qs


CIRCLED = "①②③"


def write_study_page(day=None):
    """docs/study.html: the review page, with every card's data embedded (the page works out the day itself)."""
    last = _n(day) + 3 if day else 0  # quiz for every day up to a few days ahead of the build
    data = {"start": CARDS_START, "kanaPerDay": KANA_PER_DAY, "kana": KANA, "jpPhrases": JP_PHRASES,
            "quiz": [jp_quiz(date.fromisoformat(CARDS_START) + timedelta(days=i)) for i in range(last + 1)]}
    page = (ROOT / "templates" / "study.html").read_text(encoding="utf-8")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "study.html").write_text(page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)), encoding="utf-8")


def _review_links(tab, day, what):
    prev = f"{STUDY_URL}#{tab}-{day - timedelta(days=1)}"
    links = f"<a style='{LINK};color:#6b7280' href='{escape(STUDY_URL)}#{tab}-{day}'>지금까지 배운 {what} 모두 보기 →</a>"
    if _n(day) > 0:
        links = f"<a style='{LINK};color:#6b7280' href='{escape(prev)}'>◀ 어제 {what}</a> &nbsp;·&nbsp; " + links
    return f"<div style='margin-top:8px'>{links}</div>"


def _youglish(en):
    # Search text: drop "(...)", "...", leading "to " and end punctuation so YouGlish finds real clips.
    q = re.sub(r"\(.*?\)|\.\.\.|…|[?.!]$", "", en).strip()
    q = re.sub(r"^to ", "", q).strip(" ,")
    return f"https://youglish.com/pronounce/{quote(q)}/english"


def _translate(jp):
    return f"https://translate.google.com/?sl=ja&tl=ko&op=translate&text={quote(jp)}"


def render_english(p):
    return (
        f"<div style='{HEAD}'>BUSINESS ENGLISH · 오늘의 표현</div><div style='{CARD}'>"
        f"<div style='font-size:17px;font-weight:700'>{escape(p['en'])}</div>"
        f"<div style='font-size:14px;color:#374151;margin:2px 0 8px'>{escape(p['ko'])}</div>"
        f"<div style='font-size:14px;font-style:italic;color:#4b5563;border-left:3px solid #e3e6ea;padding-left:10px'>{escape(p['ex'])}</div>"
        f"<div style='margin-top:8px'><a style='{LINK};color:#2f6fed' href='{escape(_youglish(p['en']))}'>▶ 실제 영상 속 발음 듣기 (YouGlish)</a></div>"
        "<div style='font-size:12px;color:#6b7280;margin-top:6px'>오늘 회의나 메일에서 한 번 써 보세요.</div></div>"
    )


def _quiz_block(i, q):
    big = "".join(f"<div style='font-size:{26 if len(line) < 8 else 18}px;line-height:1.35'>{escape(line)}</div>"
                  for line in q["big"].split("\n") if line)
    opts = "&nbsp;&nbsp;&nbsp;".join(f"<b>{CIRCLED[j]}</b> {escape(c)}" for j, c in enumerate(q["choices"]))
    return (f"<div style='margin:0 0 12px'><div style='font-size:13px;color:#6b7280'>Q{i} · {escape(q['prompt'])}</div>"
            f"{big}<div style='font-size:{18 if len(q['choices'][0]) < 8 else 14}px;margin-top:2px'>{opts}</div></div>")


def render_japanese(card, day):
    """Email: a taste of the quiz (2 of today's 5 questions), yesterday's answers, and a button to the quiz page,
    where tapping an answer shows right/wrong at once (Gmail blocks buttons and scripts inside the email)."""
    qs = jp_quiz(day)
    sample = [qs[0], qs[-1]]  # one new letter, one travel phrase
    yesterday = ""
    if _n(day) > 0:
        ans = " &nbsp;·&nbsp; ".join(f"Q{i} {CIRCLED[q['answer']]} {escape(q['choices'][q['answer']])}"
                                     for i, q in enumerate(jp_quiz(day - timedelta(days=1)), 1))
        yesterday = (f"<div style='border-top:1px solid #eef0f2;margin-top:10px;padding-top:8px;font-size:12px;color:#6b7280'>"
                     f"어제 5문제 정답 &nbsp;{ans}</div>")
    return (
        f"<div style='{HEAD}'>JAPANESE · {escape(card['kana'][0][0])} 0단계 퀴즈</div><div style='{CARD}'>"
        + "".join(_quiz_block(i, q) for i, q in enumerate(sample, 1))
        + f"<div style='margin:6px 0 0'><a style='{LINK};color:#fff;background:#c2410c;border-radius:6px;padding:8px 14px;display:inline-block' "
          f"href='{escape(STUDY_URL)}#jq-{day}'>오늘의 일본어 퀴즈 풀기 ({len(qs)}문제 · 2분) →</a></div>"
        + yesterday
        + f"{_review_links('jp', day, '글자·표현')}</div>"
    )


def _num(v):
    return float(re.sub(r"[^\d.\-]", "", v))


def _change(first, last):
    """Week change between two stored value strings: rates in bp, spreads in bp, levels in %."""
    a, b = _num(first), _num(last)
    if last.endswith("bp"):
        return f"{b - a:+.0f}bp"
    if last.endswith("%"):
        return f"{(b - a) * 100:+.0f}bp"
    return f"{(b / a - 1) * 100:+.2f}%"


GLOBAL_NAMES = {n for _, n in WORLD} | {c[-1] for c in COMMODITIES} | {"VIX (공포 지수)"}


def _bar(name, first, last):
    pct = (_num(last) / _num(first) - 1) * 100
    w = min(abs(pct) / 5 * 50, 50)  # +-5% fills half the track
    color = "#d93025" if pct >= 0 else "#1a73e8"
    side = "left:50%" if pct >= 0 else f"left:{50 - w:.1f}%"
    return (f"<tr><td style='padding:2px 8px 2px 0;white-space:nowrap'>{escape(name)}</td>"
            f"<td style='width:55%'><div style='position:relative;height:8px;background:#f1f3f5;border-radius:2px'>"
            f"<div style='position:absolute;top:0;{side};width:{w:.1f}%;height:8px;background:{color};border-radius:2px'></div></div></td>"
            f"<td style='text-align:right;padding-left:8px;color:{color};white-space:nowrap'>{pct:+.1f}%</td></tr>")


def render_weekly(state, day):
    """Sunday recap of the last 7 days (day-6 .. day): market moves, articles, reports, phrases, kana."""
    days = [str(day - timedelta(days=i)) for i in range(6, -1, -1)]
    sub = "font-size:13px;font-weight:700;margin:12px 0 4px"
    li = "margin:0 0 3px"
    parts = []

    hist = state.get("markets_history", {})
    seen = [hist[d] for d in days if d in hist]
    if len(seen) >= 2:
        first = {n: next(h[n] for h in seen if n in h) for n in seen[-1]}
        bars = [n for n in seen[-1] if n in GLOBAL_NAMES]
        if bars:
            parts.append(f"<div style='{sub}'>세계 증시·원자재 주간 등락</div>"
                         f"<table style='width:100%;font-size:12.5px;border-collapse:collapse'>{''.join(_bar(n, first[n], seen[-1][n]) for n in bars)}</table>")
        rows = "".join(
            f"<tr><td style='padding:2px 0'>{escape(n)}</td><td style='text-align:right'>{escape(seen[-1][n])}</td>"
            f"<td style='text-align:right;padding-left:12px;color:#6b7280'>{escape(_change(first[n], seen[-1][n]))}</td></tr>"
            for n in seen[-1] if n not in GLOBAL_NAMES
        )
        if rows:
            parts.append(f"<div style='{sub}'>국내·금리·환율 주간 변화</div><table style='width:100%;font-size:13px'>{rows}</table>")

    def links(key):
        items = [x for d in days for x in state.get(key, {}).get(d, [])]
        return "".join(f"<li style='{li}'><a style='color:#111' href='{escape(x['link'])}'>{escape(x['title'])}</a>"
                       f" <span style='color:#6b7280'>· {escape(x['label'])}</span></li>" for x in items)

    for key, title in (("articles", "이번 주 기사"), ("reports", "이번 주 리포트")):
        if html := links(key):
            parts.append(f"<div style='{sub}'>{title}</div><ul style='font-size:13px;margin:0;padding-left:18px'>{html}</ul>")

    start = max(day - timedelta(days=6), date.fromisoformat(CARDS_START))
    week = [start + timedelta(days=i) for i in range((day - start).days + 1)]
    if week:
        jp = " ".join(f"{k}({r})" for d in week for _, k, r in kana(d))
        parts.append(f"<div style='{sub}'>이번 주 일본어 글자</div><div style='font-size:15px'>{escape(jp)}</div>")

    if not parts:
        return ""
    return (f"<div style='{HEAD}'>WEEKLY · 한 주 정리 ({escape(days[0][5:])} ~ {escape(days[-1][5:])})</div>"
            f"<div style='{CARD};border-color:#c7d2fe;background:#f8f9ff'>{''.join(parts)}</div>")
