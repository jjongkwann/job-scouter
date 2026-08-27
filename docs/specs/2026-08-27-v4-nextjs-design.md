# v4 — 데이터 repo를 DB로, 렌더링은 Next.js로

> 2026-08-27. 사용자 요구: "resume-private를 DB로 생각하고 나머지 작업은 전부 job-scouter에서".
> 선택한 목적 4개 — 실시간 인터랙션 · 디자인 체계 · 클라이언트 필터/정렬 · DB와 렌더링의 분리.

## 1. 목표 · 비목표

**목표**
1. 데이터 repo에 코드 0줄. 마크다운·JSON·개인 설정(`settings.json`)만 남는다.
2. 웹은 `web/`(Next.js + shadcn/ui)이 그린다. FastAPI는 JSON API로만 남는다(HTML 0줄).
3. 추천도·통근·순위·마감 계산은 서버(파이썬) **한 곳**. 지금은 `web.py`와 `template.html`에 두 벌.
4. 승인·초안·되돌리기·채팅 턴이 끝나면 화면이 스스로 갱신된다(SSE). 새로고침 없음.
5. 후보목록의 필터·정렬·순위는 그대로. 다른 목록(제안·지원서류)에도 같은 필터 UI.

**비목표**
- 채팅 토큰 스트리밍. `claude -p`가 Temporal activity 안에서 한 번에 돌기 때문. 1차는 "생성 중" 표시 후 완료 시 갱신. 스트리밍은 activity가 청크를 파일에 쓰고 SSE가 tail하는 배관이 따로 필요 — 다음 버전.
- 인증. LAN 전용·1인 그대로. Host 허용 목록과 Sec-Fetch-Site 검사는 유지.
- 워크플로·activity·LLM 프롬프트 변경. `judge.py`·`workflow.py`는 activity 이름 3개만 바뀐다.
- 데이터 스키마 변경. `candidates.json` 행 형식(8~9필드)·`proposals.json`·`applications/` 레이아웃 그대로.

## 2. 아키텍처

```
브라우저 ──:8090──▶ web (Next.js, node)  ──/api/*──▶ api (FastAPI :8091, docker 내부)
                                                        │ 읽기 전용 마운트 ${DATA_REPO}
                                                        │ Temporal client (start/query/list)
                       temporal ◀── io 워커 (파일 쓰기·git·수집·마감갱신) ── llm 워커 (claude -p)
                                          │ 읽기·쓰기 마운트 ${DATA_REPO}
```

- **쓰기는 io 워커만.** api 컨테이너는 데이터 repo를 `:ro`로 마운트한다 — "API는 절대 파일을 쓰지 않는다"가 코드 규약이 아니라 마운트로 강제된다.
- `api`는 LAN에 포트를 열지 않는다. 브라우저는 `web`만 보고, `web`의 라우트 핸들러 `app/api/[...path]/route.ts`가 `API_URL`(docker 내부 주소)로 그대로 넘긴다. 스트리밍 응답(SSE)도 이 핸들러가 body를 통과시킨다.
- 컨테이너 5개: `temporal` · `io` · `llm` · `api` · `web`. `web`만 `8090:3000`을 연다.

## 3. 데이터 계층

### 3.1 데이터 repo로 가는 것 / 남는 것

| 지금 데이터 repo에 있는 코드 | 처리 |
|---|---|
| `jobfeed/fetch_jobs.py` | → `jobscouter/jobfeed.py`의 `fetch_jobs` activity. `new.md`는 계속 쓴다(gitignore, 수동 조사 스킬이 읽음). macOS 알림 제거. |
| `jobfeed/refresh_due.py` | → 같은 파일의 `refresh_due` activity. |
| `jobfeed/build.py` | 폐기. `check()`만 `jobscouter/candidates.py`의 `validate()`로 이전 — API가 후보목록 응답에 `errors`로 실어 화면에 배너로 띄운다. 스냅샷·터미널 보고·회피회사 자동 skip은 버린다(스냅샷은 `candidates.json` git 히스토리가 같은 정보). |
| `jobfeed/template.html` | 폐기. React가 그린다. |
| `jobfeed/reports/*_후보목록.html` (12) | 삭제. |
| 통근 밴드 `ZONE` 표, 검색어 `KEYWORDS` | → 데이터 repo `settings.json`. 집 위치·관심 키워드는 개인값이라 공개 레포에 못 둔다. |
| 추천도 계수 `REC` | 알고리즘 — `jobscouter/candidates.py` 상수. |

