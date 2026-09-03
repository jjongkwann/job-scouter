"""DailyScan/Publish/Drafts/Draft — 결정론적 오케스트레이션만. 파일IO·네트워크·시계 직접 사용 금지.
초안(_draft)은 listed_target dict(판정 scores·reason 포함)를 그대로 LLM에 넘긴다."""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, ChildWorkflowError, WorkflowAlreadyStartedError

from jobscouter.config import Q_CHAT, Q_IO, Q_LLM, PublishParams, ScanParams

_IO_OPTS = dict(
    task_queue=Q_IO,
    start_to_close_timeout=timedelta(minutes=10),
    retry_policy=RetryPolicy(maximum_attempts=3),
)
_LLM_OPTS = dict(
    task_queue=Q_LLM,
    start_to_close_timeout=timedelta(minutes=5),
    retry_policy=RetryPolicy(maximum_attempts=3),
)
_DRAFT_OPTS = {**_LLM_OPTS, "start_to_close_timeout": timedelta(minutes=15)}
_CHAT_OPTS = dict(
    task_queue=Q_CHAT,
    start_to_close_timeout=timedelta(minutes=6),
    retry_policy=RetryPolicy(maximum_attempts=2),
)


async def _draft(target: dict) -> str:
    """공고 전문 → LLM 초안 5종(target의 판정 점수·사유 활용) → applications/{회사}_{공고id}/에
    기록(커밋·push). 파일명 검증은 draft_application 안 — 틀리면 LLM 단계가 재시도된다."""
    posting = await workflow.execute_activity("fetch_posting_full", target, **_IO_OPTS)
    files = await workflow.execute_activity(
        "draft_application", args=[target, posting], **_DRAFT_OPTS)
    return await workflow.execute_activity(
        "write_application", args=[target, files], **_IO_OPTS)


@workflow.defn
class Draft:
    """등재된 공고 하나의 지원서류 초안 (재)생성 — 웹 버튼·`worker draft`가 시작하고 Drafts도 자식으로 쓴다.
    listed_target이 돌려준 dict(scores·reason 포함)를 그대로 _draft에 넘긴다."""

    @workflow.run
    async def run(self, cid: str) -> str:
        await workflow.execute_activity("sync_repo", **_IO_OPTS)
        target = await workflow.execute_activity("listed_target", cid, **_IO_OPTS)
        return await _draft(target)


def _cause(e: BaseException) -> str:
    """Temporal은 activity 예외를 여러 겹으로 감싼다 — 실제 사유는 __cause__ 끝에 있다."""
    while e.__cause__ is not None:
        e = e.__cause__
    return str(e).split("\n")[0][:200]


@workflow.defn
class Drafts:
    """Publish 완료 직후 시작(ABANDON — Publish는 기다리지 않는다). 승인건마다 Draft 자식을
    순차 실행 — LLM 초안은 건당 몇 분이라 Publish 안에서 돌리면 대시보드 잠금(409)이 그만큼
    길어진다. 하나가 실패해도 나머지는 계속하고, 끝에 실패가 있으면 FAILED로 끝나
    SSE 토스트·최근 실행 목록에 드러난다(성공한 건은 이미 커밋됨)."""

    def __init__(self) -> None:
        self._stage = "시작"

    @workflow.query
    def status(self) -> dict:
        return {"stage": self._stage}

    @workflow.run
    async def run(self, cids: list[str]) -> dict:
        done: dict[str, str] = {}
        failed: dict[str, str] = {}
        for i, cid in enumerate(cids, 1):
            self._stage = f"초안 {i}/{len(cids)}"
            try:
                # 웹 버튼·`worker draft`와 같은 id — 사람이 먼저 시작해 둔 것과 겹쳐 만들지 않는다
                done[cid] = await workflow.execute_child_workflow(
                    Draft.run, cid, id=f"draft-{cid}")
            except WorkflowAlreadyStartedError:
                failed[cid] = "이미 실행 중"
            except ChildWorkflowError as e:
                failed[cid] = _cause(e)
        self._stage = "완료"
        if failed:
            raise ApplicationError(
                f"초안 실패 {len(failed)}건: " + ", ".join(f"{k} — {v}" for k, v in failed.items()),
                non_retryable=True)
        return {"done": done, "failed": failed}


