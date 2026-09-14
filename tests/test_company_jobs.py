import io
import json

import pytest

from jobscouter import company_jobs as C
from jobscouter import pdf
from jobscouter.config import job_cid, job_reference


@pytest.mark.parametrize("src,pid,cid,fragment", [
    ("wanted", 12, "12", "/wd/12"), ("jumpit", 12, "j12", "/position/12"),
    ("daangn", 12, "daangn_12", "/role/12/"), ("toss", 12, "toss_12", "job_id=12"),
    ("samsung", "12_34", "samsung_12_34", "no=12"),
    ("lg", "12_34", "lg_12_34", "id=12"),
    ("sk", "R12", "sk_R12", "/Detail/R12"),
    ("hyundai", "2026_N2_12", "hyundai_2026_N2_12", "recuType=N2&recuCls=12"),
    ("autoever", 12, "autoever_12", "/ko/o/12"), ("mobis", 12, "mobis_12", "seq=12"),
])
def test_source_ids_keep_existing_data_and_do_not_collide(src, pid, cid, fragment):
    assert job_cid({"src": src, "id": pid}) == cid
    assert job_reference(cid)["src"] == src
    assert fragment in job_reference(cid)["url"]


def test_dates_and_invalid_external_ids():
    assert C._date("2026년 09월 12일(토)") == "2026-09-12"
    assert C._date("202609121800") == "2026-09-12"
    assert C._date("2026-09-12T16:00:00Z") == "2026-09-13"
    for cid in ("daangn_../../etc", "unknown_1", "hyundai_1", "samsung_1&no=2", "lg_12", "lg_12_1&x=2"):
        with pytest.raises(ValueError):
            job_reference(cid)


def test_daangn_jsonld_and_list_dedup(monkeypatch):
    data = [{"@type": "Organization"}, {"@type": "JobPosting", "title": "AI Platform",
            "description": "<h3>자격요건</h3><p>Python <b>LLM</b> 경험</p>",
            "hiringOrganization": {"name": "당근"}}]
    monkeypatch.setattr(C, "_get", lambda url: ('<a href="/jobs/role/12/">공고</a>' * 2
                        if url.endswith("/jobs/") else
                        '<script type="application/ld+json">' + json.dumps(data) + '</script>'))
    jobs = C.load("daangn")
    assert len(jobs) == 1 and jobs[0]["id"] == "12"
    assert "Python LLM 경험" in jobs[0]["description"]
    assert jobs[0]["due"] == "상시" and jobs[0]["loc"] == ""


def test_toss_includes_subpositions_once_and_skips_hidden(monkeypatch):
    def posting(pid, hidden=False):
        return {"id": pid, "internal_job_id": 100, "title": "LLM 개발", "location": {"name": "Seoul"},
                "metadata": [{"id": k, "value": v} for k, v in {
                    4169410003: "토스", 4155730003: "# 자격요건\nPython 경험",
                    5038345003: hidden}.items()]}
    monkeypatch.setattr(C, "_get", lambda url: json.dumps({"success": [
        {"jobs": [posting(1), posting(2), posting(3, True)]}, {"jobs": [posting(2)]}]}))
    assert [p["id"] for p in C.load("toss")] == ["1", "2"]


def test_samsung_paginates_and_separates_roles(monkeypatch):
    pages = []
    def get(url, form=None):
        if form:
            page = form["currentPageNo"]
            pages.append(page)
            return f'<input class="divCnt" data-max="2"><a data-value="{page}">공고</a>'
        pid = 1 if "seqno=1" in url else 2
        return json.dumps({"success": True, "data": {
            "result": {"seq": pid, "title": "경력채용", "cmpNameKr": "삼성SDS", "isOpened": 1,
                       "enddate": "202609301700", "qlfctKr": "경력 3년"},
            "addFiles": [{"fileName": "roles.pdf", "filePath": "bbs/123/",
                          "fileOriginalName": "직무소개서.pdf"}],
            "items": [{"seq": n, "titleKr": title, "taskKr": task}
                      for n, title, task in [(10, "백엔드", "Python"), (11, "디자인", "Figma")]]}})
    monkeypatch.setattr(C, "_get", get)
    jobs = C.load("samsung")
    assert pages == [1, 2] and len({j["id"] for j in jobs}) == 4
    assert "Figma" not in jobs[0]["description"]
    assert jobs[0]["url"] == jobs[1]["url"]  # README의 공고 ID로 직무를 구분한다.
    assert jobs[0]["pdfs"][0]["title"] == "직무소개서.pdf"
    assert "sfile=roles.pdf" in jobs[0]["pdfs"][0]["url"]


def test_samsung_pdf_reads_text_and_ocr_pages_and_rejects_external_urls(monkeypatch):
    with pdf.pymupdf.open() as doc:
        doc.new_page().insert_text((30, 30), "Required: Python and SQL experience for AX development.")
        text_only = doc.tobytes()
        doc.new_page()
        data = doc.tobytes()
    def ocr(page, **kwargs):
        assert kwargs["language"] == "kor+eng"
        page.insert_text((30, 30), "Required: PLC and Python for factory automation.")
        return page.get_textpage()
    monkeypatch.setattr(pdf.pymupdf.Page, "get_textpage_ocr", ocr)
    text = pdf.extract(data)
    assert "[PDF 1쪽]" in text and "Python and SQL" in text
    assert "[PDF 2쪽 · OCR 오인식 가능]" in text and "PLC and Python" in text
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(text_only))
    assert "Python and SQL" in C.pdf_text("https://www.samsungcareers.com/download?sfile=roles.pdf")
    with pytest.raises(ValueError, match="공식 첨부 URL"):
        C.pdf_text("http://localhost/private.pdf")


