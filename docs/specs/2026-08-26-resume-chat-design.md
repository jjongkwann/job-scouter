# 이력서 채팅·회사별 요청·수정 이력 (v3)

2026-08-26. `/resume` 화면을 읽기 전용 렌더에서 **대화로 고치는 작업대**로 올린다.

선행 스펙: `2026-08-24-v1-design.md` · `2026-08-25-v2-design.md`. 구현 계획은 `docs/plans/`.

## 1. 배경 — 이미 있는 것

| 요구 | 현재 |
|---|---|
| 공통 이력서 | `JK.md` → `/resume` 렌더 |
| 회사별 이력서 | `applications/{slug}/1_맞춤_이력서.md` — Publish가 자동 생성, CLI `worker draft <id>`로 재생성 |
| 수정 이력 | 데이터 repo가 git. 모든 io activity가 commit(+push) |
| 백업 | `_commit_and_push`가 원격으로 push |

**새 저장 계층·새 이력 포맷을 만들지 않는다.** 이력과 백업은 git이 이미 하고 있고,
없는 것은 그것을 보여주는 화면과 대화로 고치는 입구뿐이다.

## 2. 결정 사항

1. 대화 투입은 **웹 실시간 채팅** (붙여넣기·파일 드롭이 아니라)
2. 반영은 **세션 버퍼 → 저장 버튼** (턴마다 즉시 커밋이 아니라)
3. 회사별 이력서는 **등재 공고에서 버튼으로** (임의 회사 입력이 아니라)
4. 수정 이력은 **보기 + 되돌리기 버튼**

## 3. 구조

### 3.1 자격증명 경계

`web`은 `judge`를 import하지 않는다(기존 테스트로 강제). 채팅 한 턴도 LLM 큐
activity를 거친다. web은 워크플로를 시작하고 결과를 기다릴 뿐이다.

### 3.2 전용 큐 `Q_CHAT`

llm 워커 프로세스에 워커를 하나 더 띄운다. `Q_LLM`은
`max_task_queue_activities_per_second=0.5`라 DailyScan이 도는 중엔 채팅 턴이
판정 뒤에 줄 선다. `Q_CHAT`은 레이트리밋 없음, 스레드 2.

### 3.3 세션 버퍼 위치

`JOBFEED.parent / "tmp" / "chat" / {sid}.json`.

데이터 repo `.gitignore`에 `tmp/`가 있어 `sync_repo`의 `git add -A`에도 안 딸려간다.
io·llm·web 컨테이너가 모두 `${DATA_REPO}`를 마운트하므로 **compose 변경 없음**.

```json
{
  "sid": "8자리 hex",
  "target": "JK.md",
  "base_sha256": "세션 시작 시 대상 파일 해시",
  "base_doc": "세션 시작 시 원문 — diff 기준",
  "doc": "현재 초안 전문",
  "turns": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "...", "applied": 2, "skipped": ["원문 불일치: ..."]}
  ],
  "created": "ISO8601"
}
```

### 3.4 대상 문서 allowlist — `config.resume_target(key) -> Path`

기존 `io_acts._RESUME_TARGETS`를 config로 올려 채팅·되돌리기·`apply_resume`이
**한 정의를 공유**한다.

| key | 파일 |
|---|---|
| `factbase` | `FACTBASE` |
| `JK.md` | `JK_MD` |
| `applications/{slug}/{name}.md` | `APPLICATIONS/...` — name은 `APP_FILES` + `README.md`만 |
| `drafts/{name}.md` | `DRAFTS/...` |

그 밖은 `ValueError`. slug는 `[0-9A-Za-z_가-힣]+`만 — 경로 탈출 불가.

## 4. 이력서 채팅

### 4.1 턴 흐름

```
web POST /resume/chat/{sid}
  └ execute_workflow(ResumeChat, {sid, target, message}) ── await
       chat_load(sid, target)          [io]    없으면 새 세션 생성(doc=원문)
       resume_chat(doc, turns, message)[chat]  claude -p
       chat_append(sid, message, out)  [io]    edits를 doc에 적용, 버퍼 저장
  └ 302 → GET /resume/chat/{sid}
```

turn id는 `chat-{sid}-{n}`. Temporal이 재시도·이력을 맡는다.

### 4.2 LLM 계약

문서 전문을 되받지 않는다. 65KB를 출력시키면 느리고 비싸다.

```python
CHAT_SCHEMA = {"edits": [{"current", "proposed", "why"}], "reply": str}
```

`current` → `proposed` 정확 치환. `apply_resume`의 치환과 같은 모양이다.
원문 불일치 항목은 건너뛰고 `skipped`에 사유를 남겨 채팅에 표시한다.

- **system**: 사실베이스 + "사실베이스에 없는 주장 금지" 규칙 — 세션 내 불변 → 프롬프트 캐시
- **user**: 현재 문서 전문 + 대화 기록 + 이번 메시지

긴 자유 텍스트(`reply`, `why`)는 스키마 **맨 끝**에 둔다 — `SCORE_SCHEMA`와 같은
이유(뒤 필드가 긴 문자열에 삼켜지는 실측 사고).

> `ponytail:` 매 턴 문서 전문 재전송 — `JK.md` 65KB 기준 약 20k 토큰/턴, 20턴 세션에
> 수 달러. 문서가 더 커지면 섹션 단위 편집으로 좁힌다.

