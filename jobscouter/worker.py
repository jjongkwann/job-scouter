"""실행 진입점.

    uv run python -m jobscouter.worker io            # workflow+io 워커 (자격증명 없음)
    uv run python -m jobscouter.worker llm           # judge·report (claude -p, 구독 인증)
    uv run python -m jobscouter.worker run           # 사이클 시작
    uv run python -m jobscouter.worker browser-done "메모"
    uv run python -m jobscouter.worker status
"""
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()  # .env(서버 주소·데이터 경로·키) — config import 전에

from temporalio.client import Client
from temporalio.worker import Worker

from jobscouter.config import TEMPORAL, WORKFLOW_ID, Q_IO, Q_WF, CycleParams


async def _running_handle(client: Client):
    """실행 중인 사이클 핸들. 스케줄 시작 워크플로는 id가 매번 달라 검색으로 찾는다."""
    async for wf in client.list_workflows(
            "WorkflowType='JobScoutCycle' AND ExecutionStatus='Running'"):
        return client.get_workflow_handle(wf.id)
    sys.exit("실행 중인 사이클이 없다")


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    client = await Client.connect(TEMPORAL)

    if cmd == "io":
        from jobscouter import io_acts, search
        from jobscouter.workflow import JobScoutCycle
        acts = [io_acts.run_script, io_acts.load_targets,
                io_acts.fetch_requirements, io_acts.commit_rows,
                search.search_context]
        ex = ThreadPoolExecutor(4)
        workers = [
            Worker(client, task_queue=Q_WF, workflows=[JobScoutCycle]),
            Worker(client, task_queue=Q_IO, activities=acts, activity_executor=ex),
        ]
        print(f"io 워커 시작 — {TEMPORAL} / {Q_WF}, {Q_IO}")
        await asyncio.gather(*(w.run() for w in workers))

    elif cmd == "run":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--budget", type=int, default=2_000_000)
        p.add_argument("--browser-wait", type=int, default=120)
        p.add_argument("--dry-run", action="store_true")
        a = p.parse_args(sys.argv[2:])
        from jobscouter.workflow import JobScoutCycle
        handle = await client.start_workflow(
            JobScoutCycle.run,
            CycleParams(budget_tokens=a.budget, browser_wait_minutes=a.browser_wait,
                       dry_run=a.dry_run),
            id=WORKFLOW_ID, task_queue=Q_WF)
        print(f"시작: {handle.id} → http://{TEMPORAL.split(':')[0]}:8233")

    elif cmd == "browser-done":
        note = sys.argv[2] if len(sys.argv) > 2 else "완료"
        h = await _running_handle(client)
        await h.signal("browser_done", note)
        print("signal 전송:", note)

    elif cmd == "approve":
        ids = [] if sys.argv[2:] == ["--none"] else sys.argv[2:]
        h = await _running_handle(client)
        await h.signal("approve", ids)
        print(f"승인 signal: {ids or '등재 없음'}")

    elif cmd == "status":
        h = await _running_handle(client)
        print(await h.query("status"))

    elif cmd == "llm":
        import shutil
        from jobscouter import judge as judge_mod
        if not shutil.which(judge_mod.CLAUDE):
            sys.exit(f"'{judge_mod.CLAUDE}' 없음 — Claude Code 설치·로그인(또는 CLAUDE_CODE_OAUTH_TOKEN) 필요")
        from jobscouter.config import Q_LLM
        worker = Worker(
            client, task_queue=Q_LLM,
            activities=[judge_mod.judge, judge_mod.report],
            activity_executor=ThreadPoolExecutor(2),
            max_task_queue_activities_per_second=0.5)  # 레이트리밋은 큐 레벨
        print(f"llm 워커 시작 — {TEMPORAL} / {Q_LLM}")
        await worker.run()

    elif cmd == "schedule":
        from temporalio.client import (Schedule, ScheduleActionStartWorkflow,
                                       ScheduleOverlapPolicy, SchedulePolicy,
                                       ScheduleSpec)
        from jobscouter.workflow import JobScoutCycle
        await client.create_schedule(
            "job-scout-weekly",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    JobScoutCycle.run, CycleParams(),
                    id=WORKFLOW_ID, task_queue=Q_WF),
                spec=ScheduleSpec(cron_expressions=["7 9 * * 1"],
                                  time_zone_name="Asia/Seoul"),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ))
        print("스케줄 등록: 매주 월 09:07 KST — 진행 중 사이클 있으면 skip")

    else:
        sys.exit(f"모르는 명령: {cmd}")


if __name__ == "__main__":
    asyncio.run(main())
