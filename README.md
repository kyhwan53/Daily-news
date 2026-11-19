# Daily news

매일 아침 **영어 리스닝(비즈니스/환경공학 R&D 중심) + 외신 읽기 + 국내 리포트 + 시장 지표**를 메일로 보내고,
같은 에피소드를 모은 **개인 팟캐스트 피드**(`docs/feed.xml`)를 GitHub Pages로 게시하는 도구입니다.
외부 팟캐스트의 오디오는 재호스팅하지 않고 원본 URL만 가리킵니다. 외부 유료 API는 쓰지 않습니다(추가 비용 0원).

## 목표
- 영어: OPIc AL, 비즈니스(환경공학 R&D 회의/발표/협상) 영어. 우선순위는 **리스닝**(출퇴근용). 스피킹은 후순위.
- 일본어: 기초 지식이 없어 팟캐스트는 효과가 없음 → 2026-11-05 편성에서 빼고, 메일의 0단계 카드(가나 3자 + 여행 표현 1개)로 대체.

## 구조
| 파일 | 역할 |
|---|---|
| `config.toml` | **사용자가 고치는 유일한 설정**: 팟캐스트 소스, 외신 기사 소스, 요일별 편성, 수신/게시 주소 |
| `sources.py` | config.toml 로드/검증 |
| `build_daily.py` | 오늘의 큐 선정 → `docs/feed.xml` 생성 → 메일 HTML 생성/발송 |
| `cards.py` | 업무 영어 표현·일본어 0단계 카드(하루 한 칸씩) + 일요일 주간 정리 |
| `templates/study.html` | 복습 페이지 틀. 매일 실행 때 카드 데이터를 넣어 `docs/study.html`로 게시 (메일의 "어제 표현 / 모두 보기" 링크) |
| `news_english.py` | 기사 속 업무 영어: `content/news_english.toml`의 표현 중 그날 기사·헤드라인에 실제로 나온 것을 원문 문장과 함께 하루 최대 2개 |
| `content/*.toml` | 카드 내용: 업무 영어 표현(`business_english.toml`), 가나·여행 표현(`japanese.toml`). 직접 추가 가능 |
| `reports.py` | 국내 리포트(네이버 증권 리서치의 증권사 리포트, 한국은행 RSS) 선정 → 메일 섹션 |
| `manage.py` | 소스 추가/삭제/점검 CLI |
| `portfolio.py` | 포트폴리오(비공개 저장소 portfolio_managing)의 알파 매수 후보 상위 10개 → **본인에게 가는 메일에만** 넣는 섹션. 로그·저장소에는 남기지 않음 |
| `build_estate.py` | **부동산 주간 브리핑**(별도 메일, 금요일): Claude 코멘트 + 부동산 뉴스 + 실거래·가격 추이 그래프 + 투자 공부 카드 |
| `estate.py` | 부동산 뉴스 선정 (Google News RSS 검색 → 주제 필터 → 같은 사건 묶기 → 보도 매체 수로 순위) |
| `estate_deals.py` | 국토부 아파트 실거래가(선택, `MOLIT_API_KEY`): 관심 지역(영등포역·사당/이수·동탄2)별 12개월 추이 + 새 신고 거래 + 관심 단지 최근 거래 |
| `content/real_estate.toml` | 주거용 부동산 투자 공부 카드 (하루 1장, 카드마다 '더 알아보기' 링크: 공식 사이트 또는 네이버 지식백과) |
| `content/estate_note.toml` | Claude의 시장 코멘트 (메일 맨 위). Claude Code에게 "부동산 코멘트 업데이트해줘"로 갱신 |
| `docs/feed.xml` | GitHub Pages로 게시되는 개인 피드 (안드로이드 AntennaPod 등에서 구독) |
| `state.json` | 이미 쓴 에피소드/기사 기록 (git 제외, 로컬 전용) |
| `out/email.html` | 마지막으로 만든 메일 미리보기 (git 제외) |

피드 주소: `https://kyhwan53.github.io/Daily-news/feed.xml`

## 새 컴퓨터에서 이식하기
1. **Python 3.11+ 설치** (표준 라이브러리만 사용, `pip install` 불필요). Windows는 python.org 설치본 권장.
   Microsoft Store 별칭(`WindowsApps\python.exe`)은 동작하지 않을 수 있으니 실제 경로로 실행하세요.
