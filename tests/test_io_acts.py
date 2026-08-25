import json
import subprocess

import pytest

import jobscouter.io_acts as io_acts
from jobscouter.config import Target


def _touch_jobfeed(tmp_path, monkeypatch):
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path)
    (tmp_path / "candidates.json").write_text(json.dumps({
        "rows": [["포지션", "나쁜회사", 111, [30, 10, 16, 20],
                  ["bad", 1.0, 10, "1,1", "요약"], None, [], None],
                 ["포지션", "등재회사", 222, [30, 10, 16, 20], None, "사유", [], None]],
        "skipped": {"333": ["스킵회사", "포지션", "사유"]},
    }, ensure_ascii=False))
    jobs = [
        {"src": "wanted", "id": 111, "title": "A", "company": "나쁜회사", "url": "u"},
        {"src": "wanted", "id": 222, "title": "B", "company": "등재회사", "url": "u"},
        {"src": "wanted", "id": 333, "title": "C", "company": "스킵회사", "url": "u"},
        {"src": "wanted", "id": 444, "title": "D", "company": "(주)나쁜회사", "url": "u"},
        {"src": "jumpit", "id": 555, "title": "E", "company": "새회사", "url": "u"},
    ]
    (tmp_path / "jobs.jsonl").write_text(
        "\n".join(json.dumps(j, ensure_ascii=False) for j in jobs))


def test_load_targets(tmp_path, monkeypatch):
    _touch_jobfeed(tmp_path, monkeypatch)
    got = io_acts.load_targets()
    ids = [t.id for t in got]
    # 111 등재됨·222 등재됨·333 스킵·444 🚫회사 정규화 매칭 → 미점수는 j555뿐
    assert ids == ["j555"]


def test_fetch_requirements_jumpit_plural_and_cap(monkeypatch):
    monkeypatch.setattr(io_acts, "_get", lambda url: {
        "result": {"qualifications": "필수: " + "가" * 400,
                   "qualification": None,  # 단수 키 함정 — 이걸 읽으면 None
                   "responsibility": "줄1\n줄2\n줄3"}})
    t = Target(id="j555", company="새회사", title="E", src="jumpit", url="u")
    text = io_acts.fetch_requirements(t)
    assert text.startswith("필수: 가")
    assert len(text) <= io_acts.REQ_CAP
    assert "줄3" not in text  # responsibility는 첫 2줄만 (캡 안에 들어올 때)


def test_to_row_format():
    j = {"id": "j555", "company": "새회사", "title": "백엔드",
         "scores": [30, 18, 20, 16, -5], "total": 79, "exclude": False,
         "reason": "필수에 Python", "confidence": 0.9, "rubric_version": "v1"}
    r = io_acts.to_row(j)
    assert len(r) == 8 and r[2] == "j555" and r[4] is None and r[5]
    j["id"] = "365172"
    assert io_acts.to_row(j)[2] == 365172   # 원티드는 int — 기존 관례


def test_commit_rows_rejects_mixed_rubric():
    js = [{"id": "1", "rubric_version": "v1"}, {"id": "2", "rubric_version": "v2"}]
    with pytest.raises(RuntimeError, match="혼재"):
        io_acts.commit_rows(js, dry_run=True)


def test_sync_repo_no_remote(tmp_path, monkeypatch):
    """실제 tmp git repo — 원격 없음(맥북 단독 개발 호환) → 예외 없이 생략 메시지."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path / "jobfeed")
    assert io_acts.sync_repo() == "원격 없음 — 동기화 생략"


def _init_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)


def test_save_proposals_merges_and_cleans(tmp_path, monkeypatch):
    """이미 등재된 id는 병합 후 제거되고, 신규는 남아 commit_rows 입력 형식으로 저장된다."""
    _init_repo(tmp_path)
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    monkeypatch.setattr(io_acts, "JOBFEED", jobfeed)
    (jobfeed / "candidates.json").write_text(json.dumps({
        "rows": [["포지션", "등재회사", 222, [30, 10, 16, 20, 0], None, "사유", [], None]],
        "skipped": {"333": ["스킵회사", "포지션", "사유"]},
    }, ensure_ascii=False))
    judged = [
        {"id": "222", "company": "등재회사", "title": "포지션", "url": "u1", "src": "wanted",
         "scores": [30, 10, 16, 20, 0], "total": 76, "reason": "r", "quotes": [],
         "confidence": 0.9, "rubric_version": "v1"},
        {"id": "555", "company": "새회사", "title": "백엔드", "url": "u2", "src": "jumpit",
         "scores": [30, 18, 20, 16, -5], "total": 79, "reason": "r2", "quotes": [],
         "confidence": 0.8, "rubric_version": "v1"},
    ]
    n = io_acts.save_proposals(judged)
    assert n == 1
    saved = json.loads((jobfeed / "proposals.json").read_text())
    assert "222" not in saved   # candidates rows에 이미 있음 → 제거
    assert saved["555"]["company"] == "새회사"
    assert saved["555"]["url"] == "u2"
    assert saved["555"]["judged_at"]


def test_reject_proposals_records_skipped(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    monkeypatch.setattr(io_acts, "JOBFEED", jobfeed)
    (jobfeed / "candidates.json").write_text(json.dumps(
        {"rows": [], "skipped": {}}, ensure_ascii=False))
    (jobfeed / "proposals.json").write_text(json.dumps({
        "777": {"id": "777", "company": "제외회사", "title": "포지션", "url": "u",
                "src": "wanted", "scores": [10, 5, 5, 5, 0], "total": 25,
                "reason": "r", "quotes": [], "confidence": 0.5, "rubric_version": "v1",
                "judged_at": "2026-08-24"},
    }, ensure_ascii=False))

    n = io_acts.reject_proposals([{"id": "777", "why": "연봉 미공개"}])
    assert n == 1

    cand = json.loads((jobfeed / "candidates.json").read_text())
    assert cand["skipped"]["777"] == ["제외회사", "포지션", "연봉 미공개"]
    props = json.loads((jobfeed / "proposals.json").read_text())
    assert "777" not in props


def test_sync_repo_commits_dirty_output_before_pull(tmp_path, monkeypatch):
    """fetch 산출물(jobs.jsonl 등)이 커밋 안 된 채 남아 있으면 stash 대신 그대로
    커밋한 뒤 pull한다 — 다음 사이클 pull이 dirty 충돌로 안 죽게."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "HEAD"],
                   check=True, capture_output=True)

    (repo / "jobfeed").mkdir()
    (repo / "jobfeed" / "jobs.jsonl").write_text('{"id":1}')   # 커밋 안 된 fetch 산출물

    monkeypatch.setattr(io_acts, "JOBFEED", repo / "jobfeed")
    io_acts.sync_repo()

    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert status == ""
    subject = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout.strip()
    assert subject == "job-scouter: 미커밋 산출물 정리"


def test_sync_repo_pulls_when_remote_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path / "jobfeed")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[3] == "remote":
            return subprocess.CompletedProcess(cmd, 0, stdout="origin\n", stderr="")
        if cmd[3] == "status":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")   # 깨끗함
        if cmd[3] == "pull":
            return subprocess.CompletedProcess(cmd, 0, stdout="Already up to date.\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(io_acts.subprocess, "run", fake_run)
    assert io_acts.sync_repo() == "Already up to date."
    assert ["git", "-C", str(tmp_path), "pull", "--ff-only"] in calls
