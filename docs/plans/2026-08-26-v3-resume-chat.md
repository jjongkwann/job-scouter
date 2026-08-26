# job-scouter v3 (Phase 9) — 이력서 채팅·회사별 요청·수정 이력 Implementation Plan

> **For agentic workers:** task당 서브에이전트 1개, 리뷰 세리머니 생략(프로젝트 규칙).
> TDD 스킬은 쓰지 않는다 — ponytail 규칙으로 구현하고 **유닛당 러너블 체크 1개**를 남긴다.
> 체크박스로 진행 추적.

**Goal:** `/resume`를 읽기 전용 렌더에서 대화로 고치는 작업대로 올린다 — 채팅 수정(세션 버퍼 →
저장), 등재 공고 지원서류 요청 버튼, git 기반 수정 이력·되돌리기.

**Architecture:** 새 저장 계층을 만들지 않는다. 수정 이력·백업은 데이터 repo git이 이미 하고 있고,
없던 것은 그것을 보여주는 화면과 대화 입구뿐이다. 채팅 한 턴 = 워크플로 1회 실행
(`chat_load` → `resume_chat` → `chat_append`), 세션 버퍼는 데이터 repo의 gitignore된 `tmp/chat/`.
web은 파일을 쓰지 않고 워크플로만 시작한다.

**Tech Stack:** 기존 그대로 + stdlib(`difflib`·`hashlib`·`subprocess`). 새 의존성 없음.

**Spec:** `docs/specs/2026-08-26-resume-chat-design.md`

## Global Constraints

- **자격증명 격리**: LLM 호출은 `judge.py`의 `_claude()`만. `web`·`io_acts`·`workflow`는 judge를
  import하지 않는다 — `tests/test_workflow.py`의 기존 격리 테스트가 강제한다. 깨지 말 것.
- **결정론**: 워크플로에서 파일·시계·네트워크 금지. 새 IO는 전부 activity.
- **쓰기 경로**: web은 워크플로 시작만. 파일 직접 수정 금지(git 읽기는 예외 — 읽기 전용).
- **공개 저장소**: IP·절대경로·이름·회사명 하드코딩 금지. 전부 env 또는 `config.py` 상수.
- **경로 allowlist**: LLM·브라우저가 준 문자열이 경로가 되는 지점은 `config.resume_target()`
  한 곳뿐. sha는 `^[0-9a-f]{7,40}$`, sid는 `^[0-9a-f]{8,32}$`로 검증 후에만 subprocess/경로에 쓴다.
- **UI 규격**: `jobfeed/template.html` 토큰(색 변수·14px 시스템 고딕·1220px 폭·9px 카드·999px 필)
  그대로. web.py의 기존 CSS가 정본.
- **테스트**: `uv run pytest -q` 전부 통과. 커밋은 task마다 1회.

## File Structure

```
jobscouter/
  config.py    T2 resume_target()·_app_slug 이동 · T3 Q_CHAT·CHAT_DIR·CHAT_DONE·SID_RE
  io_acts.py   T2 git_revert·apply_resume 리팩터 · T3 chat_load/chat_append/chat_save/chat_discard
  judge.py     T3 CHAT_SCHEMA·resume_chat
  workflow.py  T2 RevertFile · T3 ResumeChat·EndChat
  worker.py    T2·T3 activity·workflow 등록 · T3 Q_CHAT 워커
  web.py       T1 /applications 목록·POST /applications/draft
               T2 /resume/history·POST /resume/revert
               T4 /resume/chat 3라우트
tests/
  test_io_acts.py   T2 git_revert·resume_target · T3 chat_* 
  test_judge.py     T3 resume_chat
  test_web.py       T1·T2·T4
README.md      T5
```

---

### Task 1: 등재 공고 지원서류 요청 버튼

가장 작은 end-to-end. 기존 `Draft` 워크플로에 웹 입구만 붙인다. config·io·judge 변경 없음.

**Files:** `jobscouter/web.py`, `tests/test_web.py`

**Interfaces (Produces):**
- `web.start_draft(cid: str) -> str` — `client.start_workflow(Draft.run, cid, id=f"draft-{cid}", task_queue=Q_WF)`
  후 `handle.id` 반환. **테스트가 monkeypatch하는 지점**이므로 반드시 모듈 최상위 async 함수로 둘 것
  (`start_publish`·`start_apply_resume`와 같은 모양).
