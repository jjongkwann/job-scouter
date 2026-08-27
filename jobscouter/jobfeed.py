"""공고 수집(원티드·점핏)과 마감·근무지 갱신 — io 큐 activity. 자격증명 없음, 공개 API만."""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from temporalio import activity

from jobscouter.config import JOBFEED, _norm, job_cid, settings
from jobscouter.io_acts import _HDR, _SSL  # 순환 import 없음 — io_acts가 jobfeed를 import하지 않는다

_WANTED_SEARCH = "https://www.wanted.co.kr/api/chaos/search/v1/results?"
_JUMPIT_SEARCH = "https://jumpit-api.saramin.co.kr/api/positions?"
_WANTED_JOB = "https://www.wanted.co.kr/api/v4/jobs/{}"
_JUMPIT_JOB = "https://jumpit-api.saramin.co.kr/api/position/{}"


def _get(url: str) -> dict:  # 테스트가 monkeypatch
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return json.load(r)


def _sleep() -> None:  # 원티드 API 예의 — 테스트가 no-op으로
    time.sleep(0.2)


def _wanted(kw: str):
    q = urllib.parse.urlencode({"query": kw, "tab": "position", "limit": 100})
    for p in _get(f"{_WANTED_SEARCH}{q}")["positions"]["data"]:
        yield {
            "src": "wanted", "id": p["id"], "title": p["position"],
            "company": p["company"]["name"], "loc": p["address"].get("location", ""),
            "career": "신입" if p.get("is_newbie") else "경력", "stacks": [],
            "due": (p.get("due_time") or "상시")[:10],
            "url": f"https://www.wanted.co.kr/wd/{p['id']}", "kw": kw,
        }


def _jumpit(kw: str):
    q = urllib.parse.urlencode({"sort": "reg_dt", "page": 1, "keyword": kw})
    for p in _get(f"{_JUMPIT_SEARCH}{q}")["result"]["positions"]:
        yield {
            "src": "jumpit", "id": p["id"], "title": p["title"],
            "company": p["companyName"], "loc": ", ".join(p.get("locations") or []),
            "career": f"{p['minCareer']}~{p['maxCareer']}년" if p.get("maxCareer") else "신입/무관",
            # 점핏은 매칭된 스택을 <span>으로 감싸서 내려줌
            "stacks": [re.sub(r"</?span>", "", s) for s in p.get("techStacks") or []],
            "due": (p.get("closedAt") or "상시")[:10],
            "url": f"https://jumpit.saramin.co.kr/position/{p['id']}", "kw": kw,
        }


def _known() -> tuple[set, set, set]:
    """candidates.json + 기업평판.md 에서 기추적·회피 집합을 만든다.
    new.md 각 줄을 태그해서, /job-scout가 [신규]만 읽으면 되게 한다."""
    tracked, bad, ids = set(), set(), set()
    cj = JOBFEED / "candidates.json"
    if cj.exists():
        for r in json.loads(cj.read_text())["rows"]:
            tracked.add(_norm(r[1]))
            ids.add(str(r[2]))
            if r[4] and r[4][0] == "bad":
                bad.add(_norm(r[1]))
    rep = JOBFEED / "기업평판.md"
    if rep.exists():
        for ln in rep.read_text().splitlines():
            if "🚫" in ln and ln.startswith("|"):
                cells = ln.split("|")
                if len(cells) > 1:
                    bad.add(_norm(cells[1].strip()))
    return tracked, bad, ids


def _tag(job: dict, tracked: set, bad: set, ids: set) -> str:
    cid = job_cid(job)
    n = _norm(job["company"])
    if n in bad:
        return "🚫"
    if cid in ids or n in tracked:
        return "기추적"
    return "신규"