`settings.json` (데이터 repo 루트):
```json
{
  "keywords": ["...", "..."],
  "zones": [[4, "통근 불가", "^(부산|대구|…)"], [0, "집 근처", "…"], …, [4, "통근 불가", "."]]
}
```
`zones`는 위에서부터 처음 매치되는 밴드. 정규식은 파이썬에서만 평가한다(JS 사본 없음). `config.settings()`가 읽고, 없으면 `keywords=[]`·`zones=[]`로 동작(모든 주소 → 밴드 9 "미확인").

### 3.2 `jobscouter/candidates.py` (새 모듈 — web.py에서 추출)

`candidate_rows()`, `_zone()`, `_cand_due()`, `_due_label()`, `validate()`, `app_folders()`, `job_index()`, `reputation()`, `dues()`. web.py의 것을 그대로 옮기되 ZONE은 `settings()`에서 읽는다. io_acts·api가 같이 쓴다.

### 3.3 워크플로 변경

- `DailyScan`: `run_script("fetch_jobs.py")` → `fetch_jobs`.
- `Publish`: `run_script("refresh_due.py")` → `refresh_due`; `run_script("build.py")` 단계 삭제.
- `run_script`·`SCRIPTS`·`JOBSCOUTER_PY`·Dockerfile의 `osascript` 심 삭제.
- `commit_outputs`: `candidates.json`·`reports/*.md`만 (html 스냅샷 없음).

### 3.4 데이터 repo allowlist (`.gitignore`)

허용 목록에서 `jobfeed/{fetch_jobs,refresh_due,build}.py`·`template.html` 제거, `jobfeed/reports/*` → `jobfeed/reports/*.md`, 루트 `settings.json` 추가. 그 뒤 트래킹 목록: `이력서.md` · `settings.json` · `references/이력서_사실베이스.md` · `applications/**/*.md` · `jobfeed/{candidates.json, jobs.jsonl, proposals.json, resume_proposals.json, 기업평판.md, reports/*.md}` · `job-scouter/prompts/rubric_v?.md` · `data/resume_state.json` · `.claude/skills/job-scout/SKILL.md`.

## 4. API (`jobscouter/api.py`, `web.py` 삭제)

FastAPI, JSON만. 라우트 접두 `/api`. 모든 파생값(추천도·순위·마감 라벨·통근·평판 레일·점수 셀 강조)은 서버가 계산해 내려준다 — 클라이언트는 표시·필터·정렬만.

| 메서드·경로 | 응답 | 비고 |
|---|---|---|
| `GET /api/dashboard` | `{proposals[], unresearched[], runs[], publish, stats}` | proposals는 `_decorate`된 형태. `publish`는 최근 Publish `{id,status,start,ids,reject_ids,error}` |
| `POST /api/publish` `{ids, rejects:[{id,why}]}` | `{workflow_id}` | Publish 실행 중이면 409 |
| `GET /api/candidates` | `{rows[], apps{cid:{slug,n}}, errors[], updated}` | rows는 `candidate_rows()`. `updated`는 `candidates.json` 최근 커밋 날짜 |
| `GET /api/reports` · `GET /api/reports/{name}` | `[{date,kind,name}]` · `{name, markdown}` | |
| `GET /api/resume` | `{markdown, pending, chats[]}` | |
| `GET /api/resume/history?key=` · `…/history/{sha}?key=` | `{commits[]}` · `{diff}` | |
| `POST /api/resume/revert` `{key,sha}` | `{workflow_id}` | |
| `GET /api/resume/proposals` · `POST /api/resume/apply` `{ids}` | `{items[]}` · `{workflow_id}` | |
| `POST /api/resume/chat` `{key}` | `{sid}` | sid 발급만. 버퍼는 첫 턴의 `chat_load`가 만든다 |
| `GET /api/resume/chat/{sid}` | `{target, turns[], base_doc, doc, diff, pending}` | `pending` = 실행 중인 `chat-{sid}-*` 워크플로 유무 |
| `POST /api/resume/chat/{sid}/turns` `{key,message}` | `{workflow_id}` | **비동기** — 시작만 하고 돌아온다(지금은 최대 6분 블록) |
| `POST /api/resume/chat/{sid}/end` `{save}` | `{result}` | 저장 거부는 409 `{cause, conflict}` |
| `GET /api/applications` | `{stats, linked[], orphans[]}` | |
| `GET /api/applications/job/{cid}` | `{candidate, folder, others[], docs{name: markdown}}` | |
| `GET /api/applications/{slug}` | `{folder, docs, linked_cid}` | |
| `POST /api/applications/draft` `{id}` | `{workflow_id}` | 등재 안 된 id는 400 |
| `GET /api/docs` · `GET /api/docs/{path}` | `[{path,name,group}]` · `{markdown}` | |
| `GET /api/workflows/{id}` | `{id,type,status,stage,error}` | `stage`는 `status` 쿼리가 있는 워크플로만 |
| `GET /api/events` | SSE | 아래 |

