import json
import re
import subprocess
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import jobscouter.candidates as cands
from jobscouter import api, config


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """tmp 데이터 repo — api가 import한 이름과 candidates·config 전역을 함께 patch한다.
    settings.json은 만들지 않는다 — 통근은 전부 '미확인'."""
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    (jobfeed / "proposals.json").write_text(json.dumps({
        "111": {"id": "111", "company": "테스트회사", "title": "백엔드 엔지니어",
                "url": "https://example.com/111", "src": "wanted",
                "scores": [30, 18, 20, 16, -5], "total": 79,
                "reason": "필수 스택 일치", "quotes": ["Python 3년 이상"],
                "confidence": 0.9, "rubric_version": "v1", "judged_at": "2026-08-24"},
        "333": {"id": "333", "company": "테스트회사", "title": "플랫폼 엔지니어",
                "url": "https://example.com/333", "src": "wanted",
                "scores": [20, 15, 15, 12, 0], "total": 62,
                "reason": "부분 일치", "quotes": [], "confidence": 0.5,
                "rubric_version": "v1", "judged_at": "2026-08-24"},
    }, ensure_ascii=False))
    # 마감은 proposals.json이 아니라 jobs.jsonl에 있다
    soon = (datetime.now(cands.KST).date() + timedelta(days=10)).isoformat()
    (jobfeed / "jobs.jsonl").write_text(
        json.dumps({"src": "wanted", "id": 111, "due": "2020-01-01"}) + "\n"
        + json.dumps({"src": "wanted", "id": 333, "due": soon}) + "\n")
    (jobfeed / "candidates.json").write_text(json.dumps({
        "rows": [["백엔드 엔지니어", "테스트회사", 222, [30, 18, 20, 16, -5], None,
                  "자동판정", [], None]],
        "skipped": {},
    }, ensure_ascii=False))
    (jobfeed / "resume_proposals.json").write_text(json.dumps({
        "hash": "h1",
        "items": [
            {"id": "abc12345", "target": "factbase", "section": "경력", "kind": "change",
             "current": "3년차 백엔드", "proposed": "4년차 백엔드", "evidence": "PKB: 경력노트"},
        ],
    }, ensure_ascii=False))
    (jobfeed / "reports").mkdir()
    (jobfeed / "reports" / "x.md").write_text("# 보고서\n\n내용입니다")
    # 「테스트회사」는 여기 없어야 「평판 미조사 회사」에 뜬다
    (jobfeed / "기업평판.md").write_text("| 회사 | 총점 |\n|---|---|\n| 다른회사 | 4.0 |\n")

    (tmp_path / "이력서.md").write_text("# 이력서\n\n이력 요약")
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "이력서_사실베이스.md").write_text("# 사실베이스\n\n경력 사실")

    apps = tmp_path / "applications"
    (apps / "test_co").mkdir(parents=True)
    # 연결 키는 회사명이 아니라 문서에 적힌 공고 URL — 폴더명(test_co)은 회사명(테스트회사)과 다르다
    (apps / "test_co" / "0_JD.md").write_text(
        "# JD\n\n> 원본: https://www.wanted.co.kr/wd/222\n\n본문")
    (apps / "test_co" / "1_맞춤_이력서.md").write_text("# 이력서\n\n내용")
    (apps / "no_link").mkdir()
    (apps / "no_link" / "README.md").write_text("# 링크 없는 폴더\n\n공고 주소가 없다")

    for mod in (api, cands, config):
        monkeypatch.setattr(mod, "JOBFEED", jobfeed, raising=False)
        monkeypatch.setattr(mod, "APPLICATIONS", apps, raising=False)
    # resume_target()은 config 전역을 본다
    monkeypatch.setattr(config, "RESUME", tmp_path / "이력서.md")
    monkeypatch.setattr(api, "RESUME", tmp_path / "이력서.md")
    monkeypatch.setattr(api, "REFERENCES", refs)
    return tmp_path


