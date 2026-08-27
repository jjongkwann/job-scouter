import json
import re
import subprocess
from datetime import datetime, timedelta
from urllib.parse import unquote

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
        "333": {"id": "333", "company": "테스트회사", "title": "플랫폼 엔지니어",
                "url": "https://example.com/333", "src": "wanted",
                "scores": [20, 15, 15, 12, 0], "total": 62,
                "reason": "부분 일치", "quotes": [], "confidence": 0.5,
                "rubric_version": "v1", "judged_at": "2026-08-24"},
    }, ensure_ascii=False))
    # 마감은 proposals.json이 아니라 jobs.jsonl에 있다
    soon = (datetime.now(web.KST).date() + timedelta(days=10)).isoformat()
    (jobfeed / "jobs.jsonl").write_text(
        json.dumps({"src": "wanted", "id": 111, "due": "2020-01-01"}) + "\n"
        + json.dumps({"src": "wanted", "id": 333, "due": soon}) + "\n")
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

    (tmp_path / "이력서.md").write_text("# 이력서\n\n이력 요약")
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "이력서_사실베이스.md").write_text("# 사실베이스\n\n경력 사실")
    # 사실베이스·drafts는 더 이상 /resume이 렌더하지 않는다 — 아래 두 파일이 응답에
    # 새지 않는지 확인하는 용도로만 둔다(파일 자체는 web에 patch하지 않는다)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "old.md").write_text("# 옛날 초안\n\n버려진 초안 본문")

    monkeypatch.setattr(web, "JOBFEED", jobfeed)
    monkeypatch.setattr(web, "RESUME", tmp_path / "이력서.md")
    apps = tmp_path / "applications"
    (apps / "test_co").mkdir(parents=True)
    # 연결 키는 회사명이 아니라 문서에 적힌 공고 URL — 폴더명(test_co)은 회사명(테스트회사)과 다르다
    (apps / "test_co" / "0_JD.md").write_text(
        "# JD\n\n> 원본: https://www.wanted.co.kr/wd/222\n\n본문")
    (apps / "test_co" / "1_맞춤_이력서.md").write_text("# 이력서\n\n내용")
    (apps / "no_link").mkdir()
    (apps / "no_link" / "README.md").write_text("# 링크 없는 폴더\n\n공고 주소가 없다")

    monkeypatch.setattr(web, "APPLICATIONS", apps)
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


def test_dashboard_marks_past_due(client):
    r = client.get("/")
    assert "마감 지남 01-01" in r.text   # 111 — 마감이 지나도 목록에서 사라지지 않는다
    assert "D-10" in r.text              # 333 — 남은 날짜
    assert re.search(r'>1</div><div class="l">마감 지남<', r.text)


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


def test_resume_shows_single_document(client):
    r = client.get("/resume")
    assert r.status_code == 200
    assert "이력서.md" in r.text
    assert "이력 요약" in r.text
    # 사실베이스·drafts는 더 이상 렌더하지 않는다
    assert "경력 사실" not in r.text
    assert "옛날 초안" not in r.text
    assert "버려진 초안 본문" not in r.text


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


def test_applications_joins_folder_by_job_id(client):
    """폴더 ↔ 공고 연결은 회사명이 아니라 문서에 적힌 공고 id로 한다."""
    r = client.get("/applications")
    assert r.status_code == 200
    linked, orphan = r.text.split("공고를 못 찾은 폴더")
    assert "test_co" in linked and "테스트회사" in linked   # 폴더명≠회사명인데도 이어졌다
    assert "2 / 5" in linked                                # 0_JD·1_맞춤_이력서만 있다
    assert "no_link" in orphan and "test_co" not in orphan


def test_job_screen_shows_posting_header(client):
    r = client.get("/applications/job/222")
    assert r.status_code == 200
    assert "백엔드 엔지니어" in r.text and "테스트회사" in r.text
    assert "79" in r.text                        # 적합도 = 30+18+20+16-5
    assert "1_맞춤_이력서.md" in r.text          # 문서 탭
    assert "3_면접지식맵.md 없음" in r.text      # 빠진 표준 문서는 자리를 남긴다


def test_job_screen_without_folder_offers_draft(client, monkeypatch):
    monkeypatch.setattr(web, "APPLICATIONS", web.APPLICATIONS / "없는곳")
    r = client.get("/applications/job/222")
    assert r.status_code == 200
    assert "아직 문서가 없습니다" in r.text and "초안 만들기" in r.text


def test_candidates_injects_app_index(client):
    """후보목록.html은 build.py 산출물 — 웹앱이 색인만 끼워 넣고 본문은 그대로 둔다."""
    r = client.get("/candidates")
    assert r.status_code == 200
    assert "후보목록 본문" in r.text
    assert '"222"' in r.text.split("window.__APPS__=")[1].split(";</script>")[0]


def test_draft_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_draft(cid):
        calls.append(cid)
        return "draft-test"

    monkeypatch.setattr(web, "start_draft", fake_start_draft)
    r = client.post("/applications/draft", data={"id": "222"}, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/applications/job/222"
    assert calls == ["222"]


def test_draft_rejects_unlisted_id(client, monkeypatch):
    calls = []
    monkeypatch.setattr(web, "start_draft", lambda cid: calls.append(cid))
    r = client.post("/applications/draft", data={"id": "999"})
    assert r.status_code == 400
    assert calls == []


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True)


def _init_git(repo):
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)


