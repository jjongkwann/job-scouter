"""JobScoutCycle — 결정론적 오케스트레이션만. 파일IO·네트워크·시계 직접 사용 금지."""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from jobscouter.config import Q_IO, Q_LLM, CycleParams

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
class JobScoutCycle:
    def __init__(self) -> None:
        self._browser_note: str | None = None
        self._stage = "시작"
        self._judged: list[dict] = []
        self._demoted: list[str] = []
        self._failed: list[str] = []
        self._spent = 0
        self._approved: list[str] | None = None

    @workflow.signal
    def browser_done(self, note: str) -> None:
        self._browser_note = note or "완료"

    @workflow.signal
    def approve(self, ids: list[str]) -> None:
        self._approved = list(ids)

    @workflow.query
    def status(self) -> dict:
        prop = [{"id": j["id"], "company": j["company"], "title": j["title"],
                 "total": j["total"], "confidence": j["confidence"]}
                for j in self._judged if not j["exclude"]]
        return {"stage": self._stage, "browser": self._browser_note,
                "judged": len(self._judged),
                "excluded": sum(1 for j in self._judged if j["exclude"]),
                "demoted": self._demoted, "failed": self._failed,
                "spent_tokens": self._spent,
                "proposals": sorted(prop, key=lambda p: -p["total"])}

    @workflow.run
    async def run(self, params: CycleParams) -> dict:
        out: dict = {}

        self._stage = "fetch"
        out["fetch"] = await workflow.execute_activity(
            "run_script", "fetch_jobs.py", **_IO_OPTS)

        # 판정 대상 = 미점수 전부 (신규 + 백로그)
        self._stage = "대상 선정"
        targets = await workflow.execute_activity("load_targets", **_IO_OPTS)

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
                return await workflow.execute_activity(
                    "judge",
                    {"target": t, "requirements": req,
                     "search_context": ctx, "max_usd": params.max_usd},
                    **_LLM_OPTS)

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
        out["judge"] = {"judged": len(self._judged), "demoted": len(self._demoted),
                        "failed": len(self._failed), "spent_tokens": spent}

        # 수동 반쪽: 원티드 매칭·잡플래닛은 로그인 크롬 필요 — durable 대기
        self._stage = "브라우저 조사 대기"
        try:
            await workflow.wait_condition(
                lambda: self._browser_note is not None,
                timeout=timedelta(minutes=params.browser_wait_minutes))
            out["browser"] = self._browser_note
        except TimeoutError:
            out["browser"] = f"타임아웃({params.browser_wait_minutes}분) — 수동 단계 생략"

        # 등재 후보 배치 승인 — 사람이 signal로 확정해야 candidates.json에 커밋 (DESIGN)
        self._stage = "승인 대기"
        try:
            await workflow.wait_condition(
                lambda: self._approved is not None,
                timeout=timedelta(hours=params.approve_wait_hours))
        except TimeoutError:
            self._approved = []   # 타임아웃 = 등재 없음 — 판정 캐시는 남아 재사용
        chosen = [j for j in self._judged
                  if not j["exclude"] and j["id"] in set(self._approved)]
        self._stage = "커밋"
        out["commit"] = await workflow.execute_activity(
            "commit_rows", args=[chosen, params.dry_run], **_IO_OPTS)

        self._stage = "refresh"
        out["refresh"] = await workflow.execute_activity(
            "run_script", "refresh_due.py", **_IO_OPTS)
        self._stage = "build"
        out["build"] = await workflow.execute_activity(
            "run_script", "build.py", **_IO_OPTS)

        self._stage = "report"
        stats = {
            "targets": len(targets), "judged": len(self._judged),
            "excluded": sum(1 for j in self._judged if j["exclude"]),
            "proposals": len([j for j in self._judged if not j["exclude"]]),
            "approved": len(chosen), "demoted": len(self._demoted),
            "failed": self._failed, "spent_tokens": self._spent,
            "avg_ms": (sum(j["usage"].get("ms", 0) for j in self._judged
                           if not j["cached"])
                       // max(1, sum(1 for j in self._judged if not j["cached"]))),
            "cache_hits": sum(1 for j in self._judged if j["cached"]),
            "commit": out["commit"], "budget": params.budget_tokens,
        }
        out["report"] = await workflow.execute_activity(
            "report", stats, **_LLM_OPTS)
        out["spent_tokens"] = self._spent

        self._stage = "완료"
        return out