- `web.listed_rows() -> list[dict]` — `candidates.json`의 `rows`를 읽어
  `[{"id": str(r[2]), "company": r[1], "title": r[0], "slug": _app_slug(r[1]), "has": bool}]`.
  `has`는 `APPLICATIONS/{slug}` 또는 `APPLICATIONS/{slug}_draft` 존재 여부. 최신 행이 위로 오게 역순.
- `GET /applications` — 기존 카드 목록 위에 「등재 공고」 표를 추가한다. 각 행: 회사·포지션·
  초안 유무 배지·버튼(`has`면 "다시 만들기", 아니면 "초안 만들기"). 폼은
  `POST /applications/draft`에 `id` 하나를 실어 보낸다.
- `POST /applications/draft` — form `id`. `listed_rows()`에 없는 id면 **400**
  (등재된 공고만 초안을 만든다 — `io_acts.listed_target`의 제약과 같은 이유). 있으면
  `await start_draft(id)` 후 302 `/applications`.

**구현 메모:**
- `_app_slug`는 지금 `io_acts`에 있다. web은 io_acts를 import하지 않는다(elasticsearch를 끌고 온다).
  **이 태스크에서 `config.py`로 옮기고** `io_acts`는 `from jobscouter.config import _app_slug`로 바꾼다.
  web에 복사하지 말 것 — `_norm`이 이미 같은 이유로 config에 있다. 그 전례를 따른다.
- web 신규 import: `_app_slug`, `Draft`(workflow에서).
- Draft는 비동기다. 완료를 기다리지 않고 바로 리다이렉트하며, 안내 문구로
  "초안 생성은 몇 분 걸립니다 — 완료되면 이 목록에 나타납니다"를 둔다.

- [ ] `_app_slug`를 `config.py`로 이동(io_acts는 import로 교체), `web.listed_rows`·`start_draft` 추가,
      `/applications` 템플릿에 「등재 공고」 표 + `POST /applications/draft` 라우트
- [ ] tests/test_web.py:
      - `test_applications_lists_listed_rows` — repo 픽스처의 `candidates.json` rows가 표에 보인다
      - `test_draft_starts_workflow` — `start_draft` monkeypatch, `POST /applications/draft {id: "222"}`
        → 302 + 호출 인자 `["222"]`
      - `test_draft_rejects_unlisted_id` — `{id: "999"}` → 400
      - 픽스처의 `candidates.json`에 `rows`가 없으면 `repo` fixture에 추가할 것
        (현재 `proposals.json`만 있다)
- [ ] `uv run pytest -q` 통과 → 커밋 `feat: 등재 공고 지원서류 초안 요청 버튼`

---

### Task 2: 대상 allowlist + 수정 이력 보기·되돌리기

**Files:** `jobscouter/config.py`, `jobscouter/io_acts.py`, `jobscouter/workflow.py`,
`jobscouter/worker.py`, `jobscouter/web.py`, `tests/test_io_acts.py`, `tests/test_web.py`

**Interfaces (Produces):**

`config.py` — `APP_FILES` 정의 **뒤에** 둔다(참조하므로):
```python
_APP_DOC = re.compile(r"applications/([0-9A-Za-z_가-힣]+)/([^/]+\.md)")
_DRAFT_DOC = re.compile(r"drafts/([^/]+\.md)")


def resume_target(key: str) -> Path:
    """채팅·되돌리기·apply_resume이 건드릴 수 있는 파일만 절대경로로. 그 밖은 ValueError.
    LLM·브라우저가 준 문자열이 경로가 되는 유일한 지점 — allowlist를 여기 한 곳에 모은다."""
    if key == "factbase":
        return FACTBASE
    if key == "JK.md":
        return JK_MD
    m = _APP_DOC.fullmatch(key)
    if m and m.group(2) in APP_FILES + ["README.md"]:
        return APPLICATIONS / m.group(1) / m.group(2)
    m = _DRAFT_DOC.fullmatch(key)
    if m:
        return DRAFTS / m.group(1)
    raise ValueError(f"허용되지 않은 이력서 대상: {key}")
```