def test_lg_keeps_roles_separate_and_checks_closed_status(monkeypatch):
    notice = {"jobNoticeName": "신입 채용", "companyName": "LG CNS", "recAvail": 1,
              "recEndDate": "2026.09.14 18:00", "qualForAppInfo": "기졸업자 가능"}
    roles = [{"recSectorId": 1, "jobGroupName": "AI", "requiredItem": "RAG 프로젝트",
              "preferredItem": "Kubernetes", "detailContext": "AI 서비스 개발"},
             {"recSectorId": 8, "jobGroupName": "Smart Factory", "requiredItem": "Python"}]
    def get(url, *, json_body):
        if url.endswith("/retrieveJobNoticesList"):
            assert json_body["companyCodeList"] == ["CNS"]
            return json.dumps({"status": "S", "data": {"listCount": 1,
                "jobNoticeList": [{"jobNoticeId": 1002127, "companyCode": "CNS"}]}})
        assert url.endswith("/retrieveJobNoticesDetail") and json_body == {"jobNoticeId": 1002127}
        return json.dumps({"status": "S", "data": {"jobNoticesDetail": {
            "jobNoticesDetail": notice, "recList": roles}}})
    monkeypatch.setattr(C, "_get", get)
    ai, factory = (C.detail("lg", f"1002127_{sector}") for sector in (1, 8))
    assert C.load("lg") == [ai, factory]
    assert ai["url"] == factory["url"] and ai["id"] != factory["id"]
    assert "RAG" in ai["description"] and "RAG" not in factory["description"]
    assert "우대사항\nKubernetes" in ai["description"] and "기졸업자 가능" in ai["description"]
    assert ai["due"] == "2026-09-14" and "18:00" in ai["description"]
    notice["recAvail"] = 0
    assert C.detail("lg", "1002127_1")["due"] == "closed"
    with pytest.raises(ValueError, match="모집 직무 없음"):
        C.detail("lg", "1002127_99")
    monkeypatch.setattr(C, "_get", lambda *a, **k: json.dumps({"status": "S", "data": {
        "listCount": 2, "jobNoticeList": [{"jobNoticeId": 1002127, "companyCode": "CNS"}]}}))
    with pytest.raises(ValueError, match="일부 누락"):
        C.load("lg")


def test_sk_reads_fields_and_image_body(monkeypatch):
    fields = {"회사": "SK", "지원 기간": "2026년 09월 01일~2026년 09월 30일", "지역": "서울"}
    html = '<h2 class="box-title">LLM 개발</h2>' + ''.join(
        f'<div class="box-detail-item"><div class="label">{k}</div><div class="value">{v}</div></div>'
        for k, v in fields.items())
    html += '<div class="detail-content-item"><img src="https://example.com/jd.png"></div>'
    monkeypatch.setattr(C, "_get", lambda url: html)
    monkeypatch.setattr(C, "_ocr", lambda url: "자격요건: Python 기반 LLM 서비스를 운영한 경험")
    job = C.detail("sk", "R1")
    assert "Python" in job["description"] and job["loc"] == "서울"
    assert job["due"] == "2026-09-30"


def test_hyundai_paginates_and_keeps_requirements(monkeypatch):
    pages = []
    def get(url):
        if "02700" in url:
            page = 1 if "page=1&" in url else 2
            pages.append(page)
            return json.dumps({"data": {"listCnt": 2, "list": [
                {"recuYy": "2026", "recuType": "N2", "recuCls": page}]}})
        return json.dumps({"data": {"applyInfo": {"recuNoticeNm": "LLM 개발", "applyEndDt": "20260930",
            "privMustReq": "Python 3년", "prefReq": "LLM 운영", "privJdDtl": "Agent 개발"}}})
    monkeypatch.setattr(C, "_get", get)
    jobs = C.load("hyundai")
    assert pages == [1, 2] and len(jobs) == 2
    assert all(s in jobs[0]["description"] for s in ("지원자격", "Python 3년", "우대사항", "LLM 운영"))


def test_autoever_reads_korean_opening_and_closed_status(monkeypatch):
    data = {"openingsInfo": {"title": "LLM 개발", "detail": "<p>Python 경험</p>", "status": "CLOSED"},
            "jobPositionSetting": {"jobPositions": [{"workspacePlace": {"place": "서울 강남구"}}]}}
    props = {"dehydratedState": {"queries": [
        {"queryKey": ["career", "getOpeningById", {}], "state": {"data": {"data": data}}}]}}
    html = '<script id="__NEXT_DATA__">' + json.dumps({"props": {"pageProps": props}}) + '</script>'
    monkeypatch.setattr(C, "_get", lambda url: html)
    job = C.detail("autoever", "1")
    assert job["due"] == "closed" and job["loc"] == "서울 강남구"


def test_mobis_ignores_related_jobs(monkeypatch):
    html = '''<div class="view-top"><p id="viewTit">LLM 개발</p><p class="date">2026-09-01 - 2026-09-30</p>
      <div class="view-info02"><p>SW</p><p>의왕연구소</p></div><p class="career">경력</p></div>
      <div class="view-cont"><p>지원자격</p><p>Python 경험</p></div><aside>관련 공고: 디자이너 Figma</aside>'''
    monkeypatch.setattr(C, "_get", lambda url: html)
    job = C.detail("mobis", "1")
    assert "Python" in job["description"] and "Figma" not in job["description"]
    assert job["loc"] == "의왕연구소"
