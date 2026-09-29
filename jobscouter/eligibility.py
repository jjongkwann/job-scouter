"""수집원의 구조화된 연차를 표시하고 AI 경력 검토 대상을 구분한다."""
import json
import re
from pathlib import Path

from jobscouter import config


def career_label(low, high, newbie=False) -> str:
    if type(low) is int and low >= 0:
        if type(high) is int and low <= high < 100:
            return f"{low}~{high}년"
        return f"{low}년 이상" if low else "신입/무관"
    return "신입" if newbie else "경력"


def careers(jobfeed: Path) -> dict[str, str]:
    path = jobfeed / "jobs.jsonl"
    if not path.exists():
        return {}
    return {config.job_cid(j): j.get("career") or "미확인"
            for j in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def minimum_years(career: str) -> int | None:
    # 자유문장·우대·복수 직무는 추측하지 않고 판정기에 원문을 넘긴다.
    match = re.fullmatch(r"\s*(\d+)\s*(?:[~～–-]\s*\d+\s*년|년\s*이상)\s*", career)
    return int(match[1]) if match else None


def needs_experience_review(career: str) -> bool:
    return (minimum_years(career) or 0) >= 7