`io_acts.py`:
- `apply_resume`의 `_RESUME_TARGETS` dict를 **삭제**하고 `config.resume_target(it["target"])`을 쓴다.
  `ValueError`는 기존 "알 수 없는 대상" 실패 항목 처리와 같게 잡아 넘긴다. 커밋 경로 목록도
  `[resume_target("factbase"), resume_target("JK.md")]` 기준으로 만든다.
- 신규:
```python
_SHA = re.compile(r"[0-9a-f]{7,40}")


@activity.defn
def git_revert(key: str, sha: str) -> str:
    """git show {sha}:{경로} 내용을 파일에 되쓰고 commit+push. 히스토리는 지우지 않으므로
    되돌린 것도 다시 되돌릴 수 있다. sha는 subprocess 인자로 들어가므로 형식 검증 필수."""
```
  동작: `_SHA.fullmatch(sha)` 아니면 `ValueError`. `path = resume_target(key)`,
  `rel = str(path.relative_to(JOBFEED.parent))` (밖이면 `ValueError` — 정상 배치에서는 안쪽).
  `git -C repo show {sha}:{rel}` stdout을 `path`에 쓰고
  `_commit_and_push([rel], f"resume: {rel} → {sha[:7]} 되돌리기")`. 반환 문자열은 커밋 결과.

`workflow.py`:
```python
@workflow.defn
class RevertFile:
    """웹 되돌리기 버튼이 시작. 과거 커밋 내용을 새 커밋으로 올린다."""

    @workflow.run
    async def run(self, inp: dict) -> str:      # {"key": str, "sha": str}
        await workflow.execute_activity("sync_repo", **_IO_OPTS)
        return await workflow.execute_activity(
            "git_revert", args=[inp["key"], inp["sha"]], **_IO_OPTS)
```

`worker.py`: io 커맨드의 `acts` 리스트에 `io_acts.git_revert` 추가, `workflows=[...]`에 `RevertFile` 추가.

`web.py` — 신규 import: `subprocess`, `config.resume_target`, `workflow.RevertFile`.
(읽기 전용 git — 자격증명 불필요, web 컨테이너에 repo가 이미 마운트돼 있다):
```python
def _git_log(rel: str, n: int = 30) -> list[dict]:
    """[{"sha","date","subject"}] — 해당 파일을 건드린 커밋만."""
    r = subprocess.run(
        ["git", "-C", str(JOBFEED.parent), "log", f"-{n}",
         "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M", "--", rel],
        capture_output=True, text=True, timeout=20)
    out = []
    for ln in r.stdout.splitlines():
        sha, _, rest = ln.partition("\t")
        date, _, subject = rest.partition("\t")
        out.append({"sha": sha, "date": date, "subject": subject})
    return out


def _git_show(sha: str, rel: str) -> str:
    """한 커밋이 그 파일에 낸 diff 원문. sha는 호출 전에 검증돼 있어야 한다."""
```
- `web.start_revert(key: str, sha: str) -> str` — `RevertFile.run`을 `id=f"revert-{sha[:7]}-{uuid4().hex[:6]}"`로
  시작하고 `handle.id` 반환. **monkeypatch 지점.**
- `GET /resume/history?key=JK.md&sha=<선택>` — `resume_target(key)`로 검증(`ValueError` → 400),
  좌측에 `_git_log` 표(날짜·제목·「diff 보기」·「이 버전으로 되돌리기」 버튼), `sha`가 있으면
  우측에 `_git_show` 결과를 `<pre>`로. `+`/`-`로 시작하는 줄만 색을 준다(기존 `--good`/`--bad` 토큰).
- `POST /resume/revert` — form `key`, `sha`. sha가 `^[0-9a-f]{7,40}$`가 아니면 **400**,
  key가 allowlist 밖이면 **400**. 통과하면 `await start_revert(key, sha)` 후
  302 `/resume/history?key={key}`.
- `/resume` 각 문서 섹션 제목 옆에 `이력` 링크(`/resume/history?key=...`)를 붙인다.