def test_history_lists_commits(client, repo, monkeypatch):
    """resume_target()은 config 모듈 전역을 보므로 web.RESUME가 아니라 config.RESUME를 건다."""
    _init_git(repo)
    monkeypatch.setattr(config, "RESUME", repo / "이력서.md")
    subprocess.run(["git", "-C", str(repo), "add", "이력서.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "이력서 초안"],
                   check=True, capture_output=True)

    r = client.get("/resume/history", params={"key": "이력서.md"})
    assert r.status_code == 200
    assert "이력서 초안" in r.text


def test_history_follows_rename(client, repo, monkeypatch):
    """이름을 바꾼 파일도 옛 이력이 이어지고 그 시절 diff가 나온다 (JK.md → 이력서.md)."""
    _init_git(repo)
    (repo / "이력서.md").unlink()
    (repo / "JK.md").write_text("# 이력서\n\n옛 이름 시절 본문\n")
    _git(repo, "add", "JK.md")
    _git(repo, "commit", "-m", "옛 이름 시절 커밋")
    old = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    _git(repo, "mv", "JK.md", "이력서.md")
    _git(repo, "commit", "-m", "이름 변경")
    monkeypatch.setattr(config, "RESUME", repo / "이력서.md")

    r = client.get("/resume/history", params={"key": "이력서.md"})
    assert "옛 이름 시절 커밋" in r.text          # --follow 없으면 이름 변경 커밋 1건만 남는다
    d = client.get("/resume/history", params={"key": "이력서.md", "sha": old})
    assert "옛 이름 시절 본문" in d.text          # diff는 그 커밋 시점 이름으로 찾아야 나온다


def test_history_rejects_bad_key(client):
    r = client.get("/resume/history?key=../etc/passwd")
    assert r.status_code == 400


def test_revert_starts_workflow(client, monkeypatch):
    calls = []

    async def fake_start_revert(key, sha):
        calls.append((key, sha))
        return "revert-test"

    monkeypatch.setattr(web, "start_revert", fake_start_revert)
    r = client.post("/resume/revert", data={"key": "이력서.md", "sha": "abc1234"},
                    follow_redirects=False)

    assert r.status_code == 302
    assert unquote(r.headers["location"]) == "/resume/history?key=이력서.md"
    assert calls == [("이력서.md", "abc1234")]


def test_revert_rejects_bad_sha(client, monkeypatch):
    calls = []
    monkeypatch.setattr(web, "start_revert", lambda key, sha: calls.append((key, sha)))
    r = client.post("/resume/revert", data={"key": "이력서.md", "sha": "zzz"})
    assert r.status_code == 400
    assert calls == []


def test_chat_new_session_redirects(client):
    r = client.get("/resume/chat", params={"key": "이력서.md"}, follow_redirects=False)
    assert r.status_code == 302
    assert re.fullmatch(r"/resume/chat/[0-9a-f]{12}\?key=이력서\.md", unquote(r.headers["location"]))


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
        "sid": sid, "target": "이력서.md", "base_sha256": "x",
        "base_doc": "# 이력서\n\n이력 요약",
        "doc": "# 이력서\n\n이력 요약 (수정됨)",
        "turns": [
            {"role": "user", "text": "경력 3년으로 고쳐줘"},
            {"role": "assistant", "text": "반영했습니다", "applied": 1, "skipped": []},
        ],
        "created": "2026-08-26",
    }, ensure_ascii=False))

    r = client.get(f"/resume/chat/{sid}", params={"key": "이력서.md"})
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
    r = client.post(f"/resume/chat/{sid}", data={"key": "이력서.md", "message": "경력 3년으로"},
                    follow_redirects=False)

    assert r.status_code == 302
    assert unquote(r.headers["location"]) == f"/resume/chat/{sid}?key=이력서.md"
    assert calls == [(sid, "이력서.md", "경력 3년으로")]

    r2 = client.post(f"/resume/chat/{sid}", data={"key": "이력서.md", "message": "  "},
                     follow_redirects=False)
    assert r2.status_code == 302
    assert calls == [(sid, "이력서.md", "경력 3년으로")]   # 빈 메시지는 워크플로를 시작하지 않는다


def test_chat_end_shows_reason_instead_of_500(client, monkeypatch, tmp_path):
    """저장 거부(해시 게이트)가 스택트레이스 500이 아니라 이유와 다음 행동을 보여줘야 한다.
    2026-08-27 라이브 검증에서 맨 500이 뜨는 걸 발견해 추가."""
    sid = "a1b2c3d4e5f6"
    chat = tmp_path / "chat"
    chat.mkdir()
    (chat / f"{sid}.json").write_text(json.dumps(
        {"sid": sid, "target": "이력서.md", "base_sha256": "x", "base_doc": "a",
         "doc": "b", "turns": [], "created": "2026-08-27"}, ensure_ascii=False))
    monkeypatch.setattr(web, "CHAT_DIR", chat)

    async def boom(sid, save):
        # Temporal은 activity 예외를 두 겹으로 감싼다 — 실제 사유는 __cause__ 끝에 있다
        try:
            raise RuntimeError("대상 파일이 세션 시작 후 바뀌었습니다 — 저장 취소")
        except RuntimeError as inner:
            raise Exception("Workflow execution failed") from inner

    monkeypatch.setattr(web, "end_chat", boom)
    r = client.post(f"/resume/chat/{sid}/end", data={"save": "1"}, follow_redirects=False)
    assert r.status_code == 200
    assert "저장하지 못했습니다" in r.text
    assert "세션 시작 후" in r.text
    assert f"/resume/chat/{sid}" in r.text          # 대화로 돌아가는 길
    assert "/resume/history?key=이력서.md" in r.text  # 무엇이 바뀌었는지 보는 길


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