@workflow.defn
class DailyScan:
    """무인 일일 스캔: sync → fetch → 미판정 전부 judge(예산 강등) → proposals.json 갱신.
    판정 결과는 exclude까지 전부 저장한다 — 다음 스캔이 같은 공고를 다시 판정하지 않도록."""

    def __init__(self) -> None:
        self._stage = "시작"
        self._judged: list[dict] = []
        self._demoted: list[str] = []
        self._failed: list[str] = []
        self._spent = 0

    @workflow.query
    def status(self) -> dict:
        prop = [{"id": j["id"], "company": j["company"], "title": j["title"],
                 "total": j["total"], "confidence": j["confidence"]}
                for j in self._judged if not j["exclude"]]
        return {"stage": self._stage, "judged": len(self._judged),
                "excluded": sum(1 for j in self._judged if j["exclude"]),
                "demoted": self._demoted, "failed": self._failed,
                "spent_tokens": self._spent,
                "proposals": sorted(prop, key=lambda p: -p["total"])}

    @workflow.run
    async def run(self, params: ScanParams) -> dict:
        self._stage = "동기화"
        await workflow.execute_activity("sync_repo", **_IO_OPTS)

        self._stage = "fetch"
        await workflow.execute_activity("fetch_jobs", **_IO_OPTS)

        self._stage = "대상 선정"
        targets = await workflow.execute_activity("load_targets", **_IO_OPTS)

        if not targets:
            self._stage = "정리"
            n = await workflow.execute_activity("save_proposals", [], **_IO_OPTS)
            self._stage = "완료"
            return {"targets": 0, "judged": 0, "excluded": 0, "demoted": 0,
                    "failed": 0, "spent_tokens": 0, "proposals": n}

        self._stage = f"판정 0/{len(targets)}"
        spent = 0
        for i in range(0, len(targets), params.chunk):
            if spent >= params.budget_tokens:
                # 우아한 강등 — 판정 없이 미점수로 남긴다
                self._demoted = [t["id"] for t in targets[i:]]
                break
            batch = targets[i:i + params.chunk]

            async def _one(t):
                req = await workflow.execute_activity(
                    "fetch_requirements", t, **_IO_OPTS)
                ctx = await workflow.execute_activity(
                    "search_context", args=[t, req], **_IO_OPTS)
                j = await workflow.execute_activity(
                    "judge",
                    {"target": t, "requirements": req,
                     "search_context": ctx, "max_usd": params.max_usd},
                    **_LLM_OPTS)
                return {**j, "url": t["url"], "src": t["src"]}

            results = await asyncio.gather(
                *(_one(t) for t in batch), return_exceptions=True)
            for t, r in zip(batch, results):
                if isinstance(r, BaseException):
                    self._failed.append(t["id"])   # 재시도 소진 — 미점수로 남음
                else:
                    self._judged.append(r)
                    if not r.get("cached"):   # 캐시 적중은 LLM 지출 0 — 예산에 안 센다
                        spent += r["usage"].get("in", 0) + r["usage"].get("out", 0)
            self._stage = f"판정 {min(i + params.chunk, len(targets))}/{len(targets)}"
        self._spent = spent

        self._stage = "정리"
        n = await workflow.execute_activity("save_proposals", self._judged, **_IO_OPTS)

        self._stage = "완료"
        return {
            "targets": len(targets), "judged": len(self._judged),
            "excluded": sum(1 for j in self._judged if j["exclude"]),
            "demoted": len(self._demoted), "failed": len(self._failed),
            "spent_tokens": self._spent, "proposals": n,
        }