- [ ] 구현 (config → io_acts → workflow → worker → web 순서. `apply_resume` 리팩터를 빠뜨리지 말 것)
- [ ] tests/test_io_acts.py:
      - `test_resume_target_allowlist` — `factbase`·`JK.md`·`applications/foo/0_JD.md`·`drafts/x.md`는
        경로를 돌려주고, `../etc/passwd`·`applications/foo/evil.sh`·`applications/../x/0_JD.md`는 `ValueError`
      - `test_git_revert_restores_and_commits` — `tmp_path`에 `git init` → `JK.md` "v1" 커밋 →
        "v2" 커밋 → `git_revert("JK.md", <v1 sha>)` → 파일 내용이 "v1", `git log` 3커밋
        (monkeypatch: `io_acts.JOBFEED = tmp_path/"jobfeed"`, `config.JK_MD`. 원격 없으니 push 생략 경로)
      - `test_git_revert_rejects_bad_sha` — `"; rm -rf /"` → `ValueError`
- [ ] tests/test_web.py:
      - `test_history_lists_commits` — tmp git repo 픽스처에서 `/resume/history?key=JK.md` 200 + 커밋 제목
      - `test_history_rejects_bad_key` — `?key=../etc/passwd` → 400
      - `test_revert_starts_workflow` — `start_revert` monkeypatch → 302 + 인자 확인
      - `test_revert_rejects_bad_sha` — `{key: "JK.md", sha: "zzz"}` → 400
- [ ] `uv run pytest -q` 통과 → 커밋 `feat: 이력서 수정 이력 보기·되돌리기`

---

### Task 3: 채팅 백엔드 — 세션 버퍼·턴·저장

화면 없이 완결된다. 검증은 테스트로.

**Files:** `jobscouter/config.py`, `jobscouter/judge.py`, `jobscouter/io_acts.py`,
`jobscouter/workflow.py`, `jobscouter/worker.py`, `tests/test_io_acts.py`, `tests/test_judge.py`

**Interfaces (Produces):**

`config.py`:
```python
Q_CHAT = "jobscout-chat"                       # 판정 레이트리밋과 분리 — 채팅이 판정 뒤에 안 밀리게
CHAT_DIR = JOBFEED.parent / "tmp" / "chat"     # 데이터 repo .gitignore의 tmp/ 아래 — 커밋 안 됨
CHAT_DONE = CHAT_DIR / "done"
SID_RE = re.compile(r"[0-9a-f]{8,32}")
```

`judge.py` — 긴 자유 텍스트(`why`·`reply`)는 **맨 끝**에 둔다(`SCORE_SCHEMA`와 같은 이유):
```python
CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "current": {"type": "string",
                                "description": "고칠 원문을 문서에서 그대로 인용. 문서에 정확히 한 번만 나오는 만큼 길게"},
                    "proposed": {"type": "string", "description": "대체할 내용. 삭제면 빈 문자열"},
                    "why": {"type": "string", "description": "이 수정을 하는 이유 한 문장"},
                },
                "required": ["current", "proposed", "why"],
            },
        },
        "reply": {"type": "string", "description": "사용자에게 보일 답변"},
    },
    "required": ["edits", "reply"],
}


@activity.defn
def resume_chat(doc: str, turns: list[dict], message: str) -> dict:
    """이력서 편집 대화 한 턴. 문서 전문을 되받지 않고 current→proposed 치환 목록만 받는다."""
```
  - system: `f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>"` + 규칙 —
    "너는 이력서 편집 조수다. 사실베이스에 없는 주장은 절대 만들지 않는다.
    수정은 `edits`로만 낸다. `current`는 문서에 **정확히 한 번** 나오도록 충분히 길게 인용한다.
    내용을 새로 넣을 때도 인접한 기존 문장을 `current`로 인용하고 `proposed`에 그 문장 + 새 내용을
    함께 쓴다. 고칠 게 없으면 `edits`를 빈 배열로 두고 `reply`만 쓴다."
    세션 내 불변이라 프롬프트 캐시가 먹는다.
  - user: `f"<현재 문서>\n{doc}\n</현재 문서>\n\n<대화>\n{...}\n</대화>\n\n{message}"`.
    대화는 `turns`를 `"[사용자] ...\n[조수] ..."` 형태로 이어 붙인다(assistant turn은 `text`만).
  - `_claude(user, system, max_usd=0.5, schema=CHAT_SCHEMA, timeout=300)` →
    `{"reply": str, "edits": list[dict]}` 반환.

