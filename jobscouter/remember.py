"""리멤버 비로그인 공개 API — 제목 검색과 기술 태그 검색의 합집합."""
import json
import time

from jobscouter.company_jobs import _get, _job
from jobscouter.config import job_reference, settings

_API = "https://career-api.rememberapp.co.kr/job_postings"


def _posting(p: dict) -> dict:
    organization = p["organization"]
    education = {"bachelor": "학사 이상", "master": "석사 이상", "doctor": "박사 이상",
                 "none": "무관"}.get(p.get("education_requirement"), p.get("education_requirement"))
    parts = {"자격요건": p.get("qualifications"), "학력": education,
             "주요업무": p.get("job_description"), "우대사항": p.get("preferred_qualifications"),
             "소개": p.get("introduction"), "채용절차": p.get("recruiting_process"),
             "기타안내": p.get("additional_information")}
    if organization.get("headhunter"):
        parts["채용 주체"] = "헤드헌팅 공고. 표시 회사는 채용 대행사이며 실제 고용회사는 별도 확인 필요."
    salary = [str(p[k]) for k in ("min_salary", "max_salary") if p.get(k) is not None]
    if salary:
        parts["연봉(만원)"] = " ~ ".join(salary)
    low, high = p.get("min_experience"), p.get("max_experience")
    career = f"{low or 0}~{high}년" if high is not None else (f"{low}년 이상" if low else "무관")
    loc = ", ".join(" ".join(a.get(k) or "" for k in ("address_level1", "address_level2")).strip()
                    for a in p.get("addresses") or [])
    row = _job("remember", p["id"], p["title"], organization["name"],
               "\n\n".join(f"{k}\n{v}" for k, v in parts.items() if v), p.get("ends_at"),
               loc, career, closed=p["status"] != "published")
    row["stacks"] = [s["name"] for s in (p.get("desired_profile_condition") or {}).get("skills", [])]
    return row


def detail(pid: str) -> dict:
    job_reference(f"remember_{pid}")
    time.sleep(2)
    return _posting(json.loads(_get(f"{_API}/{pid}"))["data"])


def load() -> list[dict]:
    keywords = settings()["keywords"]
    if not keywords:
        return []
    jobs = {}
    searches = [{"keywords": [kw]} for kw in dict.fromkeys(keywords)] + [{"skills": keywords}]
    for search in searches:
        page, pages, seed, seen = 1, 1, None, set()
        while page <= pages:
            body = {"search": search, "page": page, "per": 30, "sort": "starts_at_desc"}
            if seed is not None:
                body["seed"] = seed
            data = json.loads(_get(f"{_API}/search", json_body=body))
            meta, postings = data["meta"], data["data"]
            pages = int(meta["total_pages"])
            ids = {p["id"] for p in postings}
            if (meta["page"] != page or pages < page or not isinstance(postings, list)
                    or (meta["total_count"] and not (ids - seen))):
                raise ValueError(f"리멤버: 검색 페이지 누락/반복 ({search}, {page})")
            seen.update(ids)
            for p in postings:
                jobs[str(p["id"])] = _posting(p)
            seed = meta.get("seed")
            page += 1
            time.sleep(2)  # 공개 API 요청 제한: 분당 30회 이하로 순차 조회한다.
    return list(jobs.values())
