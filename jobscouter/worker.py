"""실행 진입점.

    uv run python -m jobscouter.worker io                  # workflow+io 워커 (자격증명 없음)
    uv run python -m jobscouter.worker llm                  # judge·report (claude -p, 구독 인증)
    uv run python -m jobscouter.worker scan [--budget N]     # DailyScan 시작
    uv run python -m jobscouter.worker publish id1 id2 ...   # Publish 시작 (등재 승인)
    uv run python -m jobscouter.worker reject <id> "<사유>"  # Publish 시작 (거부만)
    uv run python -m jobscouter.worker resume-sync            # ResumeSync 시작
    uv run python -m jobscouter.worker apply-resume id1 ...   # ApplyResume 시작 (제안 반영)
    uv run python -m jobscouter.worker draft <공고id>          # 등재 공고 지원서류 초안 재생성
    uv run python -m jobscouter.worker status                # 실행 중 사이클 조회
    uv run python -m jobscouter.worker schedule               # 자동 시작 등록(일 1회 스캔·주 1회 이력서)
"""
import asyncio
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()  # .env(서버 주소·데이터 경로·키) — config import 전에

from temporalio.client import Client
from temporalio.worker import Worker

from jobscouter.config import TEMPORAL, Q_IO, Q_WF, PublishParams, ScanParams


async def _running_handle(client: Client):
    """실행 중인 사이클 핸들. 스케줄 시작 워크플로는 id가 매번 달라 검색으로 찾는다."""
    async for wf in client.list_workflows(
            "(WorkflowType='DailyScan' OR WorkflowType='Publish' "
            "OR WorkflowType='ResumeSync' OR WorkflowType='ApplyResume' OR WorkflowType='Draft') "
            "AND ExecutionStatus='Running'"):
        return client.get_workflow_handle(wf.id)
    sys.exit("실행 중인 사이클이 없다")


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    client = await Client.connect(TEMPORAL)

    if cmd == "io":
        from jobscouter import io_acts, search
        from jobscouter.workflow import (ApplyResume, DailyScan, Draft, Publish,
                                         ResumeSync, RevertFile)
        acts = [io_acts.run_script, io_acts.load_targets,
                io_acts.fetch_requirements, io_acts.commit_rows,
                io_acts.sync_repo, io_acts.save_proposals,
                io_acts.load_proposals, io_acts.reject_proposals, io_acts.listed_target,
                io_acts.commit_outputs, io_acts.fetch_posting_full,
                io_acts.write_application, search.search_context,
                io_acts.pkb_snapshot, io_acts.resume_state_hash,
                io_acts.save_resume_proposals, io_acts.apply_resume,
                io_acts.reindex_facts, io_acts.git_revert]
        ex = ThreadPoolExecutor(4)
        workers = [
            Worker(client, task_queue=Q_WF,
                   workflows=[DailyScan, Publish, ResumeSync, ApplyResume, Draft, RevertFile]),
            Worker(client, task_queue=Q_IO, activities=acts, activity_executor=ex),
        ]
        print(f"io 워커 시작 — {TEMPORAL} / {Q_WF}, {Q_IO}")
        await asyncio.gather(*(w.run() for w in workers))

    elif cmd == "scan":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--budget", type=int, default=2_000_000)
        a = p.parse_args(sys.argv[2:])
        from jobscouter.workflow import DailyScan
        handle = await client.start_workflow(
            DailyScan.run, ScanParams(budget_tokens=a.budget),
            id="daily-scan-manual", task_queue=Q_WF)
        print(f"시작: {handle.id} → http://{TEMPORAL.split(':')[0]}:8233")

    elif cmd == "publish":
        ids = sys.argv[2:]
        if not ids:
            sys.exit("사용: worker publish id1 id2 ...")
        from jobscouter.workflow import Publish
        handle = await client.start_workflow(
            Publish.run, PublishParams(ids=ids),
            id=f"publish-{uuid.uuid4()}", task_queue=Q_WF)
        print(f"시작: {handle.id}")

    elif cmd == "reject":
        if len(sys.argv) < 4:
            sys.exit('사용: worker reject <id> "<사유>"')
        rid, why = sys.argv[2], sys.argv[3]
        from jobscouter.workflow import Publish
        handle = await client.start_workflow(
            Publish.run, PublishParams(rejects=[{"id": rid, "why": why}]),
            id=f"publish-{uuid.uuid4()}", task_queue=Q_WF)
        print(f"시작: {handle.id}")

    elif cmd == "resume-sync":
        from jobscouter.workflow import ResumeSync
        handle = await client.start_workflow(
            ResumeSync.run, id="resume-sync-manual", task_queue=Q_WF)
        print(f"시작: {handle.id}")

    elif cmd == "apply-resume":
        ids = sys.argv[2:]
        if not ids:
            sys.exit("사용: worker apply-resume id1 id2 ...")
        from jobscouter.workflow import ApplyResume
        handle = await client.start_workflow(
            ApplyResume.run, ids, id=f"apply-resume-{uuid.uuid4()}", task_queue=Q_WF)
        print(f"시작: {handle.id}")

    elif cmd == "draft":
        if len(sys.argv) < 3:
            sys.exit("사용: worker draft <공고id>  (candidates.json에 등재된 공고만)")
        from jobscouter.workflow import Draft
        handle = await client.start_workflow(
            Draft.run, sys.argv[2], id=f"draft-{sys.argv[2]}", task_queue=Q_WF)
        print(f"시작: {handle.id}")

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
            activities=[judge_mod.judge, judge_mod.report, judge_mod.draft_application,
                       judge_mod.propose_resume_update],
            activity_executor=ThreadPoolExecutor(2),
            max_task_queue_activities_per_second=0.5)  # 레이트리밋은 큐 레벨
        print(f"llm 워커 시작 — {TEMPORAL} / {Q_LLM}")
        await worker.run()

    elif cmd == "schedule":
        from temporalio.service import RPCError
        from temporalio.client import (Schedule, ScheduleActionStartWorkflow,
                                       ScheduleOverlapPolicy, SchedulePolicy,
                                       ScheduleSpec)
        from jobscouter.workflow import DailyScan, ResumeSync
        await client.create_schedule(
            "daily-scan",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    DailyScan.run, ScanParams(),
                    id="daily-scan", task_queue=Q_WF),
                spec=ScheduleSpec(cron_expressions=["7 9 * * *"],
                                  time_zone_name="Asia/Seoul"),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ))
        await client.create_schedule(
            "resume-sync",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ResumeSync.run,
                    id="resume-sync", task_queue=Q_WF),
                spec=ScheduleSpec(cron_expressions=["0 8 * * 1"],
                                  time_zone_name="Asia/Seoul"),   # 매주 월 08:00 KST
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ))
        try:
            await client.get_schedule_handle("job-scout-weekly").delete()
            deleted = "삭제됨"
        except RPCError:
            deleted = "없었음"
        print("스케줄 등록: 매일 09:07 KST daily-scan · 매주 월 08:00 KST resume-sync"
              f" — job-scout-weekly {deleted}")

    else:
        sys.exit(f"모르는 명령: {cmd}")


if __name__ == "__main__":
    asyncio.run(main())
