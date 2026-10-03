from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError
from email.utils import formatdate

import pytest

from jobscouter import linkedin


def card(pid, location="Seongnam, Gyeonggi-do, South Korea"):
    return f'''<li><div class="base-search-card job-search-card"
        data-entity-urn="urn:li:jobPosting:{pid}">
        <h3 class="base-search-card__title">Software Engineer, AI Agent</h3>
        <h4 class="base-search-card__subtitle"><a>Sendbird</a></h4>
        <span class="job-search-card__location">{location}</span>
        <time class="job-search-card__listdate" datetime="2026-10-01">1 day ago</time>
        </div></li>'''


DETAIL = '''<section class="top-card-layout">
    <h2 class="top-card-layout__title topcard__title">Software Engineer, AI Agent</h2>
    <div class="topcard__flavor-row"><span class="topcard__flavor">
        <a class="topcard__org-name-link">Sendbird</a></span>
        <span class="topcard__flavor topcard__flavor--bullet">Seoul, Seoul, South Korea</span>
    </div>
    <div class="topcard__flavor-row"><figure class="topcard__flavor--bullet">
        Over 200 applicants</figure></div>
    <div class="description__text description__text--rich">
        <section class="show-more-less-html"><div class="show-more-less-html__markup">
            <strong>You Need To Have<br></strong><ul><li>3+ years of backend experience.</li>
            <li>Strong English proficiency.</li></ul><p>AWS or GCP deployments.</p></div>
            <button>Show more</button></section></div>
    <ul class="description__job-criteria-list"><li>
        <h3 class="description__job-criteria-subheader">Employment type</h3>
        <span class="description__job-criteria-text">Full-time</span></li></ul>
    </section>'''


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(linkedin.time, "sleep", lambda n: None)
    monkeypatch.setattr(linkedin, "_blocked_until", 0.0)
    monkeypatch.setattr(linkedin, "_rate_limit_error", None)


def test_search_paginates_by_card_count_deduplicates_and_preserves_regions(monkeypatch):
    calls = []
    pages = {0: card(1) + card(2), 2: card(2) + card(3, "Seoul, South Korea"),
             4: "<!DOCTYPE html>\n<!---->\n"}

    def get(url):
        query = parse_qs(urlsplit(url).query)
        calls.append(query)
        return pages[int(query["start"][0])]

    monkeypatch.setattr(linkedin, "_get", get)
    rows = list(linkedin.search("AI Agent"))
    assert [row["id"] for row in rows] == ["1", "2", "3"]
    assert [q["start"] for q in calls] == [["0"], ["2"], ["4"]]
    assert all(q["f_TPR"] == ["r604800"] and q["sortBy"] == ["DD"]
               and q["location"] == ["South Korea"] and q["keywords"] == ["AI Agent"] for q in calls)
    assert rows[0]["loc"] == "성남, 경기, 대한민국"
    assert rows[0]["source_location"] == "Seongnam, Gyeonggi-do, South Korea"
    assert rows[0]["url"] == "https://www.linkedin.com/jobs/view/1/"
    assert rows[0]["career"] == "미확인" and rows[0]["due"] == "상시"
    assert rows[0]["posted_at"] == "2026-10-01" and rows[2]["loc"] == "서울, 대한민국"


def test_detail_preserves_requirements_and_detects_explicit_closed_status(monkeypatch):
    monkeypatch.setattr(linkedin, "_get", lambda url: DETAIL)
    row = linkedin.detail("4368419822")
    assert row["title"] == "Software Engineer, AI Agent" and row["company"] == "Sendbird"
    assert row["loc"] == "서울, 서울, 대한민국" and row["due"] == "상시"
    assert row["source_location"] == "Seoul, Seoul, South Korea"
    assert all(text in row["description"] for text in
               ["3+ years", "Strong English", "AWS or GCP", "Employment type", "Full-time"])
    assert "Show more" not in row["description"] and "200 applicants" not in row["loc"]
    monkeypatch.setattr(linkedin, "_get", lambda url: DETAIL +
                        '<span class="closed-job__flavor">No longer accepting applications</span>')
    assert linkedin.detail("4368419822")["due"] == "closed"


@pytest.mark.parametrize("html", ['<html><h1>Sign in to LinkedIn</h1></html>',
                                  '<ul><li>Unexpected response</li></ul>',
                                  card("not-numeric"), card(1).replace("Sendbird", "")])
def test_unknown_or_malformed_search_is_an_error(monkeypatch, html):
    monkeypatch.setattr(linkedin, "_get", lambda url: html)
    with pytest.raises(ValueError, match="LinkedIn"):
        list(linkedin.search("Python"))


def test_repeated_page_is_an_error(monkeypatch):
    monkeypatch.setattr(linkedin, "_get", lambda url: card(1))
    with pytest.raises(ValueError, match="페이지 반복"):
        list(linkedin.search("Python"))