**SSE `/api/events`**: 2초마다 Temporal `list_workflows`(최근 50건)를 읽어 `{id,type,status,stage}`가 지난 틱과 다른 것만 `event: workflow` 로 보낸다. RUNNING이고 `status` 쿼리가 있는 타입(DailyScan·Publish·ResumeSync·ApplyResume)은 stage도 쿼리한다. 연결당 루프 하나, 클라이언트가 끊으면 종료. 15초마다 `: ping` 코멘트로 프록시 타임아웃을 막는다.

**마크다운**은 원문으로 내려준다. 렌더는 클라이언트(`react-markdown` + `remark-gfm`, raw HTML 비허용 — 문서 안 HTML은 텍스트로 보인다). 지금 서버 렌더의 "raw HTML 허용 + CSP로 스크립트 차단"보다 단순하고 안전하다.

**보안**: `_lan_guard` 유지(Host 허용 목록 — docker 내부 이름 `api`도 `[\w-]+`에 걸린다; POST의 Sec-Fetch-Site 검사 — `web`의 프록시가 브라우저 헤더를 그대로 전달한다). 경로 인자는 지금과 같은 `_guard`·`resume_target`·`SID_RE`·`_SHA` 검증. 응답 보안 헤더는 `web`이 붙인다(§5).

**오류**: `HTTPException(status, detail)` → `{detail}`. Temporal 예외는 `__cause__` 끝까지 풀어 `detail`에 첫 줄 200자(2026-08-27 라이브 검증 교훈).

## 5. 웹 (`web/`)

**스택**: Next.js(App Router, `output: 'standalone'`) · TypeScript · Tailwind v4 · shadcn/ui · TanStack Query · `react-markdown`. 페이지는 전부 클라이언트 컴포넌트 — SSR로 얻을 게 없고(LAN 1인), 실시간 갱신이 클라이언트 상태를 요구한다.

**프록시** `app/api/[...path]/route.ts`: 모든 메서드를 `${API_URL}/api/${path}?${search}`로 전달. 요청 헤더 중 `content-type`·`sec-fetch-site`·`accept`를 넘기고, 응답 body는 `ReadableStream` 그대로 반환(SSE 통과). `export const dynamic = 'force-dynamic'`.