@workflow.defn
class Publish:
    """웹앱 승인 버튼이 시작. 등재·거부 반영 → refresh → 리포트 → 산출물 커밋, 그 뒤 승인건
    초안은 Drafts 자식 워크플로에 넘기고 바로 끝난다."""

    def __init__(self) -> None:
        self._stage = "시작"

    @workflow.query
    def status(self) -> dict:
        return {"stage": self._stage}

    @workflow.run
    async def run(self, params: PublishParams) -> dict:
        out: dict = {}

        self._stage = "동기화"
        out["sync"] = await workflow.execute_activity("sync_repo", **_IO_OPTS)

        self._stage = "불러오기"
        approved = await workflow.execute_activity(
            "load_proposals", params.ids, **_IO_OPTS)

        self._stage = "등재"
        out["commit"] = await workflow.execute_activity(
            "commit_rows", approved, **_IO_OPTS)

        self._stage = "거부 처리"
        out["reject"] = await workflow.execute_activity(
            "reject_proposals", params.rejects, **_IO_OPTS)

        self._stage = "정리"
        out["proposals"] = await workflow.execute_activity(
            "save_proposals", [], **_IO_OPTS)

        self._stage = "refresh"
        out["refresh"] = await workflow.execute_activity(
            "refresh_due", **_IO_OPTS)

        self._stage = "report"
        stats = {
            "published": len(approved), "rejected": len(params.rejects),
            "proposals_remaining": out["proposals"],
            "commit": out["commit"], "reject": out["reject"],
        }
        out["report"] = await workflow.execute_activity("report", stats, **_LLM_OPTS)

        self._stage = "산출물 커밋"
        out["outputs"] = await workflow.execute_activity("commit_outputs", **_IO_OPTS)

        # commit_outputs 뒤에 시작해야 같은 clone에서 git 작업이 겹치지 않는다(index.lock 경합).
        # ABANDON — Publish는 여기서 끝나 대시보드 잠금이 풀리고 Drafts는 독립 실행된다.
        out["drafts"] = ""
        if approved:
            child = await workflow.start_child_workflow(
                Drafts.run, [a["id"] for a in approved],
                id=f"drafts-{workflow.info().workflow_id}",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON)
            out["drafts"] = child.id

        self._stage = "완료"
        return out


@workflow.defn
class ResumeSync:
    """주 1회 무인: PKB curated 스냅샷 → 해시 게이트(변화 없으면 LLM 0) → 갱신 제안."""

    def __init__(self) -> None:
        self._stage = "시작"

    @workflow.query
    def status(self) -> dict:
        return {"stage": self._stage}

    @workflow.run
    async def run(self) -> dict:
        self._stage = "동기화"
        await workflow.execute_activity("sync_repo", **_IO_OPTS)

        self._stage = "PKB 스냅샷"
        snap = await workflow.execute_activity("pkb_snapshot", **_IO_OPTS)

        self._stage = "해시 비교"
        prev = await workflow.execute_activity("resume_state_hash", **_IO_OPTS)
        if snap["hash"] == prev:
            self._stage = "완료"
            return {"changed": False, "docs": snap["docs"]}

        self._stage = "제안 생성"
        proposals = await workflow.execute_activity(
            "propose_resume_update", snap["text"], **_LLM_OPTS)

        self._stage = "저장"
        n = await workflow.execute_activity(
            "save_resume_proposals", args=[proposals, snap["hash"]], **_IO_OPTS)

        self._stage = "완료"
        return {"changed": True, "docs": snap["docs"], "proposals": n}


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


@workflow.defn
class RevertFile:
    """웹 되돌리기 버튼이 시작. 과거 커밋 내용을 새 커밋으로 올린다."""

    @workflow.run
    async def run(self, inp: dict) -> str:      # {"key": str, "sha": str}
        await workflow.execute_activity("sync_repo", **_IO_OPTS)
        return await workflow.execute_activity(
            "git_revert", args=[inp["key"], inp["sha"]], **_IO_OPTS)


@workflow.defn
class ApplyResume:
    """웹앱 승인 버튼이 시작. 사실베이스·이력서.md에 승인 항목 반영 → 사실 재색인."""

    def __init__(self) -> None:
        self._stage = "시작"

    @workflow.query
    def status(self) -> dict:
        return {"stage": self._stage}

    @workflow.run
    async def run(self, ids: list[str]) -> dict:
        self._stage = "동기화"
        await workflow.execute_activity("sync_repo", **_IO_OPTS)

        self._stage = "반영"
        applied = await workflow.execute_activity("apply_resume", ids, **_IO_OPTS)

        self._stage = "재색인"
        reindexed = await workflow.execute_activity("reindex_facts", **_IO_OPTS)

        self._stage = "완료"
        return {"applied": applied, "reindexed": reindexed}