@pytest.mark.parametrize("html", ['<h1>Sign in</h1>', DETAIL.replace('class="description__text description__text--rich"',
                        'class="missing"') + '<span class="closed-job__flavor">No longer accepting applications</span>'])
def test_missing_detail_is_not_reported_as_closed(monkeypatch, html):
    monkeypatch.setattr(linkedin, "_get", lambda url: html)
    with pytest.raises(ValueError, match="LinkedIn"):
        linkedin.detail("12")


def test_invalid_id_is_rejected_before_network_and_http_failures_propagate(monkeypatch):
    def fail(url):
        raise HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(linkedin, "_get", fail)
    with pytest.raises(ValueError, match="공고 ID"):
        linkedin.detail("12/evil")
    with pytest.raises(HTTPError, match="429"):
        linkedin.detail("12")
    with pytest.raises(HTTPError, match="429"):
        list(linkedin.search("Python"))


def test_search_and_detail_share_request_pacing(monkeypatch):
    clock, requests = [100.0], []
    monkeypatch.setattr(linkedin, "_last_request", 0.0)
    monkeypatch.setattr(linkedin.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(linkedin.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))

    def get(url):
        requests.append(clock[0])
        if "/jobPosting/" in url:
            return DETAIL
        return card(1) if "start=0&" in url else ""

    monkeypatch.setattr(linkedin, "_get", get)
    search = linkedin.search("Python")
    assert next(search)["id"] == "1"
    linkedin.detail("1")
    assert list(search) == []
    assert requests == [100.0, 102.0, 104.0]


@pytest.mark.parametrize(("source", "normalized"), [
    ("Gangnam-gu, Seoul, South Korea", "강남구, 서울, 대한민국"),
    ("Seongnam-si, Gyeonggi-do, South Korea", "성남시, 경기, 대한민국"),
    ("Gwangju, Gyeonggi, South Korea", "광주시, 경기, 대한민국"),
    ("Gwangju, South Korea", "광주광역시, 대한민국"),
])
def test_regions_preserve_district_and_disambiguate_gwangju(source, normalized):
    assert linkedin._location(source) == normalized


@pytest.mark.parametrize(("limit", "second_page", "ids"), [
    (4, card(2) + card(3), ["1", "2", "3"]),
    (3, card(3) + card(4), ["1", "2", "3"]),
])
def test_official_search_limit_preserves_partial_rows_and_never_requests_beyond_cap(
        monkeypatch, limit, second_page, ids):
    calls, rows = [], []
    monkeypatch.setattr(linkedin, "MAX_SEARCH_RESULTS", limit)

    def get(url):
        start = int(parse_qs(urlsplit(url).query)["start"][0])
        calls.append(start)
        assert start < limit
        return card(1) + card(2) if start == 0 else second_page

    monkeypatch.setattr(linkedin, "_get", get)
    with pytest.raises(linkedin.SearchLimitReached) as error:
        for row in linkedin.search("LLM"):
            rows.append(row)
    assert [row["id"] for row in rows] == ids
    assert calls == [0, 2]
    assert error.value.count == len(ids) and error.value.limit == limit
    assert str(len(ids)) in str(error.value) and str(limit) in str(error.value)


@pytest.mark.parametrize("retry_after", ["60", formatdate(1_800_000_060, usegmt=True), None, "invalid"])
def test_429_cooldown_blocks_search_and_detail_until_retry_time(monkeypatch, retry_after):
    clock, calls = [100.0], []
    monkeypatch.setattr(linkedin, "_last_request", 0.0)
    monkeypatch.setattr(linkedin.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(linkedin.time, "time", lambda: 1_800_000_000)
    cooldown = 60 if retry_after and retry_after != "invalid" else 3600
    error = HTTPError("https://www.linkedin.com/jobs", 429, "Too Many Requests",
                      {"Retry-After": retry_after} if retry_after else {}, None)

    def get(url):
        calls.append(url)
        if len(calls) == 1:
            raise error
        return DETAIL

    monkeypatch.setattr(linkedin, "_get", get)
    with pytest.raises(HTTPError) as first:
        list(linkedin.search("LLM"))
    assert first.value is error
    clock[0] += cooldown - 1
    with pytest.raises(HTTPError) as detail_error:
        linkedin.detail("12")
    with pytest.raises(HTTPError) as search_error:
        list(linkedin.search("Python"))
    assert detail_error.value is error and search_error.value is error
    assert len(calls) == 1
    clock[0] += 1
    assert linkedin.detail("12")["company"] == "Sendbird"
    assert len(calls) == 2


def test_503_does_not_activate_linkedin_cooldown(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        raise HTTPError(url, 503, "Unavailable", {"Retry-After": "3600"}, None)

    monkeypatch.setattr(linkedin, "_get", get)
    for _ in range(2):
        with pytest.raises(HTTPError, match="503"):
            linkedin.detail("12")
    assert len(calls) == 2 and linkedin._rate_limit_error is None
