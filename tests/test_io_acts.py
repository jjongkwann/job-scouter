import hashlib
import json
import subprocess
from pathlib import Path

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


def test_fetch_posting_full_wanted_and_jumpit(monkeypatch):
    """소스별 필드 매핑."""
    monkeypatch.setattr(io_acts, "_get", lambda url: {
        "job": {"position": "백엔드", "company": {"name": "새회사"},
                "detail": {"intro": "소개", "main_tasks": "업무",
                           "requirements": "자격", "preferred_points": "우대",
                           "benefits": "복지"}}})
    t = Target(id="1", company="새회사", title="백엔드", src="wanted", url="u")
    text = io_acts.fetch_posting_full(t)
    assert "포지션: 백엔드" in text and "자격요건: 자격" in text

    monkeypatch.setattr(io_acts, "_get", lambda url: {
        "result": {"title": "E", "companyName": "새회사",
                   "responsibility": "업무", "qualifications": "자격",
                   "preferredRequirements": "우대"}})
    t2 = Target(id="j555", company="새회사", title="E", src="jumpit", url="u")
    text2 = io_acts.fetch_posting_full(t2)
    assert "회사: 새회사" in text2 and "우대사항: 우대" in text2


def test_fetch_posting_full_caps_at_6000(monkeypatch):
    monkeypatch.setattr(io_acts, "_get", lambda url: {
        "job": {"position": "백엔드", "company": {"name": "새회사"},
                "detail": {"main_tasks": "업" * 8000}}})
    t = Target(id="1", company="새회사", title="백엔드", src="wanted", url="u")
    assert len(io_acts.fetch_posting_full(t)) == io_acts.POSTING_CAP


def _init_git_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)


def test_write_application_creates_5_files_and_readme_then_drafts_on_conflict(tmp_path, monkeypatch):
    _init_git_repo(tmp_path)
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    monkeypatch.setattr(io_acts, "JOBFEED", jobfeed)
    monkeypatch.setattr(io_acts, "APPLICATIONS", tmp_path / "applications")
    files = {n: f"내용 {n}" for n in
             ["0_JD.md", "1_맞춤_이력서.md", "2_자기소개서.md",
              "3_면접지식맵.md", "4_포트폴리오_구성.md"]}

    path = io_acts.write_application("테스트회사", files)
    folder = Path(path)
    assert folder.name == "테스트회사"   # 한글 그대로
    for name, content in files.items():
        assert (folder / name).read_text() == content
    assert "지원 전 체크리스트" in (folder / "README.md").read_text()

    path2 = io_acts.write_application("테스트회사", files)   # 폴더 이미 있음 → _draft 접미
    assert Path(path2).name == "테스트회사_draft"


def test_commit_outputs_no_change(tmp_path, monkeypatch):
    """candidates.json·reports/ 둘 다 없으면(혹은 변경 없으면) '변경 없음'."""
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path / "jobfeed")
    (tmp_path / "jobfeed").mkdir()
    assert io_acts.commit_outputs() == "변경 없음"


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


def test_commit_and_push_skips_ignored_paths(tmp_path, monkeypatch):
    """데이터 repo가 무시하는 파일(new.md)이 섞여도 add가 실패하지 않는다."""
    import subprocess
    repo = tmp_path / "repo"; (repo / "jobfeed").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    (repo / ".gitignore").write_text("jobfeed/new.md\n")
    (repo / "jobfeed" / "new.md").write_text("x")
    (repo / "jobfeed" / "jobs.jsonl").write_text("{}")
    monkeypatch.setattr(io_acts, "JOBFEED", repo / "jobfeed")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t"); monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t"); monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    out = io_acts._commit_and_push(["jobfeed/jobs.jsonl", "jobfeed/new.md"], "t")
    assert "변경 없음" not in out
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True).stdout
    assert log.count("\n") == 2   # init + 이번 커밋


