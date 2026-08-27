import json
import re
import subprocess

import pytest
from fastapi.testclient import TestClient

import jobscouter.web as web
from jobscouter import config


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """tmp 데이터 repo — web 모듈이 import한 config 이름을 직접 monkeypatch."""
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    (jobfeed / "proposals.json").write_text(json.dumps({
        "111": {"id": "111", "company": "테스트회사", "title": "백엔드 엔지니어",
                "url": "https://example.com/111", "src": "wanted",
                "scores": [30, 18, 20, 16, -5], "total": 79,
                "reason": "필수 스택 일치", "quotes": ["Python 3년 이상"],
                "confidence": 0.9, "rubric_version": "v1", "judged_at": "2026-08-24"},
    }, ensure_ascii=False))
    (jobfeed / "후보목록.html").write_text("<html><body>후보목록 본문</body></html>")
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
    (jobfeed / "기업평판.md").write_text(
        "| 회사 | 총점 |\n|---|---|\n| 다른회사 | 4.0 |\n")

    (tmp_path / "JK.md").write_text("# JK\n\n이력 요약")
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "이력서_사실베이스.md").write_text("# 사실베이스\n\n경력 사실")

    monkeypatch.setattr(web, "JOBFEED", jobfeed)
    monkeypatch.setattr(web, "JK_MD", tmp_path / "JK.md")
    monkeypatch.setattr(web, "FACTBASE", refs / "이력서_사실베이스.md")
    monkeypatch.setattr(web, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(web, "APPLICATIONS", tmp_path / "applications")
    monkeypatch.setattr(web, "REFERENCES", refs)
    return tmp_path


@pytest.fixture
def client(repo):
    return TestClient(web.app)


def test_dashboard_shows_company_score_and_unresearched(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "테스트회사" in r.text
    assert "79" in r.text
    # 「평판 미조사 회사」 절 안에도 테스트회사가 나와야 한다(기업평판.md에 없으므로)
    assert "테스트회사" in r.text.split("평판 미조사 회사")[1]


def test_candidates_serves_raw_html(client):
    r = client.get("/candidates")
    assert r.status_code == 200
    assert "후보목록 본문" in r.text
    # 원본 HTML에도 사이트 내비가 끼워져야 다른 탭으로 돌아갈 수 있다
    assert 'class="nav"' in r.text
    assert 'aria-pressed="true">후보목록' in r.text


def test_reports_render_markdown(client):
    r = client.get("/reports/x")
    assert r.status_code == 200
    assert "<h1>보고서</h1>" in r.text
    assert "내용입니다" in r.text


def test_resume_shows_jk_and_factbase(client):
    r = client.get("/resume")
    assert r.status_code == 200
    assert "JK.md" in r.text
    assert "이력 요약" in r.text
    assert "경력 사실" in r.text


def test_docs_path_traversal_blocked(client):
    # httpx가 리터럴 ".."는 요청 전에 정규화해버리므로 %2e%2e로 서버까지 전달한다
    r = client.get("/docs/%2e%2e/etc")
    assert r.status_code == 400


def test_publish_starts_workflow_with_ids_and_rejects(client, monkeypatch):
    calls = []

    async def fake_start_publish(ids, rejects):
        calls.append((ids, rejects))
        return "publish-test"

    monkeypatch.setattr(web, "start_publish", fake_start_publish)
    r = client.post("/publish", data={
        "approve": "111",
        "why_222": "연봉 미공개",
        "why_333": "",   # 빈 사유는 거부로 안 침
    }, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert calls == [(["111"], [{"id": "222", "why": "연봉 미공개"}])]


def test_resume_links_to_proposals(client):
    r = client.get("/resume")
    assert "/resume/proposals" in r.text


def test_resume_proposals_shows_items(client):
    r = client.get("/resume/proposals")
    assert r.status_code == 200
    assert "factbase" in r.text and "경력" in r.text
    assert "4년차 백엔드" in r.text


def test_resume_apply_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_apply_resume(ids):
        calls.append(ids)
        return "apply-resume-test"

    monkeypatch.setattr(web, "start_apply_resume", fake_start_apply_resume)
    r = client.post("/resume/apply", data={"apply": "abc12345"}, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/resume/proposals"
    assert calls == [["abc12345"]]


def test_running_publish_hides_its_rows_and_blocks_submit(client, monkeypatch):
    async def running():
        return {"id": "publish-x", "status": "RUNNING", "start": "2026-08-26 14:00",
                "ids": [], "reject_ids": ["111"], "error": ""}
    monkeypatch.setattr(web, "latest_publish", running)
    r = client.get("/")
    assert "Publish 실행 중" in r.text
    assert "테스트회사" not in r.text.split("평판 미조사 회사")[0]   # 처리 중인 행은 숨긴다
    assert client.post("/publish", data={"approve": ["111"]}).status_code == 409


def test_failed_publish_shows_cause(client, monkeypatch):
    async def failed():
        return {"id": "publish-x", "status": "FAILED", "start": "2026-08-26 14:00",
                "ids": [], "reject_ids": [], "error": "claude -p 실패: Not logged in"}
    monkeypatch.setattr(web, "latest_publish", failed)
    r = client.get("/")
    assert "마지막 Publish 실패" in r.text and "Not logged in" in r.text
    assert "테스트회사" in r.text   # 실패했으면 행은 그대로 보인다


def test_security_headers_and_csp(client):
    r = client.get("/")
    assert "script-src" not in r.headers["content-security-policy"]   # 기본은 스크립트 전면 차단
    assert r.headers["x-frame-options"] == "DENY"
    # build.py 산출물만 인라인 스크립트 허용
    assert "script-src 'unsafe-inline'" in client.get("/candidates").headers["content-security-policy"]


def test_dns_rebinding_host_rejected(client):
    assert client.get("/", headers={"host": "attacker.example.com"}).status_code == 403
    assert client.get("/", headers={"host": "10.1.2.3:8090"}).status_code == 200
    assert client.get("/", headers={"host": "server.local"}).status_code == 200


def test_cross_site_post_rejected(client, monkeypatch):
    calls = []

    async def fake(ids, rejects):
        calls.append(1)
        return "x"
    monkeypatch.setattr(web, "start_publish", fake)
    r = client.post("/publish", data={"approve": ["111"]}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and calls == []


def test_safe_url_blocks_non_http():
    from jobscouter.web import _safe_url
    assert _safe_url("javascript:alert(1)") == "#"
    assert _safe_url("https://www.wanted.co.kr/wd/1") == "https://www.wanted.co.kr/wd/1"
    assert _safe_url(None) == "#"


def test_applications_lists_listed_rows(client):
    r = client.get("/applications")
    assert r.status_code == 200
    assert "테스트회사" in r.text and "백엔드 엔지니어" in r.text
    assert "초안 만들기" in r.text   # applications/ 폴더가 없으니 아직 초안 없음


def test_draft_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_draft(cid):
        calls.append(cid)
        return "draft-test"

    monkeypatch.setattr(web, "start_draft", fake_start_draft)
    r = client.post("/applications/draft", data={"id": "222"}, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/applications"
    assert calls == ["222"]


def test_draft_rejects_unlisted_id(client, monkeypatch):
    calls = []
    monkeypatch.setattr(web, "start_draft", lambda cid: calls.append(cid))
    r = client.post("/applications/draft", data={"id": "999"})
    assert r.status_code == 400
    assert calls == []


def _init_git(repo):
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)


def test_history_lists_commits(client, repo, monkeypatch):
    """resume_target()은 config 모듈 전역을 보므로 web.JK_MD가 아니라 config.JK_MD를 건다."""
    _init_git(repo)
    monkeypatch.setattr(config, "JK_MD", repo / "JK.md")
    subprocess.run(["git", "-C", str(repo), "add", "JK.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "이력서 초안"],
                   check=True, capture_output=True)

    r = client.get("/resume/history?key=JK.md")
    assert r.status_code == 200
    assert "이력서 초안" in r.text


def test_history_rejects_bad_key(client):
    r = client.get("/resume/history?key=../etc/passwd")
    assert r.status_code == 400


def test_revert_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_revert(key, sha):
        calls.append((key, sha))
        return "revert-test"

    monkeypatch.setattr(web, "start_revert", fake_start_revert)
    r = client.post("/resume/revert", data={"key": "JK.md", "sha": "abc1234"},
                    follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/resume/history?key=JK.md"
    assert calls == [("JK.md", "abc1234")]


def test_revert_rejects_bad_sha(client, monkeypatch):
    calls = []
    monkeypatch.setattr(web, "start_revert", lambda key, sha: calls.append((key, sha)))
    r = client.post("/resume/revert", data={"key": "JK.md", "sha": "zzz"})
    assert r.status_code == 400
    assert calls == []


def test_chat_new_session_redirects(client):
    r = client.get("/resume/chat?key=JK.md", follow_redirects=False)
    assert r.status_code == 302
    assert re.fullmatch(r"/resume/chat/[0-9a-f]{12}\?key=JK\.md", r.headers["location"])


def test_chat_rejects_bad_key(client):
    r = client.get("/resume/chat?key=../etc/passwd")
    assert r.status_code == 400


def test_chat_rejects_bad_sid(client):
    r = client.get("/resume/chat/..%2f..%2fetc")
    assert r.status_code == 400


def test_chat_page_renders_turns_and_diff(client, repo, monkeypatch):
    chat_dir = repo / "tmp" / "chat"
    chat_dir.mkdir(parents=True)
    monkeypatch.setattr(web, "CHAT_DIR", chat_dir)
    sid = "abcdef123456"
    (chat_dir / f"{sid}.json").write_text(json.dumps({
        "sid": sid, "target": "JK.md", "base_sha256": "x",
        "base_doc": "# JK\n\n이력 요약",
        "doc": "# JK\n\n이력 요약 (수정됨)",
        "turns": [
            {"role": "user", "text": "경력 3년으로 고쳐줘"},
            {"role": "assistant", "text": "반영했습니다", "applied": 1, "skipped": []},
        ],
        "created": "2026-08-26",
    }, ensure_ascii=False))

    r = client.get(f"/resume/chat/{sid}?key=JK.md")
    assert r.status_code == 200
    assert "경력 3년으로 고쳐줘" in r.text and "반영했습니다" in r.text
    assert "적용 1건" in r.text
    assert 'style="color:var(--good)"' in r.text   # diff의 + 줄


def test_chat_post_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_resume_chat(sid, key, message):
        calls.append((sid, key, message))
        return {"turns": []}

    monkeypatch.setattr(web, "start_resume_chat", fake_start_resume_chat)
    sid = "abcdef123456"
    r = client.post(f"/resume/chat/{sid}", data={"key": "JK.md", "message": "경력 3년으로"},
                    follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == f"/resume/chat/{sid}?key=JK.md"
    assert calls == [(sid, "JK.md", "경력 3년으로")]

    r2 = client.post(f"/resume/chat/{sid}", data={"key": "JK.md", "message": "  "},
                     follow_redirects=False)
    assert r2.status_code == 302
    assert calls == [(sid, "JK.md", "경력 3년으로")]   # 빈 메시지는 워크플로를 시작하지 않는다


def test_chat_end_shows_reason_instead_of_500(client, monkeypatch, tmp_path):
    """저장 거부(해시 게이트)가 스택트레이스 500이 아니라 이유와 다음 행동을 보여줘야 한다.
    2026-08-27 라이브 검증에서 맨 500이 뜨는 걸 발견해 추가."""
    sid = "a1b2c3d4e5f6"
    chat = tmp_path / "chat"
    chat.mkdir()
    (chat / f"{sid}.json").write_text(json.dumps(
        {"sid": sid, "target": "JK.md", "base_sha256": "x", "base_doc": "a",
         "doc": "b", "turns": [], "created": "2026-08-27"}, ensure_ascii=False))
    monkeypatch.setattr(web, "CHAT_DIR", chat)

    async def boom(sid, save):
        raise RuntimeError("대상 파일이 세션 시작 후 바뀌었습니다 — 저장 취소")

    monkeypatch.setattr(web, "end_chat", boom)
    r = client.post(f"/resume/chat/{sid}/end", data={"save": "1"}, follow_redirects=False)
    assert r.status_code == 200
    assert "저장하지 못했습니다" in r.text
    assert "세션 시작 후" in r.text
    assert f"/resume/chat/{sid}" in r.text        # 대화로 돌아가는 길
    assert "/resume/history?key=JK.md" in r.text  # 무엇이 바뀌었는지 보는 길


def test_chat_end_save_and_discard(client, monkeypatch):
    calls = []

    async def fake_end_chat(sid, save):
        calls.append((sid, save))
        return "저장됨" if save else "버림"

    monkeypatch.setattr(web, "end_chat", fake_end_chat)
    sid = "abcdef123456"
    r1 = client.post(f"/resume/chat/{sid}/end", data={"save": "1"}, follow_redirects=False)
    r2 = client.post(f"/resume/chat/{sid}/end", data={"save": "0"}, follow_redirects=False)

    assert r1.status_code == 302 and r1.headers["location"] == "/resume"
    assert r2.status_code == 302 and r2.headers["location"] == "/resume"
    assert calls == [(sid, True), (sid, False)]
