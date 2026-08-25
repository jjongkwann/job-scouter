"""워크플로 로직 체크 — activity는 스텁, 서버는 time-skipping 테스트 환경."""
import asyncio
import uuid

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from jobscouter.config import PublishParams, ScanParams
from jobscouter.workflow import ApplyResume, DailyScan, Publish, ResumeSync

RAN: list[str] = []
SAVED: list[list[dict]] = []
COMMITTED: list[str] = []
REJECTED: list[dict] = []


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
             "src": "wanted", "url": f"u{i}"} for i in range(4)]


@activity.defn(name="load_targets")
async def fake_load_targets_empty() -> list[dict]:
    return []


@activity.defn(name="load_targets")
async def fake_load_targets_slow() -> list[dict]:
    # _running_handle이 실행 중 상태를 잡아낼 시간을 준다(실서버 visibility 지연 대비).
    await asyncio.sleep(1)
    return [{"id": f"t{i}", "company": f"c{i}", "title": "포지션",
             "src": "wanted", "url": f"u{i}"} for i in range(4)]


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


@activity.defn(name="save_proposals")
async def fake_save_proposals(judged: list[dict]) -> int:
    SAVED.append(judged)
    return len(judged)


@activity.defn(name="load_proposals")
async def fake_load_proposals(ids: list[str]) -> list[dict]:
    return [{"id": i, "company": f"c-{i}", "title": "포지션", "url": f"u-{i}", "src": "wanted",
             "scores": [30, 18, 20, 16, 0], "rubric_version": "v1"} for i in ids]


@activity.defn(name="commit_rows")
async def fake_commit_rows(approved: list[dict], dry_run: bool = False) -> str:
    COMMITTED.extend(j["id"] for j in approved)
    return f"등재 {len(approved)}건"


@activity.defn(name="reject_proposals")
async def fake_reject_proposals(rejects: list[dict]) -> int:
    REJECTED.extend(rejects)
    return len(rejects)


@activity.defn(name="report")
async def fake_report(stats: dict) -> str:
    return "jobfeed/reports/2026-08-24_자동사이클.md"


@activity.defn(name="commit_outputs")
async def fake_commit_outputs() -> str:
    return "커밋됨"


@activity.defn(name="fetch_posting_full")
async def fake_fetch_posting_full(t: dict) -> str:
    return f"공고전문:{t['id']}"


@activity.defn(name="draft_application")
async def fake_draft_application(company: str, title: str, posting: str) -> dict:
    return {n: f"{company} {n}" for n in
            ["0_JD.md", "1_맞춤_이력서.md", "2_자기소개서.md",
             "3_면접지식맵.md", "4_포트폴리오_구성.md"]}


@activity.defn(name="write_application")
async def fake_write_application(company: str, files: dict) -> str:
    return f"applications/{company}"


_SCAN_ACTS = [fake_sync_repo, fake_run_script, fake_load_targets, fake_fetch_requirements,
             fake_search_context, fake_judge, fake_save_proposals]
_PUB_ACTS = [fake_sync_repo, fake_load_proposals, fake_commit_rows, fake_reject_proposals,
            fake_save_proposals, fake_run_script, fake_report, fake_commit_outputs,
            fake_fetch_posting_full, fake_draft_application, fake_write_application]


async def _run_scan(client: Client, params: ScanParams | None = None) -> dict:
    q = f"test-{uuid.uuid4()}"
    async with Worker(client, task_queue=q, workflows=[DailyScan], activities=_SCAN_ACTS,
                      # 샌드박스는 workflow 모듈을 격리된 사본으로 재로드해
                      # 아래 monkeypatch가 보이지 않는다(temporalio 1.31 실측) —
                      # 테스트는 unsandboxed로 돌려 호스트 모듈 상태를 공유한다
                      workflow_runner=UnsandboxedWorkflowRunner()):
        import jobscouter.workflow as wf
        wf._IO_OPTS["task_queue"] = q
        wf._LLM_OPTS["task_queue"] = q
        handle = await client.start_workflow(
            DailyScan.run, params or ScanParams(), id=f"wf-{uuid.uuid4()}", task_queue=q)
        return await handle.result()