def test_write_application_rejects_traversal_names(tmp_path, monkeypatch):
    import pytest
    from jobscouter.config import APP_FILES
    monkeypatch.setattr(io_acts, "APPLICATIONS", tmp_path / "applications")
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path / "jobfeed")
    monkeypatch.setattr(io_acts, "_commit_and_push", lambda paths, msg: "ok")
    bad = {**{n: "x" for n in APP_FILES[:-1]}, "../../evil.md": "x"}
    with pytest.raises(ValueError):
        io_acts.write_application("회사", bad)          # 탈출 파일명은 걸러지고 5종 미달로 거부
    assert not (tmp_path / "evil.md").exists()
    assert io_acts._app_slug("../x/..") == "x"   # slug는 경로 문자를 제거한다


class _FakeESClient:
    """pkb_snapshot 테스트용 — search()만 흉내."""

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, **kw):
        self.calls.append(kw)
        return {"hits": {"hits": self.hits}}


def test_pkb_snapshot_deterministic_hash_and_filter(monkeypatch):
    """같은 hits면 해시가 같고, curated 프로필+카테고리 필터가 실제로 실린다."""
    hits = [{"_source": {"content": "content A"}},
            {"_source": {"content": "content B"}}]
    fake = _FakeESClient(hits)
    monkeypatch.setattr(io_acts, "es", lambda: fake)

    snap1 = io_acts.pkb_snapshot()
    snap2 = io_acts.pkb_snapshot()
    assert snap1["docs"] == 2
    assert snap1["hash"] == snap2["hash"]   # 결정적
    assert "content A" in snap1["text"] and "content B" in snap1["text"]

    kw = fake.calls[0]
    assert kw["index"] == io_acts.PKB_INDEX
    cats = [c.strip() for c in io_acts.PKB_CATEGORIES.split(",")]
    filt = kw["query"]["bool"]["filter"]
    assert {"terms": {"category": cats}} in filt
    assert not any("doc_type" in f.get("terms", {}) for f in filt)
    from jobscouter.config import PKB_STATUSES
    assert {"terms": {"status": PKB_STATUSES.split(",")}} in filt


def test_pkb_snapshot_truncates_text_but_hashes_full_content(monkeypatch):
    hits = [{"_source": {"content": "A" * 15}},
            {"_source": {"content": "B" * 15}},
            {"_source": {"content": "C" * 15}}]
    monkeypatch.setattr(io_acts, "es", lambda: _FakeESClient(hits))
    monkeypatch.setattr(io_acts, "PKB_TEXT_CAP", 20)   # 15자 1개만 들어가고 잘림

    snap = io_acts.pkb_snapshot()
    assert snap["docs"] == 3
    assert "[... 이하 잘림 ...]" in snap["text"]
    assert "C" * 15 not in snap["text"]
    assert snap["hash"] == hashlib.sha256(
        ("A" * 15 + "\n\n" + "B" * 15 + "\n\n" + "C" * 15).encode()).hexdigest()


def test_resume_state_hash_missing_then_present(tmp_path, monkeypatch):
    state = tmp_path / "resume_state.json"
    monkeypatch.setattr(io_acts, "RESUME_STATE", state)
    assert io_acts.resume_state_hash() == ""
    state.write_text(json.dumps({"hash": "abc123"}))
    assert io_acts.resume_state_hash() == "abc123"