@pytest.fixture
def client(repo):
    return TestClient(api.app, headers={"host": "localhost"})


def test_dashboard_json(client):
    d = client.get("/api/dashboard").json()
    ids = [p["id"] for p in d["proposals"]]
    assert ids == ["111", "333"]                      # total 내림차순
    p = d["proposals"][0]
    assert p["cells"][0] == [30, "hi"] and p["cells"][4] == [-5, "pen"] and p["tier"] == "t2"
    assert p["due_cls"] == "gone" and p["rail"] == "none" and p["busy"] is False
    assert d["unresearched"] == ["테스트회사"] and d["stats"]["pending"] == 2


def test_dashboard_marks_busy_rows_when_publish_running(client, monkeypatch):
    async def running():
        return {"id": "publish-x", "status": "RUNNING", "start": "", "ids": ["111"],
                "reject_ids": [], "error": ""}
    monkeypatch.setattr(api, "latest_publish", running)
    d = client.get("/api/dashboard").json()
    assert [p["busy"] for p in d["proposals"]] == [True, False]
    r = client.post("/api/publish", json={"ids": ["333"], "rejects": []})
    assert r.status_code == 409


def test_publish_starts_workflow(client, monkeypatch):
    got = {}

    async def start(ids, rejects):
        got.update(ids=ids, rejects=rejects)
        return "publish-1"
    monkeypatch.setattr(api, "start_publish", start)
    r = client.post("/api/publish", json={"ids": ["111"],
                                          "rejects": [{"id": "333", "why": "  너무 멀다 "},
                                                      {"id": "444", "why": "  "}]})
    assert r.json() == {"workflow_id": "publish-1"}
    assert got == {"ids": ["111"], "rejects": [{"id": "333", "why": "너무 멀다"}]}


def test_candidates_json(client):
    d = client.get("/api/candidates").json()
    assert [r["id"] for r in d["rows"]] == ["222"]
    assert d["apps"] == {"222": {"slug": "test_co", "n": 2}}
    assert d["errors"] == [] and d["rows"][0]["zone_label"] == "미확인"


def test_reports_and_docs(client):
    assert client.get("/api/reports").json() == [{"date": "x", "kind": "-", "name": "x"}]
    assert client.get("/api/reports/x").json()["markdown"].startswith("# 보고서")
    # httpx가 리터럴 ".."는 요청 전에 정규화해버리므로 %2e%2e로 서버까지 전달한다
    assert client.get("/api/reports/%2e%2e/x").status_code in (400, 404)
    assert client.get("/api/docs").json() == [
        {"path": "이력서_사실베이스.md", "name": "이력서_사실베이스.md", "group": "references"}]
    assert "경력 사실" in client.get("/api/docs/이력서_사실베이스.md").json()["markdown"]
    assert client.get("/api/docs/%2e%2e/이력서.md").status_code == 400


def test_resume_document_and_proposals(client):
    d = client.get("/api/resume").json()
    assert d["markdown"].startswith("# 이력서") and d["pending"] == 1 and d["chats"] == []
    assert client.get("/api/resume/proposals").json()["items"][0]["proposed"] == "4년차 백엔드"


def test_resume_apply_starts_workflow(client, monkeypatch):
    got = []

    async def start(ids):
        got.append(ids)
        return "apply-1"
    monkeypatch.setattr(api, "start_apply_resume", start)
    assert client.post("/api/resume/apply", json={"ids": ["abc12345"]}).json() == {
        "workflow_id": "apply-1"}
    assert got == [["abc12345"]]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], check=True, capture_output=True, text=True)