**보안 헤더** (`middleware.ts`): Host 허용 목록(api와 같은 정규식), `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. 외부 링크는 `rel="noopener"`, `http(s)`만.

**디자인 토큰** (`globals.css`, shadcn 변수 위에 도메인 변수 추가): 평판 레일 4색(`--rail-good/warn/bad/none`), 판정 배경/전경(`good/warn/bad/neu`), 적합도 등급(t1 ≥80 · t2 ≥70 · t3), 마감 긴급도(u0 ≤3일 · u1 ≤7일 · gone), 통근 밴드(z0~4 · z9). 값은 지금 `web.py`의 팔레트를 그대로 옮긴다. 폰트 시스템 고딕, 본문 14px, 최대 폭 1220px, 카드 radius 9px — 지금 규격 유지(메모리 7번: 사용자가 디자인 통일을 요구한 이력).

shadcn 컴포넌트: button · badge · card · table · checkbox · input · textarea · tabs · toggle-group · tooltip · skeleton · sonner(토스트).

**페이지** (지금 라우트와 1:1):

| 경로 | 데이터 | 실시간 |
|---|---|---|
| `/` 승인 대기 | `/api/dashboard` | Publish 시작 → 해당 행 "처리 중" 배지·제출 잠금 → 완료 토스트·목록 갱신 |
| `/candidates` 후보목록 | `/api/candidates` | 필터(평판·태그·최소 적합도·마감·통근)·정렬(추천도·적합도·축별·마감·통근·회사)은 클라이언트. 순위 #는 서버 값 고정. 마감·내려간 공고는 접힌 섹션 |
| `/reports`, `/reports/[name]` | | |
| `/resume` | `/api/resume` | |
| `/resume/history?key=` | + `/history/{sha}` | 되돌리기 → 완료 시 이력 갱신 |
| `/resume/proposals` | | 반영 → 완료 시 갱신 |
| `/resume/chat/[sid]` | `/api/resume/chat/{sid}` | 턴 전송 → "생성 중" → 완료 시 대화·diff 갱신. 저장 거부(409)는 인라인 배너 |
| `/applications`, `/applications/job/[cid]`, `/applications/[slug]` | | 초안 만들기 → 진행 배지 → 완료 시 문서 탭 채워짐 |
| `/docs`, `/docs/[...path]` | | |

**실시간 훅** `useWorkflowEvents()`: 레이아웃에서 `EventSource('/api/events')` 하나를 연다. 이벤트마다 (a) `sonner` 토스트(시작·완료·실패 — 타입별 한국어 문구), (b) TanStack Query `invalidateQueries()` 전체. 페이지별 "처리 중" 표시는 `/api/dashboard`의 `publish`, `/api/resume/chat/{sid}`의 `pending` 같은 서버 값으로 — 클라이언트가 워크플로 id를 기억하지 않는다(새로고침해도 맞다).

**필터·정렬 유틸** `lib/candidates.ts`: 순수 함수 `applyFilters(rows, f)`·`sortRows(rows, key)`. vitest 1개.

## 6. 배포

- `web/Dockerfile`: node 22 alpine 멀티스테이지(`npm ci` → `next build` → standalone 복사).
- `deploy/compose.yaml`: `api`(python 이미지, `uvicorn jobscouter.api:app --port 8091`, `${DATA_REPO}:/work/repo:ro`, LAN 포트 없음) · `web`(`build: ../web`, `API_URL=http://api:8091`, `8090:3000`). `io`·`llm`에서 `JOBSCOUTER_PY` 제거.
- 코드 갱신 절차는 그대로: 서버에서 `git pull && docker compose up -d --build io llm api web`.

## 7. 테스트

- `tests/test_api.py`: `test_web.py`의 픽스처를 그대로 쓰되 JSON 단언으로. 라우트마다 정상 1 + 거부 경로(400/404/409). SSE는 `fake list_workflows`로 두 틱 돌려 diff만 나오는지 1개.
- `tests/test_jobfeed.py`: `fetch_jobs`(HTTP는 monkeypatch, jobs.jsonl append·중복 제외·new.md 태그), `refresh_due`(closed·네트워크 실패 시 값 유지·주소 보존).
- `tests/test_candidates.py`: `validate()`(build.py의 검사 그대로), `_zone`(settings 기반, 실측 사고 케이스 — "울산 중구"·"강남구 영동대로"), 추천도·순위.
- `test_workflow.py`: `fake_run_script` → `fake_fetch_jobs`·`fake_refresh_due`.
- `web/`: `tsc --noEmit` + `next build` + vitest(`lib/candidates.test.ts`). 브라우저 E2E 없음 — 배포 후 서버 `:8090`에서 눈으로 검증(메모리 14번: 라이브에서만 나오는 결함이 있다).

## 8. 순서 · 롤백

1. **데이터 계층** — `jobfeed.py`·`candidates.py`·`settings()`·워크플로 activity 교체·테스트. 데이터 repo: `settings.json` 추가, 스크립트·템플릿·html 스냅샷 삭제, allowlist 갱신. 이 시점 `web.py`의 `/candidates`는 "아직 없음"을 보인다(배포 안 함).
2. **API** — `api.py` + `test_api.py`, `web.py`·`test_web.py` 삭제.
3. **웹** — `web/` + compose + `SERVER_SETUP.md`·README 갱신.
4. 배포 — 서버 `git pull` 양쪽, `compose up -d --build`, `:8090` 전 페이지 확인, 승인·초안 한 건 라이브.

롤백: job-scouter는 커밋 단위라 `git checkout <이전>` + `compose up -d --build`. 데이터 repo는 스크립트 삭제 커밋을 `git revert`.
