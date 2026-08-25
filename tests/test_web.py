import json

import pytest
from fastapi.testclient import TestClient

import jobscouter.web as web


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