@activity.defn
def fetch_jobs() -> str:
    """원티드+점핏 수집 → jobs.jsonl append, new.md(gitignore) 갱신. 반환: 요약 한 줄."""
    store = JOBFEED / "jobs.jsonl"
    digest = JOBFEED / "new.md"
    seen = ({f"{j['src']}:{j['id']}" for j in map(json.loads, store.read_text().splitlines())}
            if store.exists() else set())
    new: dict[str, dict] = {}
    for kw in settings()["keywords"]:
        for source in (_wanted, _jumpit):
            try:
                for job in source(kw):
                    key = f"{job['src']}:{job['id']}"
                    if key not in seen and key not in new:
                        new[key] = job
            except Exception as e:  # 한 소스가 죽어도 나머지는 수집
                print(f"! {source.__name__}/{kw}: {e}", file=sys.stderr)

    with store.open("a") as f:
        for job in new.values():
            f.write(json.dumps({**job, "found": date.today().isoformat()}, ensure_ascii=False) + "\n")

    if not new:  # 재실행해도 직전 다이제스트를 날리지 않음
        return f"새 공고 없음 (누적 {len(seen)}건)"

    tracked, bad, ids = _known()
    order = {"신규": 0, "기추적": 1, "🚫": 2}
    tagged = [(_tag(j, tracked, bad, ids), j) for j in new.values()]
    n_new = sum(1 for t, _ in tagged if t == "신규")
    lines = [f"# 새 공고 {len(new)}건 — {date.today()} "
             f"(신규 {n_new} · 기추적 {sum(1 for t, _ in tagged if t == '기추적')} · "
             f"🚫 {sum(1 for t, _ in tagged if t == '🚫')})\n",
             "> `[신규]`만 읽으면 됨. `[기추적]`은 candidates.json에 이미 있음(단 다른 포지션일 "
             "수 있어 드롭 않고 태그만). `[🚫]`는 회피 회사.\n"]
    for tag, job in sorted(tagged, key=lambda x: (order[x[0]], x[1]["company"])):
        stacks = f" · `{'`, `'.join(job['stacks'][:6])}`" if job["stacks"] else ""
        lines.append(
            f"- `[{tag}]` **[{job['title']}]({job['url']})** — {job['company']} "
            f"({job['loc']} / {job['career']} / ~{job['due']}) "
            f"[{job['src']}:{job['kw']}]{stacks}"
        )
    digest.write_text("\n".join(lines) + "\n")
    return f"새 공고 {len(new)}건 (신규 {n_new}) → new.md (누적 {len(seen) + len(new)}건)"


def _due(pid) -> tuple:
    """(마감일, 생존 여부, 근무지). id가 "j"로 시작하면 점핏 공고.

    원티드는 status 필드로 생존을 알리지만 점핏은 내려간 공고에 HTTP 400을 준다 —
    네트워크 실패와 구분해서 잡아야 호출자의 "실패 시 값 유지"에 걸려 마감된 공고가
    살아 있는 것처럼 남지 않는다."""
    if str(pid).startswith("j"):
        try:
            res = _get(_JUMPIT_JOB.format(str(pid)[1:]))["result"]
        except urllib.error.HTTPError as e:
            if e.code == 400:  # 내려간 공고
                return None, False, None
            raise
        return ((res.get("closedAt") or "")[:10] or None), True, res.get("location")

    job = _get(_WANTED_JOB.format(pid))["job"]
    addr = job.get("address") or {}
    # full_location이 "서울특별시 종로구 …"로 구까지 준다. location은 "서울"뿐이라 밴딩이 안 됨
    return (job.get("due_time"), job.get("status") == "active",
            addr.get("full_location") or addr.get("location"))


@activity.defn
def refresh_due() -> str:
    """candidates.json 각 행 r[7](마감)·r[8](주소) 갱신·저장. 반환: 요약 한 줄."""
    path = JOBFEED / "candidates.json"
    data = json.loads(path.read_text())
    rows = data["rows"]

    closed, failed = [], []
    for r in rows:
        try:
            due, alive, loc = _due(r[2])
        except Exception as e:  # 네트워크 실패는 값을 지우지 않는다
            failed.append((r[1], str(e)[:40]))
            while len(r) < 9:
                r.append(None)
            continue
        val = (due or None) if alive else "closed"
        while len(r) < 9:
            r.append(None)
        r[7] = val
        # 내려간 공고는 주소를 안 주기도 한다 — 이전 값을 지우지 않는다
        r[8] = loc or r[8]
        if val == "closed":
            closed.append((r[1], r[0]))
        _sleep()

    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    live = sum(1 for r in rows if r[7] != "closed")
    dated = sum(1 for r in rows if r[7] and r[7] != "closed")
    out = f"{len(rows)}건 갱신 — 마감일 있음 {dated} / 상시 {live - dated} / 마감됨 {len(closed)}"
    if failed:
        out += f" · 조회 실패 {len(failed)}건"
    return out