`io_acts.py`:
```python
@activity.defn
def chat_load(sid: str, key: str) -> dict:
    """세션 버퍼를 읽는다. 없으면 key 대상 원문으로 새로 만든다."""
```
  버퍼 스키마(`CHAT_DIR/{sid}.json`):
  `{"sid","target","base_sha256","base_doc","doc","turns":[...],"created"}`.
  `sid`는 `SID_RE.fullmatch` 아니면 `ValueError`. `path = resume_target(key)`,
  없는 파일이면 `ValueError`. `base_sha256 = sha256(path.read_bytes()).hexdigest()`,
  `base_doc = doc = path.read_text()`, `created = date.today().isoformat()`.
  `CHAT_DIR.mkdir(parents=True, exist_ok=True)`.

```python
@activity.defn
def chat_append(sid: str, message: str, out: dict) -> dict:
    """LLM 출력(out={"reply","edits"})을 버퍼 doc에 적용하고 turns에 쌓는다. 갱신된 세션 반환."""
```
  각 edit에 대해:
  - `current`가 빈 문자열 → `skipped.append(f"빈 인용 — 건너뜀: {why}")`
  - `doc.count(current) == 0` → `skipped.append(f"원문 불일치 — 건너뜀: {current[:40]}…")`
  - `doc.count(current) > 1` → `skipped.append(f"인용이 {n}곳에 중복 — 건너뜀: {current[:40]}…")`
  - 그 외 → `doc = doc.replace(current, proposed, 1)`, `applied += 1`
  turns에 `{"role":"user","text":message}`와
  `{"role":"assistant","text":out["reply"],"applied":applied,"skipped":skipped}`를 append.
  버퍼를 다시 쓰고 세션 dict 반환.

```python
@activity.defn
def chat_save(sid: str) -> str:
    """base_sha256이 현재 파일 해시와 같을 때만 doc를 쓰고 commit+push. 버퍼는 done/으로."""
```
  해시가 다르면 `RuntimeError("대상 파일이 세션 시작 후 바뀌었습니다 — 저장 취소")`.
  같으면 `path.write_text(s["doc"])`,
  `_commit_and_push([rel], f"resume: {rel} 채팅 수정 {턴수}턴")`,
  `CHAT_DONE.mkdir(parents=True, exist_ok=True)` 후 버퍼를 `CHAT_DONE/{sid}.json`으로 이동.

```python
@activity.defn
def chat_discard(sid: str) -> str:
    """버퍼 삭제. 커밋 없음."""
```

`workflow.py`:
```python
_CHAT_OPTS = dict(
    task_queue=Q_CHAT,
    start_to_close_timeout=timedelta(minutes=6),
    retry_policy=RetryPolicy(maximum_attempts=2),
)


@workflow.defn
class ResumeChat:
    """이력서 편집 대화 한 턴. 웹이 결과를 기다린다."""

    @workflow.run
    async def run(self, inp: dict) -> dict:      # {"sid","key","message"}
        s = await workflow.execute_activity(
            "chat_load", args=[inp["sid"], inp["key"]], **_IO_OPTS)
        out = await workflow.execute_activity(
            "resume_chat", args=[s["doc"], s["turns"], inp["message"]], **_CHAT_OPTS)
        return await workflow.execute_activity(
            "chat_append", args=[inp["sid"], inp["message"], out], **_IO_OPTS)


@workflow.defn
class EndChat:
    """저장 또는 버림. 저장은 sync_repo 후 해시 게이트를 거친다."""

    @workflow.run
    async def run(self, inp: dict) -> str:       # {"sid","save": bool}
        if not inp["save"]:
            return await workflow.execute_activity("chat_discard", inp["sid"], **_IO_OPTS)
        await workflow.execute_activity("sync_repo", **_IO_OPTS)
        return await workflow.execute_activity("chat_save", inp["sid"], **_IO_OPTS)
```

`worker.py`:
- io 커맨드: `acts`에 `io_acts.chat_load, io_acts.chat_append, io_acts.chat_save, io_acts.chat_discard`
  추가, `workflows=[...]`에 `ResumeChat, EndChat` 추가.
