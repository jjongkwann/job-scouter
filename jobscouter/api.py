"""JSON API(:8091) — 데이터 repo를 읽고(마운트는 :ro) Temporal 워크플로를 시작한다. HTML 없음.
브라우저는 web(Next.js)만 보고, web의 라우트 핸들러가 여기로 넘긴다.

파일은 쓰지 않는다 — 쓰기는 전부 워크플로 시작. Temporal 접근은 module-level 함수로 모아
테스트에서 monkeypatch한다. 파생값(추천도·순위·마감·통근·평판)은 candidates.py 한 곳."""
import asyncio
import difflib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()  # 로컬 개발: .env의 서버 주소 — 컨테이너는 compose env가 덮는다

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from temporalio.client import Client

from jobscouter.candidates import (KST, MAX, app_folders, candidate_rows, due_label, dues,
                                   reputation, validate)
from jobscouter.config import (APPLICATIONS, CHAT_DIR, JOBFEED, PROPOSALS, Q_WF, REFERENCES,
                               RESUME, RESUME_PROPOSALS, SID_RE, TEMPORAL, PublishParams,
                               _norm, git_path_at, resume_target)
from jobscouter.workflow import ApplyResume, Draft, EndChat, Publish, ResumeChat, RevertFile

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# 무인증 LAN API의 브라우저 경유 공격 차단 — 이 레포 데이터에는 이력서·연락처가 있다.
# Host 허용: IPv4 리터럴 · localhost · 점 없는 LAN 이름(docker 내부 이름 api 포함) · *.local
_HOST_OK = re.compile(r"(\d{1,3}(\.\d{1,3}){3}|localhost|[\w-]+|[\w-]+\.local)")
_SHA = re.compile(r"[0-9a-f]{7,40}")   # subprocess/경로에 쓰기 전 형식 검증 — resume_target()과 같은 이유
# stage를 물어볼 수 있는 워크플로 — status 쿼리가 있는 것만
_STATUS_TYPES = {"DailyScan", "Publish", "Drafts", "ResumeSync", "ApplyResume"}
_WF_TYPES = ("DailyScan", "Publish", "Drafts", "ResumeSync", "ApplyResume", "Draft", "RevertFile",
             "ResumeChat", "EndChat")
_DEFAULT_KEY = "이력서.md"          # 이력서 정본 한 문서 — key를 생략하면 이것
EVENT_TICKS: int | None = None      # SSE 루프 상한 — 테스트만 설정


@app.middleware("http")
async def _lan_guard(request: Request, call_next):
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if not _HOST_OK.fullmatch(host):
        return JSONResponse({"detail": "허용되지 않은 Host"}, status_code=403)
    # 다른 사이트가 승인·반영을 대신 제출하는 것(CSRF) 차단 — 브라우저가 붙이는 Sec-Fetch-Site 기준.
    # web(Next.js)의 프록시가 이 헤더를 그대로 넘긴다.
    if request.method == "POST" and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return JSONResponse({"detail": "cross-site 요청 거부"}, status_code=403)
    resp = await call_next(request)
    # 나머지 보안 헤더(CSP·X-Frame-Options·Referrer-Policy)는 web이 붙인다 — 여긴 JSON뿐
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


def _safe_url(u) -> str:
    """외부 API에서 온 URL — http(s)만 그대로, 나머지는 '#' (javascript: 등 차단)."""
    return u if isinstance(u, str) and u.lower().startswith(("http://", "https://")) else "#"


