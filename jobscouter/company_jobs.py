"""공식 채용 사이트의 공개 목록·본문. 로그인·지원서 제출 없이 조회만 한다."""
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from jobscouter.config import job_cid, job_reference


def _get(url: str, form: dict | None = None, *, json_body: dict | None = None) -> str:
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
    if urllib.parse.urlsplit(url).hostname == "talent.hyundai.com":
        # 공개 페이지의 common.axios.js와 같은 비로그인 요청 헤더.
        headers.update({"X-HKMC-SERVICE": "HM", "X-HKMC-TOKEN": "null"})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8-sig")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(html) -> str:
    soup = _soup(str(html or "").replace("\\n", "\n").replace("\u200b", ""))
    for tag in soup.select("script, style, .dict-wrap"):
        tag.decompose()
    for tag in soup.select("br, p, div, li, h1, h2, h3, h4, h5"):
        tag.insert_before("\n")
    return "\n".join(line.strip() for line in soup.get_text().splitlines() if line.strip())


def _date(raw) -> str | None:
    if not raw:
        return None
    if "T" in str(raw):
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is not None:
            return stamp.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    match = re.search(r"(\d{4})[.년/-]?\s*(\d{2})[.월/-]?\s*(\d{2})", str(raw))
    if not match:
        raise ValueError(f"공고 마감일을 읽을 수 없음: {raw}")
    return datetime.strptime("-".join(match.groups()), "%Y-%m-%d").date().isoformat()


def _job(src, pid, title, company, description, due=None, loc="", career="", closed=False):
    body = _text(description)
    if not str(title or "").strip() or not body:
        raise ValueError(f"{src}/{pid}: 공고 제목·본문 없음")
    row = {"src": src, "id": str(pid), "title": _text(title), "company": company,
           "description": body, "due": "closed" if closed else (_date(due) or "상시"),
           "loc": loc or "", "career": career or "미확인", "stacks": [], "kw": ""}
    row["url"] = job_reference(job_cid(row))["url"]
    return row


def _next_data(html: str) -> dict:
    tag = _soup(html).select_one("#__NEXT_DATA__")
    if tag is None:
        raise ValueError("페이지의 공고 데이터가 없음")
    return json.loads(tag.string)["props"]["pageProps"]


def _daangn(pid):
    url = job_reference(f"daangn_{pid}")["url"]
    for tag in _soup(_get(url)).select('script[type="application/ld+json"]'):
        data = json.loads(tag.string)
        for item in data if isinstance(data, list) else [data]:
            if item.get("@type") == "JobPosting":
                addr = (item.get("jobLocation") or {}).get("address") or {}
                return _job("daangn", pid, item["title"], item["hiringOrganization"]["name"],
                            item["description"], item.get("validThrough"),
                            " ".join(addr.get(k) or "" for k in
                                     ("addressRegion", "addressLocality", "streetAddress")).strip(),
                            item.get("employmentType"))
    raise ValueError(f"당근/{pid}: JobPosting 없음")


_TOSS = "https://api-public.toss.im/api/v3/ipd-eggnog/career/job-groups"


def _toss_jobs():
    groups = json.loads(_get(_TOSS))["success"]
    if not isinstance(groups, list):
        raise ValueError("토스: 공고 목록 조회 실패")
    seen = set()
    for group in groups:
        for p in group["jobs"]:
            meta = {m["id"]: m["value"] for m in p["metadata"]}
            if (p["id"] in seen or p["internal_job_id"] is None
                    or meta.get(5038345003) in (True, "t")):
                continue
            seen.add(p["id"])
            yield _job("toss", p["id"], p["title"], meta[4169410003], meta[4155730003],
                       meta.get(11431213003), p["location"].get("name"), meta.get(4112432003))


def _toss(pid):
    props = _next_data(_get(job_reference(f"toss_{pid}")["url"]))
    for q in props["prefetchResult"]["dehydratedState"]["queries"]:
        if q["queryKey"][1:3] == ["job-detail", str(pid)]:
            p = json.loads(q["state"]["data"])["job"]
            return _job("toss", pid, p["title"], p["company"], p["description"],
                        p.get("expiryDate"), p.get("location"), p.get("employmentType"))
    raise ValueError(f"토스/{pid}: 공고 본문 없음")