async def _run_publish(client: Client, params: PublishParams) -> dict:
    q = f"test-{uuid.uuid4()}"
    async with Worker(client, task_queue=q, workflows=[Publish], activities=_PUB_ACTS,
                      workflow_runner=UnsandboxedWorkflowRunner()):
        import jobscouter.workflow as wf
        wf._IO_OPTS["task_queue"] = q
        wf._LLM_OPTS["task_queue"] = q
        handle = await client.start_workflow(
            Publish.run, params, id=f"wf-{uuid.uuid4()}", task_queue=q)
        return await handle.result()


@pytest.mark.asyncio
async def test_daily_scan_saves_non_excluded():
    """judge 스텁: t0·t2 비제외, t1·t3 제외(i%2==1) → save_proposals에 2건만 간다."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        RAN.clear()
        SAVED.clear()
        out = await _run_scan(env.client)
        assert RAN == ["fetch_jobs.py"]
        assert out["judged"] == 4
        assert out["excluded"] == 2
        assert out["demoted"] == 0
        assert {j["id"] for j in SAVED[-1]} == {"t0", "t2"}
        assert all(j["url"] and j["src"] for j in SAVED[-1])   # target url/src 병합됨
        assert out["proposals"] == 2
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_budget_demotion():
    """chunk=2, 예산 100k, judge당 61k → 1청크(2건) 판정 후 잔여 2건 강등."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        out = await _run_scan(env.client, ScanParams(budget_tokens=100_000, chunk=2))
        assert out["judged"] == 2
        assert out["demoted"] == 2   # 예산 초과 → 미점수 강등
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_daily_scan_no_targets_skips_judge_but_cleans_proposals():
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        RAN.clear()
        SAVED.clear()
        q = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=q, workflows=[DailyScan],
                          activities=[fake_sync_repo, fake_run_script,
                                      fake_load_targets_empty, fake_save_proposals],
                          workflow_runner=UnsandboxedWorkflowRunner()):
            import jobscouter.workflow as wf
            wf._IO_OPTS["task_queue"] = q
            handle = await env.client.start_workflow(
                DailyScan.run, ScanParams(), id=f"wf-{uuid.uuid4()}", task_queue=q)
            out = await handle.result()
            assert out == {"targets": 0, "judged": 0, "excluded": 0, "demoted": 0,
                            "failed": 0, "spent_tokens": 0, "proposals": 0}
            assert SAVED == [[]]   # 정리 목적 호출은 갔다
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_publish_commits_approved_and_rejects():
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        RAN.clear()
        COMMITTED.clear()
        REJECTED.clear()
        out = await _run_publish(
            env.client,
            PublishParams(ids=["p0"], rejects=[{"id": "p1", "why": "연봉 미공개"}]))
        assert COMMITTED == ["p0"]
        assert REJECTED == [{"id": "p1", "why": "연봉 미공개"}]
        assert RAN == ["refresh_due.py", "build.py"]
        assert out["commit"] == "등재 1건"
        assert out["reject"] == 1
        assert out["report"]
        assert out["outputs"] == "커밋됨"
        assert out["drafts"] == {"p0": "applications/c-p0"}   # approved 1건 → 초안 완료
    finally:
        await env.shutdown()


PROPOSE_CALLS: list[str] = []
SAVED_RESUME: list[tuple] = []
APPLIED_IDS: list[list] = []


@activity.defn(name="pkb_snapshot")
async def fake_pkb_snapshot() -> dict:
    return {"hash": "H1", "text": "PKB 발췌", "docs": 3}


@activity.defn(name="resume_state_hash")
async def fake_resume_state_hash_same() -> str:
    return "H1"   # pkb_snapshot과 동일 → 변화 없음


@activity.defn(name="resume_state_hash")
async def fake_resume_state_hash_diff() -> str:
    return "H0"   # pkb_snapshot과 다름 → 변화 있음