def _guard(rel: str) -> None:
    """경로 조작 차단 — 절대경로·`..` 세그먼트."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise HTTPException(400, "잘못된 경로")


def _root_cause(e: BaseException) -> str:
    """Temporal은 activity 예외를 두 겹으로 감싼다 — 실제 사유는 __cause__ 끝에 있다
    (2026-08-27 라이브 검증에서 발견)."""
    while e.__cause__ is not None:
        e = e.__cause__
    return str(e).split("\n")[0][:200]


def _target(key: str) -> Path:
    try:
        return resume_target(key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")


def _sid(sid: str) -> str:
    if not SID_RE.fullmatch(sid):
        raise HTTPException(400, "잘못된 세션 id")
    return sid


# --- git 읽기 (읽기 전용 — 자격증명 불필요) -----------------------------------

def _git_log(rel: str, n: int = 30) -> list[dict]:
    """[{"sha","date","subject"}] — 해당 파일을 건드린 커밋만. --follow라 이름을 바꾸기 전
    이력도 이어진다(JK.md → 이력서.md)."""
    r = subprocess.run(
        ["git", "-C", str(JOBFEED.parent), "log", f"-{n}", "--follow",
         "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M", "--", rel],
        capture_output=True, text=True, timeout=20)
    out = []
    for ln in r.stdout.splitlines():
        sha, _, rest = ln.partition("\t")
        d, _, subject = rest.partition("\t")
        out.append({"sha": sha, "date": d, "subject": subject})
    return out


def _git_show(sha: str, rel: str) -> str:
    """한 커밋이 그 파일에 낸 diff 원문. sha는 호출 전에 검증돼 있어야 한다.
    이름을 바꾸기 전 커밋은 옛 이름으로만 나온다 — git_path_at으로 그 시점 경로를 찾는다."""
    rel = git_path_at(str(JOBFEED.parent), sha, rel)
    r = subprocess.run(
        ["git", "-C", str(JOBFEED.parent), "show", "-p", sha, "--", rel],
        capture_output=True, text=True, timeout=20)
    return r.stdout


def _updated() -> str:
    """candidates.json이 마지막으로 커밋된 날(YYYY-MM-DD). git이 없으면 빈 문자열."""
    try:
        r = subprocess.run(
            ["git", "-C", str(JOBFEED.parent), "log", "-1", "--format=%ad", "--date=short",
             "--", str(JOBFEED / "candidates.json")],
            capture_output=True, text=True, timeout=20)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# --- 데이터 읽기 --------------------------------------------------------------

def _load_proposals() -> list[dict]:
    path = JOBFEED / PROPOSALS
    if not path.exists():
        return []
    # exclude 판정은 재판정 방지용으로만 남긴 것 — 화면에는 안 띄운다
    return sorted((p for p in json.loads(path.read_text()).values() if not p.get("exclude")),
                  key=lambda p: -p.get("total", 0))


def _load_resume_proposals() -> list[dict]:
    path = JOBFEED / RESUME_PROPOSALS
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("items", [])


def _decorate(p: dict, rep: dict[str, str], due_map: dict[str, str], today: date,
              busy: set[str]) -> dict:
    """화면용 파생 필드 — 후보목록 rowHTML과 같은 규칙(hi ≥85%, lo ≤40%, 총점 등급).
    실행 중인 Publish가 처리하는 행은 숨기지 않고 busy로 표시한다 — 왜 못 누르는지 보이게."""
    sc = list(p.get("scores") or []) + [0] * 5
    cells = [(v, "hi" if v / m >= .85 else ("lo" if v / m <= .4 else "")) for v, m in zip(sc, MAX)]
    cells.append((sc[4] or "·", "pen" if sc[4] else ""))
    total = p.get("total", 0)
    due, due_cls = due_label(due_map.get(str(p["id"])), today)
    return {**p, "url": _safe_url(p.get("url")), "cells": cells,
            "tier": "t1" if total >= 80 else "t2" if total >= 70 else "t3",
            "rail": rep.get(_norm(p.get("company", "")), "none"),
            "due": due, "due_cls": due_cls, "busy": str(p["id"]) in busy}


def load_chat(sid: str) -> dict | None:
    """채팅 세션 버퍼 읽기 전용 열람 — api는 이 버퍼에 쓰지 않는다(워크플로만 시작)."""
    path = CHAT_DIR / f"{sid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _chat_sessions() -> list[dict]:
    """진행 중(미저장) 채팅 세션 — CHAT_DIR 바로 아래 json만(끝난 세션은 done/으로 옮겨져 안 걸림)."""
    if not CHAT_DIR.exists():
        return []
    out = []
    for p in sorted(CHAT_DIR.glob("*.json")):
        try:
            s = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append({"sid": s["sid"], "target": s["target"], "n": len(s["turns"]) // 2})
    return out


def _rank_key(c: dict) -> float:
    """정렬용 — rank는 candidate_rows()가 반올림 전 추천도로 매겨 둔 순위. None(마감)은 맨 뒤로."""
    return c["rank"] if c["rank"] is not None else float("inf")


def _folder_docs(folder: dict | None) -> dict[str, str]:
    """{파일명: 마크다운 원문} — 렌더는 클라이언트(react-markdown)가 한다."""
    if not folder:
        return {}
    return {n: (APPLICATIONS / folder["slug"] / n).read_text(errors="replace")
            for n in folder["files"]}


# --- Temporal 접근 — 이 함수들만 client를 만든다. 테스트에서 monkeypatch. ---

async def start_publish(ids: list[str], rejects: list[dict]) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        Publish.run, PublishParams(ids=list(ids), rejects=rejects),
        id=f"publish-{uuid4().hex[:8]}", task_queue=Q_WF)
    return handle.id


async def start_apply_resume(ids: list[str]) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        ApplyResume.run, list(ids),
        id=f"apply-resume-{uuid4().hex[:8]}", task_queue=Q_WF)
    return handle.id


async def start_draft(cid: str) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        Draft.run, cid, id=f"draft-{cid}", task_queue=Q_WF)
    return handle.id


async def start_revert(key: str, sha: str) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        RevertFile.run, {"key": key, "sha": sha},
        id=f"revert-{sha[:7]}-{uuid4().hex[:6]}", task_queue=Q_WF)
    return handle.id


async def start_resume_chat(sid: str, key: str, message: str) -> str:
    """한 턴을 시작만 하고 돌아온다 — LLM 응답은 몇 분 걸린다. 화면은 SSE로 완료를 받는다."""
    buf = load_chat(sid)
    n = len(buf["turns"]) if buf else 0
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        ResumeChat.run, {"sid": sid, "key": key, "message": message},
        id=f"chat-{sid}-{n}", task_queue=Q_WF)
    return handle.id


async def end_chat(sid: str, save: bool) -> str:
    client = await Client.connect(TEMPORAL)
    return await client.execute_workflow(
        EndChat.run, {"sid": sid, "save": save},
        id=f"endchat-{sid}", task_queue=Q_WF)


async def chat_pending(sid: str) -> bool:
    """이 세션의 턴이 아직 돌고 있나. Temporal에 못 붙으면 False(화면은 그냥 안 기다린다)."""
    try:
        client = await Client.connect(TEMPORAL)
        async for wf in client.list_workflows(
                "WorkflowType='ResumeChat' AND ExecutionStatus='Running'", limit=50):
            if wf.id.startswith(f"chat-{sid}-"):
                return True
    except Exception:
        return False
    return False


async def draft_running(cid: str) -> bool:
    try:
        client = await Client.connect(TEMPORAL)
        async for wf in client.list_workflows(
                "WorkflowType='Draft' AND ExecutionStatus='Running'", limit=50):
            if wf.id == f"draft-{cid}":
                return True
    except Exception:
        return False
    return False


async def recent_runs() -> list[dict]:
    # dev 서버(SQLite)는 ORDER BY를 지원하지 않는다 — 넉넉히 받아 여기서 정렬
    client = await Client.connect(TEMPORAL)
    out = []
    async for wf in client.list_workflows(
            " OR ".join(f"WorkflowType='{t}'" for t in
                        ("DailyScan", "Publish", "Drafts", "ResumeSync", "ApplyResume", "Draft")),
            limit=30):
        out.append({"type": wf.workflow_type,
                    "status": wf.status.name if wf.status else "?",
                    "start": wf.start_time.astimezone(KST).strftime("%Y-%m-%d %H:%M")})
    return sorted(out, key=lambda r: r["start"], reverse=True)[:6]


async def latest_publish() -> dict | None:
    """가장 최근 Publish 한 건. 실행 중이면 입력(승인·거부 id) — 대시보드가 그 행을 busy로 표시하고
    제출을 막는다. 실패면 원인 메시지 — 제출 직후 화면이 그대로라 실패를 모르고 지나치지 않게."""
    client = await Client.connect(TEMPORAL)
    latest = None
    async for wf in client.list_workflows("WorkflowType='Publish'", limit=30):
        if latest is None or wf.start_time > latest.start_time:
            latest = wf
    if latest is None:
        return None
    info = {"id": latest.id, "status": latest.status.name if latest.status else "?",
            "start": latest.start_time.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            "ids": [], "reject_ids": [], "error": ""}
    handle = client.get_workflow_handle(latest.id)
    if info["status"] == "RUNNING":
        hist = await handle.fetch_history()
        payload = hist.events[0].workflow_execution_started_event_attributes.input.payloads[0]
        params = json.loads(payload.data)
        info["ids"] = [str(i) for i in params.get("ids") or []]
        info["reject_ids"] = [str(r["id"]) for r in params.get("rejects") or []]
    elif info["status"] == "FAILED":
        if info["id"] not in _ERRORS:          # 실패 원인은 불변 — 틱마다 result() RPC를 반복하지 않는다
            try:
                await handle.result()
                _ERRORS[info["id"]] = ""
            except Exception as e:
                _ERRORS[info["id"]] = _root_cause(e)
        info["error"] = _ERRORS[info["id"]]
    return info


async def _latest_publish_safe() -> dict | None:
    try:
        return await latest_publish()
    except Exception:
        return None


def _wf_row(wid: str, wtype: str, status: str, start) -> dict:
    return {"id": wid, "type": wtype, "status": status, "stage": None, "error": "",
            "start": start.astimezone(KST).strftime("%Y-%m-%d %H:%M") if start else ""}


_ERRORS: dict[str, str] = {}   # FAILED 워크플로 id → 원인 (SSE 틱마다 재조회 방지)


async def _fill(client, info: dict) -> dict:
    """RUNNING이면 stage 쿼리, FAILED면 실패 원인 — 둘 다 실패해도 행은 그대로 낸다."""
    handle = client.get_workflow_handle(info["id"])
    if info["status"] == "RUNNING" and info["type"] in _STATUS_TYPES:
        try:
            info["stage"] = (await handle.query("status")).get("stage")
        except Exception:
            pass
    elif info["status"] == "FAILED":
        if info["id"] not in _ERRORS:          # 실패 원인은 불변 — 틱마다 result() RPC를 반복하지 않는다
            try:
                await handle.result()
                _ERRORS[info["id"]] = ""
            except Exception as e:
                _ERRORS[info["id"]] = _root_cause(e)
        info["error"] = _ERRORS[info["id"]]
    return info


async def workflow_snapshot() -> list[dict]:
    """SSE 한 틱 — 최근 50건의 {id,type,status,stage,error,start}."""
    client = await Client.connect(TEMPORAL)
    out = []
    async for wf in client.list_workflows(
            " OR ".join(f"WorkflowType='{t}'" for t in _WF_TYPES), limit=50):
        out.append(await _fill(client, _wf_row(
            wf.id, wf.workflow_type, wf.status.name if wf.status else "?", wf.start_time)))
    return out


# --- 라우트 -------------------------------------------------------------------

class PublishBody(BaseModel):
    ids: list[str] = []
    rejects: list[dict] = []


class ApplyBody(BaseModel):
    ids: list[str] = []


class RevertBody(BaseModel):
    key: str = _DEFAULT_KEY
    sha: str = ""


class ChatBody(BaseModel):
    key: str = _DEFAULT_KEY


class TurnBody(BaseModel):
    key: str = _DEFAULT_KEY
    message: str = ""


class EndBody(BaseModel):
    save: bool = False


class DraftBody(BaseModel):
    id: str = ""


@app.get("/api/dashboard")
async def dashboard():
    rep = reputation()
    pub = await _latest_publish_safe()
    busy = set(pub["ids"]) | set(pub["reject_ids"]) if pub and pub["status"] == "RUNNING" else set()
    due_map, today = dues(), datetime.now(KST).date()
    proposals = [_decorate(p, rep, due_map, today, busy) for p in _load_proposals()]
    unresearched = sorted({p["company"] for p in proposals if _norm(p["company"]) not in rep})
    runs, runs_error = [], None
    try:
        runs = await recent_runs()
    except Exception as e:
        runs_error = str(e)
    return {"proposals": proposals, "unresearched": unresearched, "runs": runs,
            "runs_error": runs_error, "publish": pub,
            "stats": {"pending": len(proposals),
                      "fit75": sum(1 for p in proposals if p.get("total", 0) >= 75),
                      "gone": sum(1 for p in proposals if p["due_cls"] == "gone"),
                      "unresearched": len(unresearched)}}


@app.post("/api/publish")
async def publish(body: PublishBody):
    pub = await _latest_publish_safe()
    if pub and pub["status"] == "RUNNING":
        # 동시에 두 Publish가 같은 repo에 커밋·push하면 충돌한다 — 끝난 뒤 다시
        raise HTTPException(409, "Publish 실행 중 — 끝난 뒤 다시 제출")
    ids = [str(i) for i in body.ids]
    reject_ids = [str(r.get("id", "")) for r in body.rejects]
    dup = sorted(set(ids) & set(reject_ids))
    if dup:
        raise HTTPException(400, f"같은 공고를 승인과 거부에 동시에 넣을 수 없음: {', '.join(dup)}")
    empty = [rid for rid, r in zip(reject_ids, body.rejects) if not str(r.get("why", "")).strip()]
    if empty:
        raise HTTPException(400, f"거부 사유 없음: {', '.join(empty)}")
    rejects = [{"id": rid, "why": str(r.get("why", "")).strip()}
               for rid, r in zip(reject_ids, body.rejects)]
    return {"workflow_id": await start_publish(ids, rejects)}


@app.get("/api/candidates")
def candidates():
    path = JOBFEED / "candidates.json"
    raw = json.loads(path.read_text())["rows"] if path.exists() else []
    apps = {cid: {"slug": f["slug"], "n": len(f["docs"])}
            for f in app_folders() for cid in f["ids"]}
    return {"rows": candidate_rows(), "apps": apps, "errors": validate(raw), "updated": _updated()}


@app.get("/api/reports")
def reports_index():
    d = JOBFEED / "reports"
    names = sorted((p.stem for p in d.glob("*.md")), reverse=True) if d.exists() else []
    out = []
    for n in names:
        day, _, kind = n.partition("_")
        out.append({"date": day, "kind": kind or "-", "name": n})
    return out


@app.get("/api/reports/{name}")
def report(name: str):
    _guard(name)
    path = JOBFEED / "reports" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "보고서 없음")
    return {"name": name, "markdown": path.read_text()}


@app.get("/api/resume")
def resume():
    return {"markdown": RESUME.read_text() if RESUME.exists() else "",
            "pending": len(_load_resume_proposals()), "chats": _chat_sessions()}


def _resume_rel(key: str) -> str:
    path = _target(key)
    try:
        return str(path.relative_to(JOBFEED.parent))
    except ValueError:
        # 정상 배치에서는 FACTBASE도 데이터 repo 안쪽 — env가 밖으로 잘못 잡힌 경우
        raise HTTPException(400, f"{key}는 데이터 repo 밖에 있어 이력을 볼 수 없습니다")


@app.get("/api/resume/history")
def resume_history(key: str = _DEFAULT_KEY):
    return {"key": key, "commits": _git_log(_resume_rel(key))}


@app.get("/api/resume/history/{sha}")
def resume_diff(sha: str, key: str = _DEFAULT_KEY):
    if not _SHA.fullmatch(sha):
        raise HTTPException(400, "잘못된 sha 형식")
    return {"sha": sha, "diff": _git_show(sha, _resume_rel(key))}


@app.post("/api/resume/revert")
async def resume_revert(body: RevertBody):
    if not _SHA.fullmatch(body.sha):
        raise HTTPException(400, "잘못된 sha 형식")
    _target(body.key)
    return {"workflow_id": await start_revert(body.key, body.sha)}


@app.get("/api/resume/proposals")
def resume_proposals():
    return {"items": _load_resume_proposals()}


@app.post("/api/resume/apply")
async def resume_apply(body: ApplyBody):
    return {"workflow_id": await start_apply_resume(list(body.ids))}


@app.post("/api/resume/chat")
def resume_chat_new(body: ChatBody):
    _target(body.key)
    return {"sid": uuid4().hex[:12]}


@app.get("/api/resume/chat/{sid:path}")
async def resume_chat(sid: str, key: str = _DEFAULT_KEY):
    # sid는 경로 세그먼트 하나여야 하지만 %2f로 인코딩된 슬래시가 라우팅 단계에서 실제
    # 슬래시로 풀려 여러 세그먼트가 될 수 있다 — :path로 받아 여기서 형식 검증한다
    _sid(sid)
    buf = load_chat(sid)
    target_key = buf["target"] if buf else key   # 첫 턴 전(버퍼 없음)엔 요청의 key를 쓴다
    _target(target_key)
    diff = ""
    if buf:
        diff = "\n".join(difflib.unified_diff(
            buf["base_doc"].splitlines(), buf["doc"].splitlines(), "저장 전", "현재", lineterm=""))
    return {"sid": sid, "target": target_key, "exists": buf is not None,
            "turns": buf["turns"] if buf else [], "diff": diff,
            "pending": await chat_pending(sid)}


@app.post("/api/resume/chat/{sid}/turns")
async def resume_chat_turn(sid: str, body: TurnBody):
    _sid(sid)
    _target(body.key)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "빈 메시지")
    return {"workflow_id": await start_resume_chat(sid, body.key, message)}


@app.post("/api/resume/chat/{sid}/end")
async def resume_chat_end(sid: str, body: EndBody):
    _sid(sid)
    try:
        return {"result": await end_chat(sid, body.save)}
    except Exception as e:
        # 저장 거부(대상 파일이 세션 중 바뀜)가 여기로 온다. 세션 버퍼는 그대로 남아 있으므로
        # 스택트레이스 500 대신 이유를 준다 — 2026-08-27 라이브 검증에서 발견.
        cause = _root_cause(e)
        return JSONResponse({"detail": cause, "cause": cause,
                             "conflict": "세션 시작 후" in cause}, status_code=409)


@app.get("/api/applications")
def applications_index():
    cands = {c["id"]: c for c in candidate_rows()}
    linked, orphans = [], []
    for f in app_folders():
        hits = [cands[i] for i in f["ids"] if i in cands]
        if hits:
            c = min(hits, key=_rank_key)
            same = [x for x in cands.values() if _norm(x["company"]) == _norm(c["company"])]
            linked.append({**f, "c": c, "others": len(same) - 1})
        else:
            orphans.append({**f, "why": ("문서의 공고 id가 후보목록에 없음 — 내려갔거나 거부된 공고"
                                         if f["ids"] else "문서 어디에도 공고 링크가 없음"),
                            "badge": "공고 내려감" if f["ids"] else "id 없음",
                            "cls": "warn" if f["ids"] else "bad"})
    linked.sort(key=lambda x: _rank_key(x["c"]))
    return {"stats": {"candidates": len(cands), "folders": len(linked) + len(orphans),
                      "linked": len(linked),
                      "gone": sum(1 for o in orphans if o["ids"]),
                      "unlinked": sum(1 for o in orphans if not o["ids"])},
            "linked": linked, "orphans": orphans}


@app.post("/api/applications/draft")
async def applications_draft(body: DraftBody):
    if body.id not in {c["id"] for c in candidate_rows()}:
        raise HTTPException(400, "등재되지 않은 공고 — 등재된 공고만 초안을 만든다")
    return {"workflow_id": await start_draft(body.id)}


@app.get("/api/applications/job/{cid}")
async def application_job(cid: str, folder: str = ""):
    """공고 한 건 — 후보 행 + 연결된 폴더의 문서 원문. 문서가 없으면 docs가 비어 온다.
    폴더가 여럿(원본 `x_222` + 재생성 슬롯 `x_222_draft`)이면 folders로 전부 주고, `folder`로
    고른 것(없으면 정렬상 앞 = 원본)의 문서를 docs에 담는다 — 재생성본도 화면에서 볼 수 있게."""
    cands = {c["id"]: c for c in candidate_rows()}
    c = cands.get(cid)
    if not c:
        raise HTTPException(404, "등재되지 않은 공고")
    folders = [f for f in app_folders() if cid in f["ids"]]
    sel = next((f for f in folders if f["slug"] == folder), folders[0] if folders else None)
    others = sorted((x for x in cands.values()
                     if _norm(x["company"]) == _norm(c["company"]) and x["id"] != cid),
                    key=_rank_key)
    return {"candidate": c, "folder": sel, "folders": folders, "others": others,
            "docs": _folder_docs(sel), "drafting": await draft_running(cid)}


@app.get("/api/applications/{slug}")
def application(slug: str):
    """공고에 연결되지 않은 폴더 — 문서만. 연결돼 있으면 linked_cid를 주고 화면이 이동한다."""
    _guard(slug)
    if not (APPLICATIONS / slug).exists():
        raise HTTPException(404, "지원서류 없음")
    folder = next((f for f in app_folders() if f["slug"] == slug), None)
    ids = {c["id"] for c in candidate_rows()}
    linked = next((i for i in (folder["ids"] if folder else []) if i in ids), None)
    return {"folder": folder, "docs": _folder_docs(folder), "linked_cid": linked}


@app.get("/api/docs")
def docs_index():
    out = []
    if REFERENCES.exists():
        for p in sorted(REFERENCES.rglob("*.md")):
            rel = p.relative_to(REFERENCES)
            out.append({"path": str(rel), "name": rel.name,
                        "group": str(rel.parent) if rel.parent != Path(".") else "references"})
    return out


@app.get("/api/docs/{path:path}")
def docs_page(path: str):
    _guard(path)
    full = REFERENCES / path
    if full.suffix != ".md" or not full.exists():
        raise HTTPException(404, "문서 없음")
    return {"path": path, "markdown": full.read_text()}


@app.get("/api/workflows/{wid}")
async def workflow_info(wid: str):
    try:
        client = await Client.connect(TEMPORAL)
        d = await client.get_workflow_handle(wid).describe()
    except Exception:
        raise HTTPException(404, "워크플로 없음")
    return await _fill(client, _wf_row(
        d.id, d.workflow_type, d.status.name if d.status else "?", d.start_time))


@app.get("/api/events")
async def events(request: Request):
    """2초마다 스냅샷을 떠서 (status, stage)가 달라진 워크플로만 흘린다."""
    async def gen():
        seen: dict[str, tuple] = {}
        n = 0
        while EVENT_TICKS is None or n < EVENT_TICKS:
            n += 1
            if await request.is_disconnected():
                break
            try:
                snap = await workflow_snapshot()
            except Exception:
                snap = []          # Temporal이 죽어도 연결은 유지 — 살아나면 다시 흐른다
            for w in snap:
                key = (w["status"], w["stage"])
                if seen.get(w["id"]) != key:
                    seen[w["id"]] = key
                    yield f"event: workflow\ndata: {json.dumps(w, ensure_ascii=False)}\n\n"
            if n % 8 == 0:         # 프록시 타임아웃 방지 — 16초마다 코멘트
                yield ": ping\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