2. **Git 설치** 후 클론:
   ```
   git clone https://github.com/kyhwan53/Daily-news.git
   cd Daily-news
   ```
   첫 `git push` 때 브라우저 로그인 창이 뜹니다 (GitHub `kyhwan53` 계정).
3. **Gmail 앱 비밀번호를 환경변수로 설정** (파일에 저장 금지, 공개 저장소임):
   ```
   [Environment]::SetEnvironmentVariable("GMAIL_USER","<본인 Gmail 주소>","User")
   [Environment]::SetEnvironmentVariable("GMAIL_APP_PASSWORD","<16자리 앱 비밀번호>","User")
   ```
   앱 비밀번호는 Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호에서 발급. 새 터미널을 열어야 반영됩니다.
4. **동작 확인**:
   ```
   python manage.py check          # 모든 피드가 살아 있는지
   python build_daily.py           # 메일 미리보기만 생성 (발송 안 함) → out/email.html
   python build_daily.py --send    # 실제 발송
   ```
5. **(선택) 진행 상태 이어받기**: `state.json`은 git에 올라가지 않습니다. 이전 컴퓨터의 `state.json`을 복사해 오면
   중복 방지 기록이 이어집니다. 없으면 처음부터 시작합니다.
6. **매일 자동 실행은 GitHub Actions가 합니다** (`.github/workflows/daily.yml`, 매일 06:00 KST = 21:00 UTC, PC 불필요).
   저장소 Settings → Secrets and variables → Actions에 `GMAIL_USER`, `GMAIL_APP_PASSWORD`를 등록해야 동작합니다.
   (선택) `PORTFOLIO_TOKEN`: portfolio_managing 저장소만 선택한 fine-grained 토큰(권한 Actions: Read and write).
   있으면 06:00에 portfolio_managing을 매수 후보 모드로 실행해 결과를 받아 본인 메일에만 넣습니다(약 1분 추가). 없거나 실패하면 그 섹션만 빠집니다.
   GitHub 예약 실행은 2~6시간씩 늦게 시작하므로, 실제 06:00 발송은 외부 스케줄러(cron-job.org, 무료)가 05:50 KST에
   API로 `scheduled=true` 실행을 요청해서 맞춥니다. 내장 cron은 예비용이고, 그날 이미 보냈으면 건너뜁니다(`state.json`의 `sent`).
   수동 실행: 저장소 Actions 탭 → Daily news → Run workflow (체크박스를 비워 두면 즉시 발송).
   실행 결과(`docs/feed.xml`, `state.json`)는 봇이 저장소에 commit합니다.

> **로컬에서 `--send`로 직접 보내지 마세요.** Actions가 `state.json`을 저장소에서 관리하므로, 로컬에서 실행하면 상태가 어긋납니다.
> 로컬 테스트는 `python build_daily.py`(발송 없음)만 쓰고, 그 뒤 `git checkout state.json docs/feed.xml`로 되돌리거나 `git pull`로 최신 상태를 받으세요.

## 시장 지표 / 경제 일정 (`indicators.py`)
메일 하단에 코스피·코스닥·국고채 3년(네이버 증권 비공식 JSON), 미국채 2Y/10Y/30Y 금리와 10Y-2Y 스프레드(US Treasury 공식 CSV), USD/KRW·JPY·EUR(Frankfurter/ECB),
앞으로 3일간 주요 통화(USD/EUR/GBP/JPY/CNY)의 고영향 경제지표 일정(Forex Factory 주간 JSON, KST 환산)을 넣습니다.
세계 경제 칸에는 밤사이 미국 시장 요약(증권사 미국 마감 시황, `slot = "overnight"`), 세계 증시 7개(미·유럽·일·중·홍콩),
원자재·위험 지표(WTI, 브렌트, 금, 구리, VIX; 네이버 증권 비공식 JSON), 중앙은행 금리(뉴욕 연준 공식 API의 연준 목표·실효금리,
한국은행 통화정책 RSS의 기준금리, 다음 회의일은 `config.toml`의 `[central_banks]`), 해외 경제 헤드라인(CNBC Economy, 연준 통화정책
보도자료 RSS; 제목과 링크만)을 넣습니다.
모든 블록은 실패해도 메일이 나가도록 개별 처리됩니다. 경제 일정 서버는 요청 제한(429)이 엄격해서
마지막 성공 결과를 `state.json`의 `calendar_cache`에 보관하고 실패 시 그것을 씁니다.