def test_save_resume_proposals_assigns_ids_and_writes_state(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    monkeypatch.setattr(io_acts, "JOBFEED", jobfeed)
    monkeypatch.setattr(io_acts, "RESUME_STATE", tmp_path / "data" / "resume_state.json")

    items = [{"target": "factbase", "section": "경력", "kind": "change",
              "current": "3년차", "proposed": "4년차", "evidence": "PKB 발췌"}]
    n = io_acts.save_resume_proposals(items, "hash123")
    assert n == 1

    saved = json.loads((jobfeed / "resume_proposals.json").read_text())
    assert saved["hash"] == "hash123"
    expected_id = hashlib.sha1("factbase경력4년차".encode()).hexdigest()[:8]
    assert saved["items"][0]["id"] == expected_id

    state = json.loads((tmp_path / "data" / "resume_state.json").read_text())
    assert state["hash"] == "hash123"


def test_apply_resume_change_add_remove_and_reports_failures(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    monkeypatch.setattr(io_acts, "JOBFEED", jobfeed)

    factbase = tmp_path / "facts.md"
    factbase.write_text("# 사실베이스\n\n## 경력\n\n3년차 백엔드 엔지니어\n\n"
                        "## 자격증\n\n정보처리기사\n")
    jk = tmp_path / "JK.md"
    jk.write_text("# JK\n\n소개\n")
    monkeypatch.setattr(io_acts, "FACTBASE", factbase)
    monkeypatch.setattr(io_acts, "JK_MD", jk)
    monkeypatch.setattr(io_acts, "_RESUME_TARGETS", {"factbase": factbase, "JK.md": jk})

    items = [
        {"id": "id-change", "target": "factbase", "section": "경력", "kind": "change",
         "current": "3년차 백엔드 엔지니어", "proposed": "4년차 백엔드 엔지니어", "evidence": "e"},
        {"id": "id-remove", "target": "factbase", "section": "자격증", "kind": "remove",
         "current": "정보처리기사", "proposed": "", "evidence": "e"},
        {"id": "id-add", "target": "JK.md", "section": "소개", "kind": "add",
         "current": "", "proposed": "새 프로젝트 경험", "evidence": "e"},
        {"id": "id-mismatch", "target": "factbase", "section": "경력", "kind": "change",
         "current": "원문에 없는 문장", "proposed": "x", "evidence": "e"},
    ]
    (jobfeed / "resume_proposals.json").write_text(
        json.dumps({"hash": "h", "items": items}, ensure_ascii=False))

    msg = io_acts.apply_resume(
        ["id-change", "id-remove", "id-add", "id-mismatch", "id-none"])
    assert "반영 3건" in msg
    assert "id-none: 제안 없음" in msg
    assert "id-mismatch" in msg and "원문 불일치" in msg

    fb_text = factbase.read_text()
    assert "4년차 백엔드 엔지니어" in fb_text and "3년차" not in fb_text
    assert "정보처리기사" not in fb_text
    jk_text = jk.read_text()
    assert "## 미분류 추가(자동 제안 승인)" in jk_text
    assert "새 프로젝트 경험" in jk_text

    remaining = json.loads((jobfeed / "resume_proposals.json").read_text())["items"]
    assert {it["id"] for it in remaining} == {"id-mismatch"}   # 반영분만 제거됨


def test_reindex_facts_delegates_to_index_es(monkeypatch):
    import scripts.index_es as index_es_mod
    calls = []
    monkeypatch.setattr(index_es_mod, "index_facts", lambda client: calls.append(client) or 7)
    monkeypatch.setattr(io_acts, "es", lambda: "fake-client")

    assert io_acts.reindex_facts() == "jobscout_facts: 7건"
    assert calls == ["fake-client"]


def test_listed_target_from_candidates(tmp_path, monkeypatch):
    (tmp_path / "candidates.json").write_text(json.dumps({
        "rows": [["Senior Backend", "딜라이트룸", 382461, [22, 10, 20, 20, -5], None, "x", [], None],
                 ["FDE", "에스투더블유", "j54736975", [30, 18, 20, 12], None, "x", [], None]],
        "skipped": {}}))
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path)
    t = io_acts.listed_target("382461")
    assert (t["company"], t["src"], t["url"]) == ("딜라이트룸", "wanted", "https://www.wanted.co.kr/wd/382461")
    assert io_acts.listed_target("j54736975")["url"] == "https://jumpit.saramin.co.kr/position/54736975"
    with pytest.raises(ValueError):
        io_acts.listed_target("999")
