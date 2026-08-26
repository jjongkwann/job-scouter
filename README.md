# job-scouter

채용 공고 무인 탐색(수집 → 루브릭 채점)을 Temporal durable workflow 위의 LLM
판정 파이프라인으로 올린 것. 사람이 끼는 지점(등재 승인·거부, 평판 조사)은
LAN 웹앱과 대화형 세션으로 모델링한다.

```
DailyScan (workflow, 매일 자동)                Publish (workflow, 웹 승인 시작)
 ├─ sync_repo        [io 큐]   jobfeed repo 원격 동기화     ├─ sync_repo   [io 큐]
 ├─ fetch            [io 큐]   공개 API 수집(fetch_jobs.py) ├─ commit_rows(승인) · reject_proposals(거부)
 ├─ judge × N        [llm 큐]  공고당 activity 1개 — 루브릭  │     [io 큐]
 │     채점, JSON 스키마 강제, usage 기록                    ├─ refresh_due → build   [io 큐]
 │     캐시키 (공고id, 루브릭버전, 사실베이스 해시)           │     candidates.json 커밋, 결정론 검증(build.py)
 │     예산 초과 → 미점수 강등                               └─ report                [llm 큐]
 └─ proposals.json 갱신 → commit+push  [io 큐]
```

승인·거부는 `web`(FastAPI, :8090)이 `proposals.json`을 보여주고 버튼으로
`Publish`를 시작한다 — 파일을 직접 고치는 경로는 없다.

큐 4개는 자격증명 격리 경계다. judge·report·초안·이력서 채팅은 Claude Code
headless(`claude -p`, 구독 인증 — 로그인된 CLI 또는 `CLAUDE_CODE_OAUTH_TOKEN`)로 돌고,
이 실행 경계는 llm 워커의 `judge.py`에만 있다 — io·workflow·web 모듈은 judge를
import하지 않는다(테스트로 강제). API 키 불필요. 호출당 지출 상한은
`JudgeInput.max_usd`(`ScanParams.max_usd`, `--budget`).

`jobscout-llm`에는 큐 레벨 레이트리밋(0.5/s)이 걸려 있다. 이력서 채팅은 사람이 화면
앞에서 기다리는 대화라 판정 뒤에 줄 서면 안 되므로 `jobscout-chat` 큐를 따로 쓴다 —
같은 llm 워커 프로세스가 둘 다 돌리고, 채팅 큐에만 리밋이 없다.

## 설정

`.env.example`을 `.env`로 복사해 채운다. 개인 자료 3종은 저장소 밖에 둔다:

| 항목 | env | 내용 |
|---|---|---|
| jobfeed | `JOBSCOUTER_JOBFEED` | `fetch_jobs.py`·`refresh_due.py`·`build.py`·`candidates.json`·`jobs.jsonl`·`기업평판.md` |
| 사실베이스 | `JOBSCOUTER_FACTBASE` | 본인 확인 완료 경력 사실 — judge의 감점 근거 |
| 루브릭 | `JOBSCOUTER_PROMPTS` | `rubric_v1.md` — `prompts/rubric_v1.example.md`를 채워서 |

서버 설치: `deploy/SERVER_SETUP.md`. 설계·계획 문서: `docs/specs/` · `docs/plans/`.

## 운영

```bash
uv run python -m jobscouter.worker io    # 터미널 1 — workflow+io (자격증명 없음)
uv run python -m jobscouter.worker llm   # 터미널 2 — judge·report (claude -p)

uv run python -m jobscouter.worker scan [--budget 2000000]   # DailyScan 시작(수동)
uv run python -m jobscouter.worker publish id1 id2 ...       # Publish 시작 — 등재 승인
uv run python -m jobscouter.worker reject <id> "<사유>"      # Publish 시작 — 거부만
uv run python -m jobscouter.worker status                    # 실행 중 DailyScan/Publish 조회
uv run python -m jobscouter.worker resume-sync             # 주 1회 이력서 갱신 제안(수동 시작)
uv run python -m jobscouter.worker apply-resume <id> ...    # 제안 반영
uv run python -m jobscouter.worker schedule                  # 일 1회 자동 시작 등록(매일 09:07 KST)
```

승인·거부는 보통 웹앱에서 한다:

```bash
uv run uvicorn jobscouter.web:app --host 0.0.0.0 --port 8090   # 터미널 3 — LAN 전용, 인증 없음
```

| 경로 | 내용 |
|---|---|
| `/` | `proposals.json` 대시보드(점수·사유·인용) + 승인/거부 체크 → `Publish` 시작. 평판 미조사 회사·최근 실행 상태 |
| `/candidates` | `build.py` 산출 `후보목록.html` 그대로 |
| `/reports`, `/reports/{name}` | 사이클 보고서 목록·렌더 |
| `/resume/proposals` | 이력서 갱신 제안 승인 → ApplyResume |
| `/resume` | `JK.md`·사실베이스·`drafts/` 렌더. 문서별 「대화로 고치기」·「이력」 링크, 진행 중 대화 목록 |
| `/resume/chat`, `/resume/chat/{sid}` | 대화로 이력서 수정. 한 턴 = `ResumeChat` 워크플로 1회. 수정은 세션 버퍼에만 쌓이고 `저장`을 눌러야 파일 반영 + 커밋 1개(`EndChat`) |
| `/resume/history` | 문서별 커밋 목록·diff. 「되돌리기」는 과거 내용을 **새 커밋으로** 올린다(`RevertFile`) — 히스토리를 지우지 않으므로 되돌린 것도 되돌릴 수 있다 |
| `/applications`, `/applications/{slug}` | 회사별 지원서류 5종 렌더. 등재 공고에서 초안 (재)생성 요청 → `Draft` |
| `/docs`, `/docs/{path}` | `references/` 문서 렌더(하위 디렉토리 포함) |

워커가 꺼져 있어도 워크플로는 서버에서 대기하고, 워커를 켜면 이어진다.
판정 캐시는 `data/judgments.jsonl` — 루브릭을 올리면 `rubric_v2.md` 추가 후
`judge.RUBRIC_VERSION` 변경, 전 건이 자동 재판정 대상이 된다.

서버 컨테이너 운영(io·llm·web 상시 가동): `deploy/SERVER_SETUP.md`.

## RAG (Phase 3)

기존 ES에 `jobscout_facts`(사실베이스) · `jobscout_precedents`(판정 판례) ·
`jobscout_reputation`(평판 캐시) 인덱스를 만든다. bge-m3 + BM25/kNN 클라이언트
RRF, 리랭커 없음, k=20.

```bash
uv run python scripts/index_es.py          # 재색인 (판례·평판·사실베이스 갱신 시)
uv run python scripts/eval_judge.py [--rag] # 수동 판정 대조 (일치율·MAE)
```
