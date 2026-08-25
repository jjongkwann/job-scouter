# job-scouter

채용 공고 수동 조사(수집 → 루브릭 채점 → 평판 확인 → 등재)를 Temporal durable
workflow 위의 LLM 판정 파이프라인으로 올린 것. 사람이 끼는 두 지점(브라우저
평판 조사, 등재 승인)은 signal 대기로 모델링한다.

```
JobScoutCycle (workflow)
 ├─ fetch            [io 큐]   공개 API 수집 (jobfeed/fetch_jobs.py)
 ├─ judge × N        [llm 큐]  공고당 activity 1개 — 루브릭 채점, JSON 스키마 강제, usage 기록
 │     캐시키 (공고id, 루브릭버전, 사실베이스 해시)   예산 초과 → 미점수 강등
 ├─ signal 1: browser_done   수동 브라우저 조사 완료
 ├─ signal 2: approve        등재 승인 (id 목록)
 ├─ commit → refresh → build [io 큐]  candidates.json 커밋, 결정론 검증(build.py)
 └─ report           [llm 큐]  사이클 요약·비용
```

큐 3개는 자격증명 격리 경계다. judge·report는 Claude Code headless(`claude -p`,
구독 인증 — 로그인된 CLI 또는 `CLAUDE_CODE_OAUTH_TOKEN`)로 돌고, 이 실행 경계는
llm 워커의 `judge.py`에만 있다 — io·workflow 모듈은 judge를 import하지 않는다
(테스트로 강제). API 키 불필요. 호출당 지출 상한은 `CycleParams.max_usd`
(`--max-budget-usd`).

## 설정

`.env.example`을 `.env`로 복사해 채운다. 개인 자료 3종은 저장소 밖에 둔다:

| 항목 | env | 내용 |
|---|---|---|
| jobfeed | `JOBSCOUTER_JOBFEED` | `fetch_jobs.py`·`refresh_due.py`·`build.py`·`candidates.json`·`jobs.jsonl`·`기업평판.md` |
| 사실베이스 | `JOBSCOUTER_FACTBASE` | 본인 확인 완료 경력 사실 — judge의 감점 근거 |
| 루브릭 | `JOBSCOUTER_PROMPTS` | `rubric_v1.md` — `prompts/rubric_v1.example.md`를 채워서 |

서버 설치: `deploy/SERVER_SETUP.md`.

## 운영

```bash
uv run python -m jobscouter.worker io    # 터미널 1 — workflow+io (자격증명 없음)
uv run python -m jobscouter.worker llm   # 터미널 2 — judge·report (claude -p)
uv run python -m jobscouter.worker run [--budget 2000000] [--dry-run]

uv run python -m jobscouter.worker status               # 단계·proposals·비용
uv run python -m jobscouter.worker browser-done "메모"   # signal 1
uv run python -m jobscouter.worker approve <id> ...     # signal 2 (--none = 등재 없음)
uv run python -m jobscouter.worker schedule             # 주 1회 자동 시작 등록 (월 09:07 KST)
```

워커가 꺼져 있어도 워크플로는 서버에서 대기하고, 워커를 켜면 이어진다.
판정 캐시는 `data/judgments.jsonl` — 루브릭을 올리면 `rubric_v2.md` 추가 후
`judge.RUBRIC_VERSION` 변경, 전 건이 자동 재판정 대상이 된다.

서버 컨테이너 운영(io·llm 워커 상시 가동): `deploy/SERVER_SETUP.md`.

## RAG (Phase 3)

기존 ES에 `jobscout_facts`(사실베이스) · `jobscout_precedents`(판정 판례) ·
`jobscout_reputation`(평판 캐시) 인덱스를 만든다. bge-m3 + BM25/kNN 클라이언트
RRF, 리랭커 없음, k=20.

```bash
uv run python scripts/index_es.py          # 재색인 (판례·평판·사실베이스 갱신 시)
uv run python scripts/eval_judge.py [--rag] # 수동 판정 대조 (일치율·MAE)
```