def _samsung_notice(pid):
    data = json.loads(_get("https://www.samsungcareers.com/recruit/detail.data?" +
                          urllib.parse.urlencode({"seqno": pid, "strCode": ""})))
    if data.get("success") is not True:
        raise ValueError(f"삼성/{pid}: 공고 조회 실패")
    return data["data"]


def _samsung_roles(data):
    p = data["result"]
    for role in data["items"]:
        if role.get("rmYn") == "Y":
            continue
        parts = {"공통 지원자격": p.get("qlfctKr"), "지원자격": role.get("qlfctKr"),
                 "우대사항": role.get("favorKr"), "수행업무": role.get("taskKr"),
                 "직무소개": role.get("explnKr"), "참고사항": role.get("memoKr"),
                 "회사소개": p.get("introKr"), "지원안내": p.get("processKr"),
                 "기타사항": p.get("etcKr"), "접수 마감": p["enddate"]}
        body = "\n\n".join(f"{k}\n{v}" for k, v in parts.items() if v)
        job = _job("samsung", f"{p['seq']}_{role['seq']}", f"{role['titleKr']} — {p['title']}",
                   p["cmpNameKr"], body, p["enddate"], role.get("workPlaceKr"),
                   {"A": "신입", "B": "경력", "C": "인턴"}.get(p.get("recruitType")),
                   closed=str(p["isOpened"]) != "1")
        job["pdfs"] = [{"title": f["fileOriginalName"],
                        "url": "https://www.samsungcareers.com/download?" + urllib.parse.urlencode({
                            "path": f["filePath"].replace("/", ","), "sfile": f["fileName"],
                            "ofile": f["fileOriginalName"]})}
                       for f in [*(data.get("addFiles") or []), *(role.get("files") or [])]
                       if f["fileName"].lower().endswith(".pdf")]
        yield job


