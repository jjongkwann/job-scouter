import json

import pytest

from jobscouter import company_jobs, remember


def test_public_search_paginates_deduplicates_and_preserves_requirements(monkeypatch):
    posting = {"id": 12, "title": "AI 개발", "organization": {"name": "채용회사"},
               "status": "published", "qualifications": "Python 경험", "education_requirement": "bachelor",
               "job_description": "RAG 서비스", "preferred_qualifications": "Kubernetes 우대",
               "recruiting_process": "코딩테스트", "additional_information": "2년 후 전환 심사",
               "ends_at": "2026-09-28T14:59:59Z", "min_experience": 3, "max_experience": 5,
               "min_salary": 5890, "max_salary": 5900,
               "addresses": [{"address_level1": "경기도", "address_level2": "성남시 분당구"}],
               "desired_profile_condition": {"skills": [{"name": "Python"}]}}
    calls = []
    def get(url, *, json_body=None):
        if json_body is None:
            return json.dumps({"data": {**posting, "status": "closed"}})
        calls.append(json_body)
        page = json_body["page"]
        return json.dumps({"data": [{**posting, "id": 11 + page}],
                           "meta": {"page": page, "total_pages": 2, "total_count": 2, "seed": 17}})
    monkeypatch.setattr(remember, "_get", get)
    monkeypatch.setattr(remember, "settings", lambda: {"keywords": ["Python"]})
    monkeypatch.setattr(remember.time, "sleep", lambda n: None)
    jobs = company_jobs.load("remember")
    assert [j["id"] for j in jobs] == ["12", "13"]
    assert [c["page"] for c in calls] == [1, 2, 1, 2]
    assert calls[1]["seed"] == 17 and calls[2]["search"] == {"skills": ["Python"]}
    assert jobs[0]["due"] == "2026-09-28" and jobs[0]["loc"] == "경기도 성남시 분당구"
    assert jobs[0]["url"] == "https://career.rememberapp.co.kr/job/posting/12"
    assert jobs[0]["stacks"] == ["Python"]
    assert all(s in jobs[0]["description"] for s in ["자격요건\nPython", "학사 이상",
               "우대사항\nKubernetes 우대", "코딩테스트", "2년 후 전환", "5890 ~ 5900"])
    assert company_jobs.detail("remember", "12")["due"] == "closed"
    posting["organization"]["headhunter"] = True
    assert "채용 대행사" in company_jobs.detail("remember", "12")["description"]
    monkeypatch.setattr(remember, "_get", lambda *a, **k: json.dumps({"data": [posting],
                        "meta": {"page": 1, "total_pages": 2, "total_count": 2}}))
    with pytest.raises(ValueError, match="페이지 누락/반복"):
        company_jobs.load("remember")