@activity.defn(name="propose_resume_update")
async def fake_propose_resume_update(snapshot_text: str) -> list[dict]:
    PROPOSE_CALLS.append(snapshot_text)
    return [{"target": "factbase", "section": "경력", "kind": "change",
             "current": "3년차", "proposed": "4년차", "evidence": "e"}]


@activity.defn(name="save_resume_proposals")
async def fake_save_resume_proposals(items: list[dict], hash: str) -> int:
    SAVED_RESUME.append((items, hash))
    return len(items)


@activity.defn(name="apply_resume")
async def fake_apply_resume(ids: list[str]) -> str:
    APPLIED_IDS.append(ids)
    return f"반영 {len(ids)}건"


@activity.defn(name="reindex_facts")
async def fake_reindex_facts() -> str:
    return "jobscout_facts: 5건"


async def _run_resume_sync(client: Client, resume_hash_act) -> dict:
    q = f"test-{uuid.uuid4()}"
    acts = [fake_sync_repo, fake_pkb_snapshot, resume_hash_act,
           fake_propose_resume_update, fake_save_resume_proposals]
    async with Worker(client, task_queue=q, workflows=[ResumeSync], activities=acts,
                      workflow_runner=UnsandboxedWorkflowRunner()):
        import jobscouter.workflow as wf
        wf._IO_OPTS["task_queue"] = q
        wf._LLM_OPTS["task_queue"] = q
        handle = await client.start_workflow(
            ResumeSync.run, id=f"wf-{uuid.uuid4()}", task_queue=q)
        return await handle.result()


@pytest.mark.asyncio
async def test_resume_sync_no_change_skips_propose():
    """해시가 같으면 propose_resume_update를 아예 호출하지 않는다 — LLM 0."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        PROPOSE_CALLS.clear()
        out = await _run_resume_sync(env.client, fake_resume_state_hash_same)
        assert out == {"changed": False, "docs": 3}
        assert PROPOSE_CALLS == []
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_resume_sync_change_calls_propose_and_saves():
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        PROPOSE_CALLS.clear()
        SAVED_RESUME.clear()
        out = await _run_resume_sync(env.client, fake_resume_state_hash_diff)
        assert out == {"changed": True, "docs": 3, "proposals": 1}
        assert PROPOSE_CALLS == ["PKB 발췌"]
        assert SAVED_RESUME[0][1] == "H1"   # pkb_snapshot 해시로 저장
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_apply_resume_workflow_applies_then_reindexes():
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        APPLIED_IDS.clear()
        q = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=q, workflows=[ApplyResume],
                          activities=[fake_sync_repo, fake_apply_resume, fake_reindex_facts],
                          workflow_runner=UnsandboxedWorkflowRunner()):
            import jobscouter.workflow as wf
            wf._IO_OPTS["task_queue"] = q
            handle = await env.client.start_workflow(
                ApplyResume.run, ["id1", "id2"], id=f"wf-{uuid.uuid4()}", task_queue=q)
            out = await handle.result()
            assert APPLIED_IDS == [["id1", "id2"]]
            assert out == {"applied": "반영 2건", "reindexed": "jobscout_facts: 5건"}
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_running_handle_finds_cycle():
    # time-skipping 테스트 서버는 ListWorkflowExecutions(visibility)를
    # 구현하지 않는다(실측: RPCError unimplemented) — 이 테스트만 로컬 dev 서버.
    env = await WorkflowEnvironment.start_local()
    try:
        q = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=q, workflows=[DailyScan],
                          activities=[fake_sync_repo, fake_run_script, fake_load_targets_slow,
                                      fake_fetch_requirements, fake_search_context,
                                      fake_judge, fake_save_proposals],
                          workflow_runner=UnsandboxedWorkflowRunner()):
            import jobscouter.workflow as wf
            wf._IO_OPTS["task_queue"] = q
            wf._LLM_OPTS["task_queue"] = q
            started = await env.client.start_workflow(
                DailyScan.run, ScanParams(), id=f"wf-{uuid.uuid4()}", task_queue=q)
            from jobscouter.worker import _running_handle
            h = await _running_handle(env.client)
            assert h.id == started.id
            await started.result()
    finally:
        await env.shutdown()