def pdf_text(url: str) -> str:
    """삼성 공식 첨부 PDF. 텍스트가 없는 페이지는 한국어·영어 OCR로 읽는다."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme, parsed.netloc, parsed.path) != ("https", "www.samsungcareers.com", "/download"):
        raise ValueError("삼성 공식 첨부 URL이 아닙니다")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(20_000_001)
    if len(data) > 20_000_000:
        raise ValueError("공고 PDF가 20MB를 초과합니다")
    # PyMuPDF는 멀티스레드를 지원하지 않으므로 io 워커의 스레드에서 별도 프로세스로 실행.
    result = subprocess.run([sys.executable, "-m", "jobscouter.pdf"], input=data,
                            capture_output=True, timeout=180, check=True)
    return result.stdout.decode()


def _samsung_jobs():
    page, pages = 1, 1
    while page <= pages:
        soup = _soup(_get("https://www.samsungcareers.com/hr/list.data",
                         {"currentPageNo": page, "intNo": 0, "strVal": "", "strTxt": "",
                          "strKey": "", "strCompany": "", "strType": "",
                          "strOrderBy": "AA", "strEntity": ""}))
        count = soup.select_one(".divCnt")
        if count is None:
            raise ValueError("삼성: 공고 목록 형식 변경")
        pages = int(count["data-max"])
        for a in soup.select("a[data-value]"):
            yield from _samsung_roles(_samsung_notice(a["data-value"].replace(",", "")))
        page += 1


def _samsung(pid):
    return next(p for p in _samsung_roles(_samsung_notice(pid.split("_")[0])) if p["id"] == pid)


def _lg_notice(notice):
    data = json.loads(_get("https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail",
                          json_body={"jobNoticeId": int(notice)}))
    if data.get("status") != "S":
        raise ValueError(f"LG/{notice}: 공고 조회 실패")
    return data["data"]["jobNoticesDetail"]


def _lg_roles(notice, detail):
    p = detail["jobNoticesDetail"]
    if not detail["recList"]:
        raise ValueError(f"LG/{notice}: 모집 직무 없음")
    for role in detail["recList"]:
        parts = {"공통 지원자격": p.get("qualForAppInfo"), "지원자격": role.get("requiredItem"),
                 "우대사항": role.get("preferredItem"), "직무소개": role.get("detailContext"),
                 "전공": role.get("majorCodeName"), "접수 마감": p["recEndDate"],
                 "전형절차": p.get("recProcessInfo"), "지원안내": p.get("submitMethodInfo")}
        yield _job("lg", f"{notice}_{role['recSectorId']}",
                   f"{role['jobGroupName']} — {p['jobNoticeName']}", p["companyName"],
                   "\n\n".join(f"{k}\n{v}" for k, v in parts.items() if v),
                   p["recEndDate"], role.get("locationName"), p.get("careerTypeName"),
                   closed=str(p["recAvail"]) != "1")


def _lg_jobs():
    data = json.loads(_get("https://api.careers.lg.com/rmk/job/retrieveJobNoticesList",
                          json_body={"lnbSearch": "", "hashTagText": "", "recDate": "CREATION_DATE",
                                     "order": "DESC", "careerList": [], "companyCodeList": ["CNS"],
                                     "desireLocList": [], "jobGroupList": []}))
    if data.get("status") != "S":
        raise ValueError("LG CNS: 공고 목록 조회 실패")
    data = data["data"]
    if len(data["jobNoticeList"]) != int(data["listCount"]):
        raise ValueError("LG CNS: 공고 목록 일부 누락")
    for p in data["jobNoticeList"]:
        if p["companyCode"] != "CNS":
            raise ValueError("LG CNS: 회사 필터 불일치")
        yield from _lg_roles(p["jobNoticeId"], _lg_notice(p["jobNoticeId"]))


def _lg(pid):
    for job in _lg_roles(pid.split("_")[0], _lg_notice(pid.split("_")[0])):
        if job["id"] == pid:
            return job
    raise ValueError(f"LG/{pid}: 모집 직무 없음")


def _sk(pid):
    soup = _soup(_get(job_reference(f"sk_{pid}")["url"]))
    fields = {x.select_one(".label").get_text(strip=True):
              x.get_text(" ", strip=True).removeprefix(x.select_one(".label").get_text(" ", strip=True)).strip()
              for x in soup.select(".box-detail-item")}
    sections = soup.select(".detail-content-item")
    title = soup.select_one("h2.box-title")
    if title is None or not sections:
        raise ValueError(f"SK/{pid}: 공고 본문 없음")
    due = fields["지원 기간"].split("~")[-1]
    body = "\n\n".join(str(x) for x in sections)
    for image in soup.select(".detail-content-item img[src]"):
        body += "\n[이미지에서 인식한 본문 — OCR 오인식 가능]\n" + _ocr(image["src"])
    return _job("sk", pid, title.get_text(), fields["회사"], body,
                due, fields.get("지역"), fields.get("구분"))


def _ocr(url: str) -> str:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("공고 이미지는 HTTPS URL이어야 합니다")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(10_000_001)
    if len(data) > 10_000_000:
        raise ValueError("공고 이미지가 10MB를 초과합니다")
    result = subprocess.run(["tesseract", "stdin", "stdout", "-l", "kor+eng", "--psm", "6"],
                            input=data, capture_output=True, timeout=60, check=True)
    text = result.stdout.decode().strip()
    if len(text) < 40:
        raise ValueError("공고 이미지의 본문을 인식하지 못했습니다")
    return text


def _sk_jobs():
    data = json.loads(_get("https://www.skcareers.com/Recruit/GetRecruitList",
                          {"sort": 1, "searchText": "", "corpCode": "", "jobRole": "",
                           "recruitType": "", "workingType": "", "workingRegion": ""}))
    if data.get("success") is not True or len(data["list"]) != data["totalCount"]:
        raise ValueError("SK: 공고 목록 조회 실패 또는 일부 누락")
    for p in data["list"]:
        yield _sk(p["noticeID"])


_HYUNDAI = "https://talent.hyundai.com/api/rec/"


def _hyundai(pid):
    year, kind, number = pid.split("_")
    q = urllib.parse.urlencode({"hgrCd": 1, "lang": "ko", "recuYy": year,
                                "recuType": kind, "recuCls": number})
    p = json.loads(_get(_HYUNDAI + "AP-HM-FO-02800?" + q))["data"]["applyInfo"]
    if p.get("recuNoticeSecretYn") == "Y":
        raise ValueError("현대자동차: 비공개 공고")
    parts = {"지원자격": p.get("privMustReq"), "우대사항": p.get("prefReq"),
             "직무상세": p.get("privJdDtl"), "조직소개": p.get("aboutTeamNtc"),
             "공고본문": p.get("recuNoticeWebCont"), "기타": p.get("etc")}
    return _job("hyundai", pid, p["recuNoticeNm"], "현대자동차",
                "\n\n".join(f"{k}\n{v}" for k, v in parts.items() if v),
                p["applyEndDt"], p.get("appDispWorkplace") or p.get("workPlaceCodeNm"),
                p.get("channelCodeNm"))


def _hyundai_jobs():
    page, received, total = 1, 0, 1
    while received < total:
        q = urllib.parse.urlencode({"hgrCd": 1, "lang": "ko", "page": page, "pageblock": 100,
                                    "searchFieldList": "", "searchOccupList": "", "searchPlaceList": "",
                                    "searchSectorList": "", "searchText": "", "jdSec": "", "srcOrd": ""})
        data = json.loads(_get(_HYUNDAI + "AP-HM-FO-02700?" + q))["data"]
        total = data["listCnt"]
        if not data["list"] and received < total:
            raise ValueError("현대자동차: 공고 페이지 누락")
        for p in data["list"]:
            yield _hyundai(f"{p['recuYy']}_{p['recuType']}_{p['recuCls']}")
        received += len(data["list"])
        page += 1


def _autoever(pid):
    props = _next_data(_get(job_reference(f"autoever_{pid}")["url"]))
    q = next(q for q in props["dehydratedState"]["queries"]
             if q["queryKey"][:2] == ["career", "getOpeningById"])
    data = q["state"]["data"]["data"]
    p = data["openingsInfo"]
    places = [j["workspacePlace"]["place"] for j in data["jobPositionSetting"]["jobPositions"]
              if j.get("workspacePlace")]
    return _job("autoever", pid, p["title"], "현대오토에버", p["detail"], p.get("dueDate"),
                ", ".join(dict.fromkeys(places)), closed=p["status"] != "OPEN")


def _autoever_jobs():
    props = _next_data(_get("https://career.hyundai-autoever.com/ko/apply"))
    q = next(q for q in props["dehydratedState"]["queries"] if q["queryKey"] == ["openings"])
    for p in q["state"]["data"]:
        yield _autoever(p["openingId"])


def _mobis(pid):
    soup = _soup(_get(job_reference(f"mobis_{pid}")["url"]))
    top, body = soup.select_one(".view-top"), soup.select_one(".view-cont")
    if top is None or body is None:
        raise ValueError(f"현대모비스/{pid}: 공고 본문 없음")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", top.select_one(".date").get_text())
    return _job("mobis", pid, top.select_one("#viewTit").get_text(), "현대모비스", str(body),
                dates[-1], top.select(".view-info02 p")[-1].get_text(strip=True),
                top.select_one(".career").get_text(strip=True))


def load(source: str) -> list[dict]:
    """목록 전체를 읽는다. 한 페이지/본문이라도 실패하면 완료로 취급하지 않는다."""
    if source in ("daangn", "mobis"):
        url, pattern = {
            "daangn": ("https://careers.daangn.com/jobs/", r"/jobs/role/(\d+)/"),
            "mobis": ("https://careers.mobis.com/jobs", r"/jobs-view\?seq=(\d+)"),
        }[source]
        ids = list(dict.fromkeys(m.group(1) for a in _soup(_get(url)).select("a[href]")
                                if (m := re.fullmatch(pattern, a["href"]))))
        if not ids:
            raise ValueError(f"{source}: 목록에서 공고 링크를 찾지 못함")
        return [detail(source, pid) for pid in ids]
    loaders = {"toss": _toss_jobs, "samsung": _samsung_jobs, "lg": _lg_jobs, "sk": _sk_jobs,
               "hyundai": _hyundai_jobs, "autoever": _autoever_jobs}
    return list(loaders[source]())


def detail(source: str, pid: str) -> dict:
    job_reference(f"{source}_{pid}")  # URL에 넣기 전에 출처와 외부 ID 검증
    return {"daangn": _daangn, "toss": _toss, "samsung": _samsung, "sk": _sk,
            "hyundai": _hyundai, "autoever": _autoever, "mobis": _mobis, "lg": _lg}[source](pid)