- llm 커맨드: 워커를 하나 더 띄우고 `asyncio.gather`로 함께 돌린다 —
```python
workers = [
    Worker(client, task_queue=Q_LLM, activities=[...기존...],
           activity_executor=ThreadPoolExecutor(2),
           max_task_queue_activities_per_second=0.5),
    # 채팅은 사람이 기다리는 대화라 판정 레이트리밋을 걸지 않는다
    Worker(client, task_queue=Q_CHAT, activities=[judge_mod.resume_chat],
           activity_executor=ThreadPoolExecutor(2)),
]
await asyncio.gather(*(w.run() for w in workers))
```

- [ ] 구현 (config → judge → io_acts → workflow → worker)
- [ ] tests/test_io_acts.py (`monkeypatch`로 `io_acts.CHAT_DIR`를 `tmp_path/"chat"`로):
      - `test_chat_load_creates_session` — 새 sid면 `doc == base_doc == 원문`, turns 빈 배열
      - `test_chat_append_applies_and_skips` — edits 3개(정상 1·원문 불일치 1·중복 인용 1) →
        `doc`에 1건만 반영, `turns[-1]["applied"] == 1`, `skipped` 2건
      - `test_chat_save_rejects_changed_file` — 세션 만든 뒤 대상 파일을 밖에서 고치고
        `chat_save` → `RuntimeError`
      - `test_chat_save_writes_and_archives` — 정상 경로에서 파일 내용이 `doc`이 되고
        버퍼가 `CHAT_DONE`으로 이동
      - `test_chat_load_rejects_bad_sid` — `"../../etc"` → `ValueError`
- [ ] tests/test_workflow.py의 기존 **자격증명 격리 테스트가 그대로 통과하는지 확인**
      (`resume_chat`은 judge.py에 두므로 web·io_acts·workflow는 여전히 judge를 import하지 않는다).
      실패하면 import 경로를 잘못 넣은 것이다 — 테스트를 고치지 말고 코드를 고칠 것
- [ ] tests/test_judge.py: `test_resume_chat_returns_reply_and_edits` —
      `judge._claude`를 monkeypatch해 `{"structured_output": {"edits": [...], "reply": "..."}}`
      반환 → `resume_chat`이 그대로 dict로 넘기는지 + system 프롬프트에 사실베이스가 실렸는지
- [ ] `uv run pytest -q` 통과 → 커밋 `feat: 이력서 채팅 백엔드 — 세션 버퍼·턴·저장`

---

### Task 4: 채팅 화면

**Files:** `jobscouter/web.py`, `tests/test_web.py`

**Interfaces (Consumes):** Task 3의 버퍼 스키마·`ResumeChat`·`EndChat`, Task 2의 `resume_target`.

web 신규 import: `difflib`, `config.CHAT_DIR`, `config.SID_RE`, `workflow.ResumeChat`, `workflow.EndChat`.

**Interfaces (Produces):**
- `web.start_resume_chat(sid: str, key: str, message: str) -> dict` —
  `await client.execute_workflow(ResumeChat.run, {"sid": sid, "key": key, "message": message},
  id=f"chat-{sid}-{n}", task_queue=Q_WF)`. `n`은 현재 버퍼의 `len(turns)`(없으면 0).
  **결과를 기다린다** — 반환은 갱신된 세션 dict. **monkeypatch 지점.**
- `web.end_chat(sid: str, save: bool) -> str` — `EndChat.run`을
  `id=f"endchat-{sid}"`로 실행하고 결과 문자열 반환. **monkeypatch 지점.**
- `web.load_chat(sid: str) -> dict | None` — `CHAT_DIR/{sid}.json` 읽기(읽기 전용). 없으면 `None`.
- `GET /resume/chat?key=JK.md` — `resume_target(key)` 검증(실패 400) 후
  `sid = uuid4().hex[:12]` 발급 → 302 `/resume/chat/{sid}?key={key}`
- `GET /resume/chat/{sid}?key=...` — `SID_RE` 검증(실패 400). 버퍼가 있으면 그 `target`을 쓰고,
  없으면 쿼리의 `key`를 쓴다(첫 턴 전). 화면 2단:
  - 좌: 대화 목록(`turns`) + 입력 `textarea` 폼(`POST /resume/chat/{sid}`, hidden `key`).
    assistant 턴에는 `applied N건` 배지와 `skipped` 사유를 작은 글씨로 표시한다.
  - 우: `difflib.unified_diff(base_doc.splitlines(), doc.splitlines(), "저장 전", "현재", lineterm="")`
    결과를 `<pre>`로. 버퍼가 없으면 "아직 수정 없음". 아래에 `저장`·`버림` 버튼
    (`POST /resume/chat/{sid}/end`, hidden `save=1|0`).