## 부동산 주간 브리핑 (`build_estate.py`, 별도 메일 "부동산 주간 브리핑 YYYY-MM-DD", 매주 금요일)
워크플로는 매일 돌지만 이 단계는 `[estate_settings].weekday`(금)에만 보냅니다. 금요일 실행이 실패하면 주말 안에 다시 시도하고,
그 주에 이미 보냈으면 건너뜁니다(`state.json`의 `estate_sent`). Daily study와는 서로 영향이 없습니다.
1. **CLAUDE · 이번 주 시장 코멘트**: `content/estate_note.toml`. 유료 API 금지 원칙에 따라 자동 생성하지 않고, Claude Code 세션에서
   "부동산 코멘트 업데이트해줘"라고 요청하면 최근 기사(`state.json`의 `estate`)와 웹 검색으로 새로 씁니다. 작성 14일이 지나면 메일에 안내가 붙습니다.
2. **뉴스 4칸** (`config.toml`의 `[[estate]]`, 모두 최근 7일): 영등포역 일대 재개발/시세(6건 — 비중 최대),
   관심 지역 사당/이수·동탄2(4건, 지역마다 1건씩 먼저 `spread`), 수도권 아파트 시세(5건), 투자 체크 · 정책/대출/세금/청약(5건).
   칸마다 검색어(`queries`)를 모두 Google News RSS로 검색 → 주제어(`topic`)·지역(`must`)·제외어(`exclude`) 필터 →
   제목이 비슷한 기사를 한 사건으로 묶고 보도 매체 수 + `boost` 단어 + 24시간 이내로 점수 → 상위 `count`개. 최근 10일 안에 나온 사건은 다시 싣지 않습니다.
3. **실거래 · 관심 지역 시세** (`MOLIT_API_KEY`): data.go.kr "국토교통부_아파트 매매 실거래가 상세 자료" 키(GitHub Secret).
   지역(`[[estate_deals.area]]`: 영등포역 일대 · 사당/이수역 · 동탄2신도시)마다
   - **12개월 가격 추이 그래프**: 그달 거래의 ㎡당 가격 중앙값 × 84 = "84㎡ 환산 중위가"를 점으로 표시(HTML 표로 그려 Gmail에서도 보임, 이번 달은 빈 점 = 집계 중)
   - **지난 메일 이후 새로 신고된 거래**(`show`: 영등포 8 / 나머지 3), **관심 단지 최근 거래**(이름 일부 또는 `exact = true`면 전체 일치, 구 전체에서 찾음)
   - 전용 59~84㎡형만(`min_area`/`max_area`). 동탄은 2026.2 분구된 화성시 동탄구 코드(41597).
4. **CLAUDE 추천 · 이번 주 투자 공부**: `content/real_estate.toml` 카드 주 2장(`cards`) + 카드마다 더 알아보기 링크.

미리보기: `python build_estate.py` → `out/estate.html` (발송 안 함, 끝나면 `git checkout state.json`).
수동 테스트 발송: Actions → Daily news → Run workflow에서 **estate_only** 체크(요일 무관하게 이 메일만 발송, Daily study는 안 보냄).
추가 수신자는 GitHub Secret `ESTATE_RECIPIENTS`(쉼표 구분). 기본은 본인(`GMAIL_USER`)에게만 갑니다.

## 소스 바꾸기
`config.toml`을 직접 편집하거나 CLI를 씁니다.
```
python manage.py list
python manage.py check
python manage.py preview <RSS주소>
python manage.py add <key> "<이름>" <RSS주소> --mode newest   # newest | oldest(순서대로)
python manage.py remove <key>
python manage.py schedule mon biz,aee,jp
```
외신 기사(`[[article]]`)는 `section`(top / business / environment)마다 하루 1건, **가장 중요한 기사**를 고릅니다. 중요도는 같은 이야기를 다룬 매체 수(주요 뉴스는 Google News 미국·영국 톱뉴스, 경제는 Google News Business·CNBC도 신호로 사용), 그다음 매체 피드 안의 배치 순서입니다. 실시간 업데이트·영상·퀴즈·칼럼과 36시간 넘은 기사는 제외하고, 주요 뉴스는 경제 기사나 경제와 같은 이야기를 피합니다.
잘못된 설정은 저장 전에 검증되어 오류로 알려주고, `manage.py`는 실패 시 파일을 원복합니다.

