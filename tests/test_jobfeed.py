import json
import urllib.error

import pytest

from jobscouter import config, jobfeed


@pytest.fixture
def repo(tmp_path, monkeypatch):
    jobfeed_dir = tmp_path / "jobfeed"
    jobfeed_dir.mkdir()
    (tmp_path / "settings.json").write_text(json.dumps({"keywords": ["LLM"], "zones": []}))
    (jobfeed_dir / "candidates.json").write_text(json.dumps({"rows": [
        ["백엔드", "테스트회사", 222, [30, 18, 20, 16], None, "", [], None],
        ["플랫폼", "다른회사", "j5", [20, 15, 15, 12], None, "", [], "2026-09-01", "옛주소"],
    ], "skipped": {}}, ensure_ascii=False))
    (jobfeed_dir / "기업평판.md").write_text("| 회사 | 총점 | 리뷰 | 판정 |\n|---|---|---|---|\n| 회피회사 | 2 | 5 | 🚫 |\n")
    monkeypatch.setattr(config, "JOBFEED", jobfeed_dir)
    monkeypatch.setattr(config, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(jobfeed, "JOBFEED", jobfeed_dir)
    monkeypatch.setattr(jobfeed, "_sleep", lambda: None)
    return jobfeed_dir


WANTED = {"positions": {"data": [
    {"id": 222, "position": "백엔드", "company": {"name": "테스트회사"}, "address": {"location": "서울"}, "due_time": None},
    {"id": 777, "position": "LLM 엔지니어", "company": {"name": "새회사"}, "address": {"location": "서울"}, "due_time": "2026-09-30T00:00"},
    {"id": 888, "position": "MLOps", "company": {"name": "회피회사"}, "address": {}, "due_time": None},
]}}
JUMPIT = {"result": {"positions": [
    {"id": 5, "title": "플랫폼", "companyName": "다른회사", "locations": ["경기"], "minCareer": 3, "maxCareer": 7,
     "techStacks": ["<span>Python</span>"], "closedAt": "2026-09-01"},
]}}


def test_fetch_jobs_appends_new_and_tags_digest(repo, monkeypatch):
    monkeypatch.setattr(jobfeed, "_get", lambda url: WANTED if "wanted" in url else JUMPIT)
    out = jobfeed.fetch_jobs()
    lines = [json.loads(l) for l in (repo / "jobs.jsonl").read_text().splitlines()]
    assert {(j["src"], j["id"]) for j in lines} == {("wanted", 222), ("wanted", 777), ("wanted", 888), ("jumpit", 5)}
    assert lines[3]["stacks"] == ["Python"] and lines[3]["career"] == "3~7년"
    digest = (repo / "new.md").read_text()
    assert "[신규]" in digest and "새회사" in digest
    assert "`[기추적]` **[백엔드]" in digest           # candidates에 이미 있음
    assert "`[🚫]`" in digest and "회피회사" in digest
    assert "4건" in out
    # 재실행: 새 것 없음 → jobs.jsonl 그대로, new.md 유지
    assert "새 공고 없음" in jobfeed.fetch_jobs()
    assert len((repo / "jobs.jsonl").read_text().splitlines()) == 4


def test_fetch_jobs_survives_one_dead_source(repo, monkeypatch):
    def get(url):
        if "jumpit" in url:
            raise RuntimeError("down")
        return WANTED
    monkeypatch.setattr(jobfeed, "_get", get)
    jobfeed.fetch_jobs()
    assert len((repo / "jobs.jsonl").read_text().splitlines()) == 3


def test_refresh_due_updates_due_addr_and_closed(repo, monkeypatch):
    def get(url):
        if "/api/v4/jobs/222" in url:
            return {"job": {"due_time": "2026-10-01", "status": "active", "address": {"full_location": "서울 강남구 테헤란로"}}}
        raise urllib.error.HTTPError(url, 400, "gone", {}, None)     # 점핏 j5 내려감
    monkeypatch.setattr(jobfeed, "_get", get)
    out = jobfeed.refresh_due()
    rows = json.loads((repo / "candidates.json").read_text())["rows"]
    assert rows[0][7] == "2026-10-01" and rows[0][8] == "서울 강남구 테헤란로"
    assert rows[1][7] == "closed" and rows[1][8] == "옛주소"           # 내려간 공고는 주소 유지
    assert "마감됨 1" in out


def test_refresh_due_keeps_value_on_network_error(repo, monkeypatch):
    def get(url):
        raise OSError("timeout")
    monkeypatch.setattr(jobfeed, "_get", get)
    jobfeed.refresh_due()
    rows = json.loads((repo / "candidates.json").read_text())["rows"]
    assert rows[1][7] == "2026-09-01" and len(rows[0]) == 9 and rows[0][7] is None
