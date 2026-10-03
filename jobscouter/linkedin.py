"""LinkedIn 비로그인 공개 공고 목록·본문. 로그인이나 접근 제한을 우회하지 않는다."""
import re
import time
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlencode

from jobscouter.company_jobs import _get, _job, _soup, _text
from jobscouter.config import job_reference

_API = "https://www.linkedin.com/jobs-guest/jobs/api"
# LinkedIn Help a507441: 검색 결과는 최대 1,000개까지 조회할 수 있다.
MAX_SEARCH_RESULTS = 1000
_REQUEST_LOCK = Lock()
_last_request = 0.0
_blocked_until = 0.0
_rate_limit_error = None
_REGIONS = {
    "Seoul": "서울", "Seongnam": "성남", "Gyeonggi-do": "경기", "Gyeonggi": "경기",
    "Incheon": "인천", "Suwon": "수원", "Yongin": "용인", "Anyang": "안양",
    "Gwacheon": "과천", "Uiwang": "의왕", "Gunpo": "군포", "Gwangmyeong": "광명",
    "Bucheon": "부천", "Hwaseong": "화성", "Goyang": "고양", "Bundang": "분당",
    "Pangyo": "판교", "Gangnam": "강남", "Seocho": "서초", "Songpa": "송파",
    "Gangdong": "강동", "Gangseo": "강서", "Mapo": "마포", "Yeongdeungpo": "영등포",
    "Busan": "부산", "Daegu": "대구", "Daejeon": "대전", "Gwangju": "광주",
    "Ulsan": "울산", "Sejong": "세종", "Jeju": "제주", "South Korea": "대한민국",
}
_REGION_PATTERN = re.compile(r"\b(" + "|".join(map(re.escape, _REGIONS)) + r")(-si|-gu)?\b",
                             re.IGNORECASE)
_REGION_NAMES = {key.lower(): value for key, value in _REGIONS.items()}


class SearchLimitReached(RuntimeError):
    """조회 한도에 도달했으며 앞서 전달한 공고는 부분 수집 결과다."""

    def __init__(self, count: int):
        self.count = count
        self.limit = MAX_SEARCH_RESULTS
        super().__init__(f"LinkedIn: 검색 조회 한도 도달 (수집 {count}개 / 한도 {self.limit}개)")


def _request(url: str) -> str:
    global _last_request, _blocked_until, _rate_limit_error
    with _REQUEST_LOCK:
        now = time.monotonic()
        if _rate_limit_error is not None and now < _blocked_until:
            raise _rate_limit_error
        delay = 2 - (now - _last_request)
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()
        try:
            return _get(url)
        except HTTPError as error:
            if error.code == 429:
                retry_after = (error.headers.get("Retry-After") or "").strip() if error.headers else ""
                cooldown = 3600
                if re.fullmatch(r"\d+", retry_after):
                    cooldown = int(retry_after)
                elif retry_after:
                    try:
                        cooldown = max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        pass
                _blocked_until = time.monotonic() + cooldown
                _rate_limit_error = error
            raise


def _location(raw: str) -> str:
    def replace(match):
        name, suffix = match[1].lower(), (match[2] or "").lower()
        if name == "gwangju":
            return "광주시" if re.search(r"\bGyeonggi(?:-do)?\b", raw, re.IGNORECASE) else "광주광역시"
        return _REGION_NAMES[name] + {"-si": "시", "-gu": "구", "": ""}[suffix]

    return _REGION_PATTERN.sub(replace, raw)


def _required(node, selector: str, context: str) -> str:
    tag = node.select_one(selector)
    value = tag.get_text(" ", strip=True) if tag else ""
    if not value:
        raise ValueError(f"LinkedIn/{context}: 필수 공고 정보 없음 ({selector})")
    return value


def search(keyword: str):
    """최근 7일 한국 공고를 공식 조회 한도까지 읽고, ID로 중복을 제거한다."""
    start, seen = 0, set()
    while start < MAX_SEARCH_RESULTS:
        query = urlencode({"keywords": keyword, "location": "South Korea", "start": start,
                           "f_TPR": "r604800", "sortBy": "DD"})
        soup = _soup(_request(f"{_API}/seeMoreJobPostings/search?{query}"))
        cards = soup.select('[data-entity-urn^="urn:li:jobPosting:"]')
        if not cards:
            # 공개 guest endpoint의 마지막 페이지는 공백/DOCTYPE/주석뿐이다.
            if soup.find() is not None or soup.get_text(strip=True):
                raise ValueError("LinkedIn: 검색 목록 없음 — 로그인/응답 형식 확인 필요")
            return
        page = []
        for card in cards[:MAX_SEARCH_RESULTS - start]:
            match = re.fullmatch(r"urn:li:jobPosting:(\d+)", card["data-entity-urn"])
            if not match:
                raise ValueError("LinkedIn: 검색 공고 ID 형식 오류")
            pid = match[1]
            reference = job_reference(f"linkedin_{pid}")
            title = _required(card, ".base-search-card__title", pid)
            company = _required(card, ".base-search-card__subtitle", pid)
            location = _required(card, ".job-search-card__location", pid)
            posted = card.select_one("time[datetime]")
            page.append({"src": "linkedin", "id": pid, "title": title, "company": company,
                         "loc": _location(location), "source_location": location,
                         "career": "미확인", "stacks": [], "due": "상시",
                         "url": reference["url"], "kw": keyword,
                         "posted_at": posted["datetime"] if posted else ""})
        if not ({row["id"] for row in page} - seen):
            raise ValueError(f"LinkedIn: 검색 페이지 반복 (start={start})")
        for row in page:
            if row["id"] not in seen:
                seen.add(row["id"])
                yield row
        start += len(cards)
    raise SearchLimitReached(len(seen))


def detail(pid: str) -> dict:
    job_reference(f"linkedin_{pid}")  # 네트워크 요청 전에 저장 ID를 검증한다.
    soup = _soup(_request(f"{_API}/jobPosting/{pid}"))
    title = _required(soup, ".topcard__title", pid)
    company = _required(soup, ".topcard__org-name-link", pid)
    location = _required(soup, ".topcard__flavor-row > span.topcard__flavor--bullet", pid)
    description = soup.select_one(".description__text")
    body = _text(description.select_one(".show-more-less-html__markup") or description) if description else ""
    if not body:
        raise ValueError(f"LinkedIn/{pid}: 공고 본문 없음 — 로그인/응답 형식 확인 필요")
    criteria = soup.select_one(".description__job-criteria-list")
    if criteria:
        body += "\n\n" + _text(criteria)
    status = " ".join(tag.get_text(" ", strip=True) for tag in
                      soup.select(".closed-job__flavor, .topcard__flavor"))
    closed = bool(re.search(r"no longer accepting applications|더 이상 지원서를 받지|지원 접수.{0,10}마감",
                            status, re.IGNORECASE))
    row = _job("linkedin", pid, title, company, body, loc=_location(location), closed=closed)
    row["source_location"] = location
    return row