def test_resume_history_and_revert(client, monkeypatch, repo):
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "첫 커밋")
    h = client.get("/api/resume/history", params={"key": "이력서.md"}).json()
    assert h["commits"][0]["subject"] == "첫 커밋"
    sha = h["commits"][0]["sha"]
    assert "+# 이력서" in client.get(f"/api/resume/history/{sha}",
                                     params={"key": "이력서.md"}).json()["diff"]
    assert client.get("/api/resume/history", params={"key": "../x"}).status_code == 400
    started = {}

    async def start(key, sha_):
        started.update(key=key, sha=sha_)
        return "revert-1"
    monkeypatch.setattr(api, "start_revert", start)
    assert client.post("/api/resume/revert", json={"key": "이력서.md", "sha": sha}).json() == {
        "workflow_id": "revert-1"}
    assert client.post("/api/resume/revert", json={"key": "이력서.md", "sha": "zz"}).status_code == 400


def test_history_follows_rename(client, repo, monkeypatch):
    """이름을 바꾼 파일도 옛 이력이 이어지고 그 시절 diff가 나온다 (JK.md → 이력서.md)."""
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "이력서.md").unlink()
    (repo / "JK.md").write_text("# 이력서\n\n옛 이름 시절 본문\n")
    _git(repo, "add", "JK.md")
    _git(repo, "commit", "-qm", "옛 이름 시절 커밋")
    old = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    _git(repo, "mv", "JK.md", "이력서.md")
    _git(repo, "commit", "-qm", "이름 변경")

    h = client.get("/api/resume/history", params={"key": "이력서.md"}).json()
    assert [c["subject"] for c in h["commits"]] == ["이름 변경", "옛 이름 시절 커밋"]
    d = client.get(f"/api/resume/history/{old}", params={"key": "이력서.md"}).json()
    assert "옛 이름 시절 본문" in d["diff"]   # diff는 그 커밋 시점 이름으로 찾아야 나온다


def test_chat_session_and_async_turn(client, monkeypatch, repo):
    sid = client.post("/api/resume/chat", json={"key": "이력서.md"}).json()["sid"]
    assert re.fullmatch(r"[0-9a-f]{12}", sid)
    s = client.get(f"/api/resume/chat/{sid}").json()
    assert s == {"sid": sid, "target": "이력서.md", "exists": False, "turns": [],
                 "diff": "", "pending": False}
    started = {}

    async def start(sid_, key, msg):
        started.update(sid=sid_, key=key, msg=msg)
        return f"chat-{sid_}-0"
    monkeypatch.setattr(api, "start_resume_chat", start)
    r = client.post(f"/api/resume/chat/{sid}/turns",
                    json={"key": "이력서.md", "message": " 한 줄 줄여 "})
    assert r.json() == {"workflow_id": f"chat-{sid}-0"} and started["msg"] == "한 줄 줄여"
    assert client.post(f"/api/resume/chat/{sid}/turns",
                       json={"key": "이력서.md", "message": "  "}).status_code == 400
    # 버퍼가 있으면 turns·diff가 나온다
    chat = repo / "tmp" / "chat"
    chat.mkdir(parents=True)
    (chat / f"{sid}.json").write_text(json.dumps(
        {"sid": sid, "target": "이력서.md", "base_doc": "a\nb", "doc": "a\nc",
         "turns": [{"role": "user", "text": "b를 c로"},
                   {"role": "assistant", "text": "했다", "applied": 1, "skipped": []}]}))
    monkeypatch.setattr(api, "CHAT_DIR", chat)
    s = client.get(f"/api/resume/chat/{sid}").json()
    assert s["exists"] and len(s["turns"]) == 2 and "-b\n+c" in s["diff"]


def test_chat_rejects_bad_sid_and_key(client):
    assert client.get("/api/resume/chat/..%2f..%2fetc").status_code == 400
    assert client.get("/api/resume/chat/abcdef123456",
                      params={"key": "../etc/passwd"}).status_code == 400
    assert client.post("/api/resume/chat", json={"key": "../etc/passwd"}).status_code == 400