- `POST /resume/chat/{sid}` — form `key`, `message`. 검증 후 `await start_resume_chat(...)` →
  302 `/resume/chat/{sid}?key={key}`. 빈 메시지는 그냥 302(무시).
- `POST /resume/chat/{sid}/end` — form `save`. `await end_chat(sid, save == "1")` →
  302 `/resume`.
- `/resume`에 「진행 중 대화」 절 — `CHAT_DIR/*.json`을 훑어 `target`·턴수·링크를 보여주고,
  각 문서 섹션 옆에 `대화로 고치기`(`/resume/chat?key=...`) 링크를 붙인다.

**구현 메모:**
- `ponytail:` 턴 POST가 LLM 응답까지 블록한다(최대 6분). LAN 개인 도구라 이걸로 충분하다.
  지연이 거슬리면 워크플로를 시작만 하고 페이지에서 폴링으로 바꾼다.
- CSP가 인라인 스크립트를 막는다. JS 없이 폼 제출만으로 동작해야 한다.

- [ ] 구현
- [ ] tests/test_web.py (`monkeypatch`로 `web.CHAT_DIR`를 tmp로):
      - `test_chat_new_session_redirects` — `GET /resume/chat?key=JK.md` → 302,
        location이 `/resume/chat/<12자리 hex>?key=JK.md`
      - `test_chat_rejects_bad_key` — `?key=../etc/passwd` → 400
      - `test_chat_rejects_bad_sid` — `GET /resume/chat/..%2f..%2fetc` → 400
      - `test_chat_page_renders_turns_and_diff` — 버퍼 json을 직접 써 두고 GET →
        대화 텍스트·`applied` 배지·diff의 `+` 줄이 보인다
      - `test_chat_post_starts_workflow` — `start_resume_chat` monkeypatch → 302 + 인자 확인
      - `test_chat_end_save_and_discard` — `end_chat` monkeypatch, `save=1`/`save=0` 각각 인자 확인
- [ ] `uv run pytest -q` 통과 → 커밋 `feat: 이력서 채팅 화면`

---

### Task 5: 라이브 검증 + 문서 (메인 세션)

**Files:** `README.md` (`deploy/SERVER_SETUP.md`·`compose.yaml`은 변경 없음 — 버퍼가 이미 마운트된 경로 안이라서)

- [ ] README 라우트 표에 추가: `/resume/chat` (대화로 이력서 수정 — 세션 버퍼, 저장 시 커밋),
      `/resume/history` (수정 이력·되돌리기), `/applications`에 등재 공고 초안 요청 버튼.
      큐 설명에 `Q_CHAT` 한 줄(판정 레이트리밋과 분리된 대화 큐).
- [ ] 서버 배포: 코드 갱신 후 `docker compose -f deploy/compose.yaml up -d --build io llm web`.
      **compose 변경은 없다** — 버퍼가 이미 마운트된 `${DATA_REPO}/tmp/` 아래라서.
      `llm` 컨테이너 로그에 `Q_CHAT` 워커 시작 줄이 보이는지 확인.
- [ ] 라이브 1: `/applications`에서 등재 공고 하나에 「초안 만들기」 → 몇 분 뒤 폴더 생성 확인
- [ ] 라이브 2: `/resume/chat?key=JK.md`에서 2~3턴 대화 → 우측 diff 확인 → `저장` →
      데이터 repo에 커밋 1개 + push 확인
- [ ] 라이브 3: `/resume/history?key=JK.md`에서 방금 커밋의 diff 확인 → 직전 커밋으로 되돌리기 →
      새 커밋이 쌓이고 내용이 복원되는지 확인
- [ ] 라이브 4: 저장 충돌 — 채팅 세션을 연 채 `worker apply-resume`나 직접 편집으로 같은 파일을
      바꾼 뒤 `저장` → 거부 메시지가 뜨는지
- [ ] 커밋 `docs: v3 이력서 채팅·이력 운영 문서`