### 4.3 저장 · 버림 · 충돌

`EndChat(sid, save: bool)` 워크플로 하나가 둘 다 처리한다.

- **저장**: `sync_repo` → `chat_save(sid)` — `base_sha256`과 현재 파일 해시가 다르면
  거부(ResumeSync·ApplyResume가 중간에 같은 파일을 고친 경우). 같으면 `doc`을 쓰고
  커밋+push 1개, 버퍼는 `tmp/chat/done/`으로 옮긴다.
- **버림**: `chat_discard(sid)` — 버퍼 삭제. 커밋 없음.

세션은 디스크에 있으므로 탭을 닫거나 워커가 죽어도 살아남는다.

### 4.4 화면

`/resume`에 진행 중 세션 목록과 문서별 `대화로 고치기` 버튼을 둔다. 버튼은
`GET /resume/chat?target={key}` → 새 sid 발급 후 `/resume/chat/{sid}`로 302.

`/resume/chat/{sid}` — 좌: 대화, 우: `difflib.unified_diff(base_doc, doc)` 누적 diff +
`저장`·`버림`. sid는 `^[0-9a-f]{8,32}$`만 받는다(경로 탈출 방지).

## 5. 회사별 이력서 요청

`/applications`에 `candidates.json` 등재 행 목록(회사·포지션·초안 유무)을 붙이고
`POST /applications/draft {id}` → 기존 `Draft` 워크플로 시작(비동기, 즉시 리다이렉트).

신규 코드는 라우트 하나 + 템플릿 조각. `write_application`이 기존 폴더를 `_draft`로
비켜 쓰므로 덮어쓰기 걱정이 없다. 만든 뒤 그 문서를 채팅으로 다듬는 게 동선이다.

## 6. 수정 이력 · 되돌리기

- **보기**: `GET /resume/history?key=JK.md` — web이 `git log --format` + `git show -p`를
  직접 읽는다. 읽기 전용이라 자격증명이 필요 없고, web 컨테이너에 repo가 이미 마운트돼 있다.
- **되돌리기**: `POST /resume/revert {key, sha}` → `RevertFile` 워크플로 →
  `git_revert`: `git show {sha}:{path}`를 파일에 쓰고 커밋+push.
  **히스토리를 지우지 않으므로 되돌린 것도 다시 되돌릴 수 있다.**
- key는 4절 allowlist와 같은 것. `FACTBASE`가 `JOBFEED.parent` 밖으로 설정된 경우
  history/revert는 오류를 낸다(정상 배치에서는 안쪽).

## 7. 백업

저장·되돌리기 모두 `_commit_and_push`를 타므로 원격 push가 곧 백업이다.
별도 기능을 만들지 않는다.

## 8. 파일별 변경

| 파일 | 내용 |
|---|---|
| `config.py` | `Q_CHAT`, `CHAT_DIR`, `resume_target()` |
| `judge.py` | `CHAT_SCHEMA`, `resume_chat` activity |
| `io_acts.py` | `chat_load`·`chat_append`·`chat_save`·`chat_discard`·`git_revert`. `apply_resume`은 `resume_target()` 사용으로 교체(중복 제거) |
| `workflow.py` | `ResumeChat`, `EndChat`, `RevertFile` |
| `web.py` | 채팅 3라우트, `/resume/history`, `/resume/revert`, `/applications` 목록·`/applications/draft` |
| `worker.py` | `Q_CHAT` 워커 + activity 등록 |
| `README.md` | 라우트 표·운영 절 갱신 |

UI는 기존 규격(`jobfeed/template.html` 토큰 — 14px 시스템 고딕·1220px·9px 카드·999px 필)을 따른다.

## 9. 테스트

- `test_io_acts` — `chat_append` 치환 성공/불일치 건너뜀, `chat_save` 해시 불일치 거부,
  `git_revert` 파일 복원, `resume_target()` allowlist 밖 거부
- `test_web` — 채팅 화면 렌더, 저장·버림·되돌리기·초안요청 라우트가 워크플로를
  시작하는지(monkeypatch), allowlist 밖 key 거부, sid 형식 검증
- `test_workflow` — 기존 자격증명 격리 테스트 유지. `resume_chat`을 `judge.py`에 두므로
  web·io·workflow가 judge를 import하지 않는 경계가 그대로다

## 10. 범위 밖 (YAGNI)

- 토큰 스트리밍 — 턴 단위 폼 제출로 충분
- 인증·다중 사용자 — LAN 무인증 유지
- 채팅에서 파일 생성·삭제 — 편집만
- PDF 생성 — 수동 유지
- 임의 회사 이력서(등재 안 된 공고) — 필요해지면 그때

## 11. 리스크

| 리스크 | 대응 |
|---|---|
| 같은 파일에 세션 2개 → 나중 저장이 앞을 덮음 | `base_sha256` 게이트로 거부 |
| LLM이 `current`를 부정확하게 인용 | 건너뛰고 채팅에 사유 표시 — 파일은 안 망가짐 |
| 긴 세션 비용 | 4.2절 천장 표기. `max_usd` 상한 유지 |
| 채팅 턴이 판정에 밀림 | `Q_CHAT` 분리 |
