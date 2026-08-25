"""DailyScan/Publish — 결정론적 오케스트레이션만. 파일IO·네트워크·시계 직접 사용 금지."""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from jobscouter.config import Q_IO, Q_LLM, PublishParams, ScanParams

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


@workflow.defn
class DailyScan:
    """무인 일일 스캔: sync → fetch → 미점수 전부 judge(예산 강등) → proposals.json 갱신."""

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
        await workflow.execute_activity("run_script", "fetch_jobs.py", **_IO_OPTS)

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
                # 우아한 강등 — 판정 없이 미점수로 남긴다 (build.py가 집계·보고)
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
                    spent += r["usage"].get("in", 0) + r["usage"].get("out", 0)
            self._stage = f"판정 {min(i + params.chunk, len(targets))}/{len(targets)}"
        self._spent = spent

        self._stage = "정리"
        proposals = [j for j in self._judged if not j["exclude"]]
        n = await workflow.execute_activity("save_proposals", proposals, **_IO_OPTS)

        self._stage = "완료"
        return {
            "targets": len(targets), "judged": len(self._judged),
            "excluded": sum(1 for j in self._judged if j["exclude"]),
            "demoted": len(self._demoted), "failed": len(self._failed),
            "spent_tokens": self._spent, "proposals": n,
        }


@workflow.defn
class Publish:
    """웹앱 승인 버튼이 시작. 등재·거부 반영 → refresh → build → 리포트."""

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
            "run_script", "refresh_due.py", **_IO_OPTS)
        self._stage = "build"
        out["build"] = await workflow.execute_activity(
            "run_script", "build.py", **_IO_OPTS)

        self._stage = "report"
        stats = {
            "published": len(approved), "rejected": len(params.rejects),
            "proposals_remaining": out["proposals"],
            "commit": out["commit"], "reject": out["reject"],
        }
        out["report"] = await workflow.execute_activity("report", stats, **_LLM_OPTS)

        self._stage = "산출물 커밋"
        out["commit_outputs"] = await workflow.execute_activity("commit_outputs", **_IO_OPTS)

        self._stage = "완료"
        return out