def test_chat_end_conflict_is_409_with_root_cause(client, monkeypatch):
    class Inner(Exception):
        pass

    async def end(sid, save):
        try:
            raise Inner("대상 파일이 세션 시작 후 바뀌었습니다 — 저장 취소")
        except Inner as e:
            raise RuntimeError("Workflow execution failed") from e
    monkeypatch.setattr(api, "end_chat", end)
    r = client.post("/api/resume/chat/abcdef123456/end", json={"save": True})
    assert r.status_code == 409 and r.json()["conflict"] is True and "세션 시작 후" in r.json()["cause"]


def test_applications(client, monkeypatch):
    d = client.get("/api/applications").json()
    assert d["stats"] == {"candidates": 1, "folders": 2, "linked": 1, "gone": 0, "unlinked": 1}
    assert d["linked"][0]["slug"] == "test_co" and d["linked"][0]["c"]["id"] == "222"
    assert d["orphans"][0]["slug"] == "no_link" and d["orphans"][0]["cls"] == "bad"
    j = client.get("/api/applications/job/222").json()
    assert j["folder"]["slug"] == "test_co" and set(j["docs"]) == {"0_JD.md", "1_맞춤_이력서.md"}
    assert j["drafting"] is False
    assert client.get("/api/applications/job/999").status_code == 404
    assert client.get("/api/applications/test_co").json()["linked_cid"] == "222"
    assert client.get("/api/applications/no_link").json()["linked_cid"] is None
    started = []

    async def start(cid):
        started.append(cid)
        return f"draft-{cid}"
    monkeypatch.setattr(api, "start_draft", start)
    assert client.post("/api/applications/draft", json={"id": "222"}).json() == {
        "workflow_id": "draft-222"}
    assert client.post("/api/applications/draft", json={"id": "999"}).status_code == 400
    assert started == ["222"]


def test_lan_guard(repo):
    c = TestClient(api.app, headers={"host": "evil.example.com"})
    assert c.get("/api/reports").status_code == 403
    c = TestClient(api.app, headers={"host": "10.1.2.3:8091"})
    assert c.get("/api/reports").status_code == 200
    c = TestClient(api.app, headers={"host": "localhost", "sec-fetch-site": "cross-site"})
    assert c.post("/api/publish", json={"ids": [], "rejects": []}).status_code == 403


def test_security_headers_are_nosniff_only(client):
    """CSP·X-Frame-Options는 web(Next.js)이 붙인다 — api는 JSON만 내므로 nosniff만."""
    h = client.get("/api/reports").headers
    assert h["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in h and "x-frame-options" not in h


def test_safe_url_blocks_non_http(client):
    assert api._safe_url("javascript:alert(1)") == "#"
    assert api._safe_url("https://www.wanted.co.kr/wd/1") == "https://www.wanted.co.kr/wd/1"
    assert api._safe_url(None) == "#"
    # 판정 결과의 url은 외부 API에서 온 값 — 응답에 넣기 전에 걸러진다
    assert client.get("/api/dashboard").json()["proposals"][0]["url"] == "https://example.com/111"


def test_events_emits_only_changes(client, monkeypatch):
    ticks = [[{"id": "a", "type": "Publish", "status": "RUNNING", "stage": "등재", "error": "", "start": ""}],
             [{"id": "a", "type": "Publish", "status": "RUNNING", "stage": "등재", "error": "", "start": ""}],
             [{"id": "a", "type": "Publish", "status": "COMPLETED", "stage": None, "error": "", "start": ""}]]

    async def snapshot():
        return ticks.pop(0)
    monkeypatch.setattr(api, "workflow_snapshot", snapshot)

    async def no_sleep(_):
        pass
    monkeypatch.setattr(api.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(api, "EVENT_TICKS", 3)             # 테스트용 상한 — 기본 None(무한)
    body = client.get("/api/events").text
    assert body.count("event: workflow") == 2 and '"status": "COMPLETED"' in body