## 현재 소스
- 영어: BBC Learning English For Work, BBC 6 Minute English, NPR Short Wave, TED Talks Daily, All Ears English, NPR Life Kit
- 외신: BBC/NPR/Guardian의 Top Stories(분야 무관 주요 뉴스), Business·Economy, Science·Environment·Climate (무료로 전문을 볼 수 있고 공개 RSS가 있는 매체 위주)

## 로드맵 / 남은 일
- [ ] 매일 오전 자동 실행 (작업 스케줄러) — 코드 다듬은 뒤 진행하기로 함
- [ ] 환경공학 R&D 회의/발표/협상 보충 에피소드 (주 1회 Claude로 대본 생성 → edge-tts → mp3 → 피드). Claude API는 쓰지 않고 구독 한도 내에서 수동 생성
- [ ] 일본어 여행 회화 단계별 레슨 (히라가나 → 카타카나 → 여행 상황)
- [ ] 기사에서 업무 영어 표현 추출 칸
- [ ] (후순위) 스피킹 연습/OPIc 모의

## 결정 사항 (바꾸지 않기로 한 것)
- Claude API 같은 유료 호출 금지: 구독료 이상의 지출 없음.
- 메일에는 mp3 링크를 넣지 않음. 개인 피드는 팟캐스트 앱 자동 다운로드용으로 원본 오디오 URL을 유지.
- 듣기는 YouTube Music에서 각 프로그램을 직접 구독해서 함(2026-11-05부터, AntennaPod 대신). 개인 피드는 YouTube Music에 등록할 수 없어
  (소유권 인증 필요, 타사 콘텐츠) 메일에는 프로그램 이름과 공식 페이지/대본 링크만 둠. YouTube Music 검색 링크는 결과가 거의 맞지 않아 제거. 개인 피드(`feed.xml`)는 계속 생성함.
- 수신 메일 주소는 공개 저장소라 config에 적지 않음 (`recipient`가 비어 있으면 `GMAIL_USER`로 발송). 추가 수신자는 GitHub Secret `EXTRA_RECIPIENTS`(쉼표로 구분)에 둠.
- Slow English 팟캐스트는 보류(동명 프로그램이 여럿이라 선택 필요).
- 외신 기사는 제목/요약/링크만 사용하고 전문은 복사하지 않음.
- 국내 리포트 요약은 새로 생성하지 않고(유료 API 금지) 작성자가 붙인 요약문에서 문단별 첫 문장을 원문 순서대로 최대 5줄 뽑아 씀. 증권사 리포트는
  네이버 증권의 비공식 JSON API(`stock.naver.com/api/stockSecurity/researches/v2/...`)라 구조가 바뀌면 해당 섹션만 빠짐.
- 증권사 리포트는 미국 시장 위주: `prefer` 단어(미국, 연준, FOMC, S&P 등)가 제목에 있는 리포트를 조회수보다 먼저 고름.
- 부동산 브리핑은 Daily study와 별도 메일로, 주 1회(금) 보냄(이미 메일이 길고, 받는 사람을 따로 정할 수 있게). 기사는 제목·언론사·링크만 사용.
  Claude 코멘트는 API 호출 없이 세션에서 수동 갱신(구독 한도 내).
- 일요일 메일 맨 위에는 주간 정리(지표 1주 변화, 그 주 기사·리포트 링크, 업무 영어·일본어 복습)를 넣음. 지표 기록은 `state.json`의 `markets_history`(21일 보관).
- 팟캐스트(듣기 큐)는 2026-11-15 메일에서 제외(`[schedule]`을 비움). 그 자리 맨 위에는 미국 주요 기업 실적 발표 일정(Nasdaq 비공식 JSON, 시총 $20B 이상, 다음 2거래일)을 넣음.
- 메일 구성(2026-11-19~): 일요일 주간 정리 → READ(주요 뉴스, 환경) → 학습 카드 → **ECONOMY**(경제 기사, 밤사이 미국·세계 증시·원자재·중앙은행·헤드라인, 국내 리포트, 지표·경제 일정, 미국 실적 발표 일정 순) → (본인 사본) 포트폴리오.
