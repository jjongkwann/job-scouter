"""워크플로 로직 체크 — activity는 스텁, 서버는 time-skipping 테스트 환경."""
import uuid

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from jobscouter.config import CycleParams
from jobscouter.workflow import JobScoutCycle

RAN: list[str] = []
COMMITTED: list[str] = []


@activity.defn(name="sync_repo")
async def fake_sync_repo() -> str:
    return "원격 없음 — 동기화 생략"


@activity.defn(name="run_script")
async def fake_run_script(name: str) -> str:
    RAN.append(name)
    return f"ok:{name}"


@activity.defn(name="load_targets")
async def fake_load_targets() -> list[dict]:
    return [{"id": f"t{i}", "company": f"c{i}", "title": "포지션",
             "src": "wanted", "url": "u"} for i in range(4)]


@activity.defn(name="fetch_requirements")
async def fake_fetch_requirements(t: dict) -> str:
    return "필수: Python"


@activity.defn(name="search_context")
async def fake_search_context(t: dict, requirements: str) -> str:
    return "판례: ..."


@activity.defn(name="judge")
async def fake_judge(inp: dict) -> dict:
    i = int(inp["target"]["id"][1:])
    return {"id": inp["target"]["id"], "company": inp["target"]["company"],
            "title": "포지션", "scores": [30, 18, 20, 16, 0], "total": 84,
            "exclude": i % 2 == 1, "reason": "r", "quotes": [],
            "confidence": 0.9, "rubric_version": "v1",
            "usage": {"in": 60_000, "out": 1_000}, "cached": False}


@activity.defn(name="commit_rows")
async def fake_commit_rows(approved: list[dict], dry_run: bool) -> str:
    COMMITTED.extend(j["id"] for j in approved)
    return f"등재 {len(approved)}건"


@activity.defn(name="report")
async def fake_report(stats: dict) -> str:
    return "jobfeed/reports/2026-08-24_자동사이클.md"


_ACTS = [fake_sync_repo, fake_run_script, fake_load_targets, fake_fetch_requirements,
         fake_search_context, fake_judge, fake_commit_rows, fake_report]


async def _run_cycle(client: Client, send_signal: bool,
                     approve: list[str] | None = None) -> dict:
    q = f"test-{uuid.uuid4()}"
    async with Worker(client, task_queue=q, workflows=[JobScoutCycle],
                      activities=_ACTS,
                      # 샌드박스는 workflow 모듈을 격리된 사본으로 재로드해
                      # 아래 monkeypatch가 보이지 않는다(temporalio 1.31 실측) —
                      # 테스트는 unsandboxed로 돌려 호스트 모듈 상태를 공유한다
                      workflow_runner=UnsandboxedWorkflowRunner()):
        # 테스트에서는 wf·io·llm을 한 큐로 — 큐 분리는 운영 배치의 문제지 로직의 문제가 아니다
        import jobscouter.workflow as wf
        wf._IO_OPTS["task_queue"] = q
        wf._LLM_OPTS["task_queue"] = q
        handle = await client.start_workflow(
            JobScoutCycle.run, CycleParams(browser_wait_minutes=1),
            id=f"wf-{uuid.uuid4()}", task_queue=q)
        if send_signal:
            await handle.signal(JobScoutCycle.browser_done, "수동 완료")
        await handle.signal(JobScoutCycle.approve, approve if approve is not None else [])
        return await handle.result()


@pytest.mark.asyncio
async def test_signal_and_timeout_paths():
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        RAN.clear()
        out = await _run_cycle(env.client, send_signal=True)
        assert out["browser"] == "수동 완료"
        assert RAN == ["fetch_jobs.py", "refresh_due.py", "build.py"]
        assert out["judge"]["judged"] == 4
        assert out["judge"]["demoted"] == 0
        assert out["report"]

        out = await _run_cycle(env.client, send_signal=False)
        assert "타임아웃" in out["browser"]  # 대기 무한 아님 — 강등 경로
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_budget_demotion():
    """chunk=2, 예산 100k, judge당 61k → 1청크(2건) 판정 후 잔여 2건 강등."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        q = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=q, workflows=[JobScoutCycle],
                          activities=_ACTS,
                          workflow_runner=UnsandboxedWorkflowRunner()):
            import jobscouter.workflow as wf
            wf._IO_OPTS["task_queue"] = q
            wf._LLM_OPTS["task_queue"] = q
            handle = await env.client.start_workflow(
                JobScoutCycle.run,
                CycleParams(browser_wait_minutes=1, budget_tokens=100_000, chunk=2),
                id=f"wf-{uuid.uuid4()}", task_queue=q)
            await handle.signal(JobScoutCycle.browser_done, "ok")
            await handle.signal(JobScoutCycle.approve, [])
            out = await handle.result()
            assert out["judge"]["judged"] == 2
            assert out["judge"]["demoted"] == 2   # 예산 초과 → 미점수 강등
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_running_handle_finds_cycle():
    # time-skipping 테스트 서버는 ListWorkflowExecutions(visibility)를
    # 구현하지 않는다(실측: RPCError unimplemented) — 이 테스트만 로컬 dev 서버.
    env = await WorkflowEnvironment.start_local()
    try:
        q = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=q, workflows=[JobScoutCycle],
                          activities=[fake_sync_repo, fake_run_script, fake_load_targets,
                                      fake_fetch_requirements, fake_judge,
                                      fake_search_context, fake_commit_rows,
                                      fake_report],
                          workflow_runner=UnsandboxedWorkflowRunner()):
            import jobscouter.workflow as wf
            wf._IO_OPTS["task_queue"] = q
            wf._LLM_OPTS["task_queue"] = q
            started = await env.client.start_workflow(
                JobScoutCycle.run, CycleParams(browser_wait_minutes=1),
                id=f"wf-{uuid.uuid4()}", task_queue=q)
            from jobscouter.worker import _running_handle
            h = await _running_handle(env.client)
            assert h.id == started.id
            await started.signal(JobScoutCycle.browser_done, "ok")
            await started.signal(JobScoutCycle.approve, [])
            await started.result()
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_approve_selects_candidate():
    """judge 스텁: t0·t2 비제외, t1·t3 제외(i%2==1). approve(["t0"])면 t0만 커밋된다."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        COMMITTED.clear()
        out = await _run_cycle(env.client, send_signal=True, approve=["t0"])
        assert COMMITTED == ["t0"]
        assert out["commit"] == "등재 1건"
    finally:
        await env.shutdown()
