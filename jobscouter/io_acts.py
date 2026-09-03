"""io 큐 activity — 자격증명 없음. 공개 API + git."""
import hashlib
import json
import re
import ssl
import subprocess
import urllib.request
from datetime import date, datetime

from temporalio import activity

from jobscouter.candidates import KST, days_left, dues
from jobscouter.config import (APP_FILES, APPLICATIONS, CHAT_DIR, CHAT_DONE, JOBFEED,
                                PKB_CATEGORIES, PKB_INDEX, PKB_STATUSES, PROPOSALS,
                                RESUME_PROPOSALS, RUBRIC_VERSION, SID_RE, Target, _app_slug,
                                _norm, git_path_at, job_cid, resume_target)
from jobscouter.search import es


# proposals.json에 남기는 필드 — usage·cached는 판정 내부용이라 뺀다. exclude 판정도 남겨야
# 다음 스캔의 load_targets가 같은 공고를 다시 판정하지 않는다(화면에는 api가 걸러 안 보인다)
PROP_FIELDS = ["id", "company", "title", "url", "src", "scores", "total",
               "reason", "quotes", "confidence", "rubric_version", "exclude"]
RESUME_STATE = JOBFEED.parent / "data" / "resume_state.json"   # 데이터 repo 내 — 마지막 반영 PKB 해시
PKB_TEXT_CAP = 40_000   # propose_resume_update 입력용 캡
_ADD_HEADING = "## 미분류 추가(자동 제안 승인)"
# personal-docs/src/pkb/retrieve.py profile_filter("curated") 그대로 재현
_PKB_PROFILE_FILTER = [   # doc_type 제한은 두지 않는다(경력 문서 doc_type이 제각각) — category+status로 범위 지정
    {"terms": {"status": [x.strip() for x in PKB_STATUSES.split(",") if x.strip()]}},
]
# 같은 파일 _lifecycle_filter(include_archived=False) 그대로 재현
_PKB_LIFECYCLE_FILTER = [
    {"bool": {"must_not": {"exists": {"field": "archived_at"}}}},
    {"bool": {"should": [
        {"bool": {"must_not": {"exists": {"field": "expires_at"}}}},
        {"range": {"expires_at": {"gt": "now"}}},
    ], "minimum_should_match": 1}},
]

try:  # python.org 빌드 대비 — fetch_jobs.py와 동일 처리
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None
_HDR = {"User-Agent": "Mozilla/5.0", "wanted-os": "web"}
REQ_CAP = 300  # DESIGN: requirements 300자 캡
POSTING_CAP = 6000  # 지원서류 초안용 공고 전문 캡


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return json.load(r)


def _has_remote(repo: str) -> bool:
    r = subprocess.run(["git", "-C", repo, "remote"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _git_commit(repo: str, message: str) -> bool:
    """커밋되면 True, 스테이지된 변경이 없으면 False. 그 외 실패(index.lock 경합·작성자
    미설정 등)는 RuntimeError — '변경 없음'으로 삼키면 activity 재시도가 안 걸린다."""
    r = subprocess.run(["git", "-C", repo, "commit", "-m", message],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True
    out = r.stdout + r.stderr
    if any(k in out for k in ("nothing to commit", "nothing added to commit",
                              "no changes added to commit")):
        return False
    raise RuntimeError(f"git commit 실패\n{out.strip()[-500:]}")


@activity.defn
def sync_repo() -> str:
    """사이클 시작 시 jobfeed repo를 원격과 동기화(서버 워커 ↔ 작업 머신).
    원격 없으면(맥북 단독 개발) 예외 없이 생략. pull 전 워킹트리가 더러우면(이전
    실행이 fetch 산출물을 커밋 못 하고 끝난 경우) stash 대신 그대로 커밋한다 —
    단순·결정적이고, 남은 흔적은 사람이 히스토리에서 나중에 봐도 된다."""
    repo = str(JOBFEED.parent)
    if not _has_remote(repo):
        return "원격 없음 — 동기화 생략"
    status = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                            capture_output=True, text=True, timeout=30).stdout
    if status.strip():
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        _git_commit(repo, "job-scouter: 미커밋 산출물 정리")
    r = subprocess.run(["git", "-C", repo, "pull", "--ff-only"],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        tail = "\n".join(out.splitlines()[-6:])
        raise RuntimeError(f"git pull exit {r.returncode}\n{tail}")
    return out.splitlines()[-1] if out else "완료"


def _expired(due, today: date) -> bool:
    """'YYYY-MM-DD' 마감이 오늘(KST)보다 이전이면 참. '상시'·없음·못 읽는 값은 거짓."""
    left = days_left(due, today)
    return left is not None and left < 0


@activity.defn
def load_targets() -> list[Target]:
    """jobs.jsonl − (rows ∪ skipped ∪ 🚫회사 ∪ 현 루브릭 판정 완료 ∪ 마감) = 판정할 것 전부.
    proposals.json의 판정(pending·exclude 모두)은 rubric_version이 현 버전일 때만 제외 —
    루브릭을 올리면 옛 판정은 전 건 재판정 대상으로 남는다."""
    cand = json.loads((JOBFEED / "candidates.json").read_text())
    known = {str(r[2]) for r in cand["rows"]} | set(cand["skipped"])
    prop_path = JOBFEED / PROPOSALS
    props = json.loads(prop_path.read_text()) if prop_path.exists() else {}
    known |= {pid for pid, p in props.items() if p.get("rubric_version") == RUBRIC_VERSION}
    today = datetime.now(KST).date()
    bad = {_norm(r[1]) for r in cand["rows"] if r[4] and r[4][0] == "bad"}
    rep = JOBFEED / "기업평판.md"
    if rep.exists():
        for ln in rep.read_text().splitlines():
            if "🚫" in ln and ln.startswith("|") and len(ln.split("|")) > 1:
                bad.add(_norm(ln.split("|")[1].strip()))

    out, seen = [], set()
    for line in (JOBFEED / "jobs.jsonl").read_text().splitlines():
        j = json.loads(line)
        cid = job_cid(j)
        if (cid in known or cid in seen or _norm(j["company"]) in bad
                or _expired(j.get("due"), today)):
            continue
        seen.add(cid)
        out.append(Target(id=cid, company=j["company"], title=j["title"],
                          src=j["src"], url=j["url"]))
    return out


@activity.defn
def fetch_requirements(t: Target) -> str:
    """자격요건 원문. 원티드: detail.requirements / 점핏: qualifications(복수!)+responsibility 첫 2줄.
    점핏 단수 qualification은 조용히 None — '필수요건 없음' 오독 사고 이력(SKILL.md)."""
    if t.src == "wanted":
        d = _get(f"https://www.wanted.co.kr/api/v4/jobs/{t.id}")
        text = (d["job"]["detail"].get("requirements") or "").strip()
    else:
        d = _get(f"https://jumpit-api.saramin.co.kr/api/position/{t.id[1:]}")
        r = d["result"]
        resp = "\n".join((r.get("responsibility") or "").splitlines()[:2])
        text = f"{(r.get('qualifications') or '').strip()}\n[주요업무 발췌] {resp}".strip()
    if not text:
        raise RuntimeError(f"{t.id}: 자격요건 없음 — 공고 내려갔거나 API 변경")
    return text[:REQ_CAP]


@activity.defn
def fetch_posting_full(t: Target) -> str:
    """지원서류 초안용 공고 전문. fetch_requirements(300자 캡)와 달리 소개·주요업무·
    자격요건·우대사항·복지까지 전부 담는다. 캡 6000자."""
    if t.src == "wanted":
        d = _get(f"https://www.wanted.co.kr/api/v4/jobs/{t.id}")
        job = d["job"]
        detail = job.get("detail") or {}
        parts = {
            "포지션": job.get("position", ""),
            "회사": (job.get("company") or {}).get("name", ""),
            "소개": detail.get("intro", ""),
            "주요업무": detail.get("main_tasks", ""),
            "자격요건": detail.get("requirements", ""),
            "우대사항": detail.get("preferred_points", ""),
            "혜택·복지": detail.get("benefits", ""),
        }
    else:
        d = _get(f"https://jumpit-api.saramin.co.kr/api/position/{t.id[1:]}")
        r = d["result"]
        parts = {
            "포지션": r.get("title", ""),
            "회사": r.get("companyName", ""),
            "주요업무": r.get("responsibility", ""),
            "자격요건": r.get("qualifications", ""),
            "우대사항": r.get("preferredRequirements", ""),
        }
    text = "\n\n".join(f"{k}: {v}" for k, v in parts.items() if v)
    if not text:
        raise RuntimeError(f"{t.id}: 공고 전문 없음 — 공고 내려갔거나 API 변경")
    return text[:POSTING_CAP]


def to_row(j: dict) -> list:
    """Judgment → candidates.json 8필드 행. 마감·근무지는 refresh_due.py가 채운다.
    평판 배열 자동 기입은 범위 외 — rep=null + 사유로 두고 사람이 보강한다."""
    cid = j["id"]
    rid = int(cid) if not cid.startswith("j") else cid   # 기존 관례: 원티드 int
    reason = (f"자동판정 rubric {j['rubric_version']} (conf {j['confidence']:.2f}) — "
              f"{j['reason']}")[:200]
    return [j["title"], j["company"], rid, j["scores"], None, reason, [], None]


@activity.defn
def commit_rows(approved: list[dict], dry_run: bool = False) -> str:
    if not approved:
        return "등재 0건"
    vers = {j["rubric_version"] for j in approved}
    if len(vers) != 1:
        # 루브릭이 섞인 배치 거부 — build.py의 배점 검사와 같은 층 (DESIGN)
        raise RuntimeError(f"루브릭 버전 혼재 {vers} — 배치 거부")
    path = JOBFEED / "candidates.json"
    cand = json.loads(path.read_text())
    have = {str(r[2]) for r in cand["rows"]}
    rows = [to_row(j) for j in approved if str(j["id"]) not in have]
    if dry_run:
        return f"dry-run: {len(rows)}건\n" + "\n".join(
            json.dumps(r, ensure_ascii=False) for r in rows)
    cand["rows"].extend(rows)
    path.write_text(json.dumps(cand, ensure_ascii=False, indent=1))
    git = _commit_and_push(["jobfeed/candidates.json"],
                           f"job-scouter: 자동 등재 {len(rows)}건 (rubric {vers.pop()})")
    return f"등재 {len(rows)}건 · git: {git}"


def _commit_and_push(paths: list[str], message: str) -> str:
    """git add한 paths를 커밋(+원격 있으면 push). 변경 없으면 git commit이 자연히
    no-op — 여기서 따로 diff를 재구현하지 않는다. 그 외 commit 실패는 RuntimeError."""
    repo = str(JOBFEED.parent)
    # 데이터 repo의 .gitignore에 걸린 경로(예: new.md)는 git add가 exit 1 — 걸러낸다
    paths = [p for p in paths if subprocess.run(
        ["git", "-C", repo, "check-ignore", "-q", p]).returncode != 0]
    if paths:
        subprocess.run(["git", "-C", repo, "add", "--", *paths], check=True)
    if not _git_commit(repo, message):
        return "변경 없음"
    msg = "커밋됨"
    if _has_remote(repo):
        p = subprocess.run(["git", "-C", repo, "push"], capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"git push 실패\n{p.stdout + p.stderr}")
        msg += " · push됨"
    return msg


@activity.defn
def save_proposals(judged: list[dict]) -> int:
    """judged(exclude 포함)를 proposals.json에 id로 병합 + 이미 등재·거부된 id와
    마감 지난 건(jobs.jsonl due < 오늘 KST) 정리. 같은 커밋에 jobs.jsonl·new.md(fetch
    산출물, 존재하는 것만)도 실어야 다음 사이클의 sync_repo pull이 dirty 파일 충돌 없이
    끝난다. 반환: 화면에 뜨는(비제외) proposals 건수."""
    path = JOBFEED / PROPOSALS
    props = json.loads(path.read_text()) if path.exists() else {}
    for j in judged:
        rec = {k: j[k] for k in PROP_FIELDS}
        rec["judged_at"] = date.today().isoformat()
        props[str(rec["id"])] = rec

    cand = json.loads((JOBFEED / "candidates.json").read_text())
    known = {str(r[2]) for r in cand["rows"]} | set(cand["skipped"])
    due_map, today = dues(), datetime.now(KST).date()
    props = {pid: rec for pid, rec in props.items()
             if pid not in known and not _expired(due_map.get(pid), today)}
    path.write_text(json.dumps(props, ensure_ascii=False, indent=1))

    n = sum(1 for rec in props.values() if not rec.get("exclude"))
    names = [n for n in ("jobs.jsonl", "new.md", PROPOSALS) if (JOBFEED / n).exists()]
    _commit_and_push([f"jobfeed/{n}" for n in names], f"job-scouter: 스캔 — proposals {n}건")
    return n


@activity.defn
def load_proposals(ids: list[str]) -> list[dict]:
    """proposals.json에서 해당 id들의 판정 dict(commit_rows 입력 형식)를 돌려준다."""
    path = JOBFEED / PROPOSALS
    props = json.loads(path.read_text()) if path.exists() else {}
    return [props[str(i)] for i in ids if str(i) in props]


@activity.defn
def listed_target(cid: str) -> dict:
    """등재된 공고 id → Target dict(+판정 scores·reason) — Draft가 초안을 (재)생성할 때.
    회사·제목·점수·사유는 candidates.json 행에서, src·url은 id 관례(j접두=점핏)에서 정한다.
    scores·reason은 draft_application이 약한 축을 보완하는 근거를 앞세우는 데 쓴다."""
    cand = json.loads((JOBFEED / "candidates.json").read_text())
    for r in cand["rows"]:
        if str(r[2]) == cid:
            jumpit = cid.startswith("j")
            return {"id": cid, "company": r[1], "title": r[0],
                    "scores": list(r[3]), "reason": r[5] or "",
                    "src": "jumpit" if jumpit else "wanted",
                    "url": (f"https://jumpit.saramin.co.kr/position/{cid[1:]}" if jumpit
                            else f"https://www.wanted.co.kr/wd/{cid}")}
    raise ValueError(f"candidates.json 등재 행에 {cid} 없음 — 등재된 공고만 초안을 만든다")


@activity.defn
def reject_proposals(rejects: list[dict]) -> int:
    """candidates.json skipped[id] = [company, title, why] 기록 + proposals에서 제거."""
    if not rejects:
        return 0
    path = JOBFEED / PROPOSALS
    props = json.loads(path.read_text()) if path.exists() else {}
    cand_path = JOBFEED / "candidates.json"
    cand = json.loads(cand_path.read_text())
    for r in rejects:
        pid = str(r["id"])
        rec = props.pop(pid, {})
        cand["skipped"][pid] = [rec.get("company", ""), rec.get("title", ""), r["why"]]
    cand_path.write_text(json.dumps(cand, ensure_ascii=False, indent=1))
    path.write_text(json.dumps(props, ensure_ascii=False, indent=1))
    _commit_and_push(["jobfeed/candidates.json", f"jobfeed/{PROPOSALS}"],
                     f"job-scouter: 제외 {len(rejects)}건")
    return len(rejects)


@activity.defn
def write_application(target: dict, files: dict[str, str]) -> str:
    """지원서류 5종(files) + README(공고 링크·파일 목록·체크리스트 스텁)을
    applications/{회사slug}_{공고id}/에 쓴다 — 같은 회사의 다른 공고는 별도 폴더.
    그 폴더가 이미 있으면(사람이 작업 중) 절대 건드리지 않고 `_draft` 접미 폴더에 쓴다.
    `_draft`는 재생성 슬롯 하나다 — 재생성할 때마다 의도적으로 덮어쓴다(이전 재생성본은
    git 이력에 있다). commit+push.

    README 첫 줄의 `공고:` URL이 **후보목록과의 유일한 연결 키**다 — 폴더명은 사람이
    바꿔 두는 일이 잦아 이름으로는 못 잇는다(candidates.job_index 참조)."""
    company = target["company"]
    slug = f"{_app_slug(company)}_{target['id']}"   # 정규식이 경로 문자를 전부 제거 — 탈출 불가
    files = {n: c for n, c in files.items() if n in APP_FILES}  # LLM이 준 파일명은 allowlist만
    if len(files) < len(APP_FILES):
        raise ValueError(f"지원서류 파일 부족: {sorted(files)}")
    folder = APPLICATIONS / slug
    if folder.exists():
        folder = APPLICATIONS / f"{slug}_draft"
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content)
    readme = (
        f"# {company} 지원서류\n\n"
        f"공고: {target['url']}\n"
        f"상태: 초안 (자동 생성 {date.today().isoformat()})\n\n"
        "## 파일\n" + "\n".join(f"- {n}" for n in sorted(files)) +
        "\n\n## 지원 전 체크리스트\n"
        "- [ ] 사실베이스 대조 — 초안의 수치·경력이 사실과 일치하는지 확인\n"
        "- [ ] 회사 리서치 보강(평판·최근 뉴스)\n"
        "- [ ] 최종 검수 후 제출\n"
    )
    (folder / "README.md").write_text(readme)
    rel = folder.relative_to(JOBFEED.parent)
    _commit_and_push([str(rel)], f"job-scouter: {company} 지원서류 초안")
    return str(folder)


@activity.defn
def commit_outputs() -> str:
    """Publish 마지막 — refresh_due 산출물(candidates.json·reports/)을 커밋."""
    names = [n for n in ("candidates.json", "reports") if (JOBFEED / n).exists()]
    if not names:
        return "변경 없음"
    return _commit_and_push([f"jobfeed/{n}" for n in names], "job-scouter: publish 산출물")


@activity.defn
def pkb_snapshot() -> dict:
    """PKB curated 프로필(경력·프로젝트 카테고리만) 스냅샷. 읽기 전용 — PKB 인덱스에
    쓰거나 지우지 않는다. content를 doc_id·chunk_index 순으로 이어 붙여 sha256 해시를
    낸 뒤(전체 기준 — 40k 밖에서 바뀌어도 변화 감지), text는 40k자에서 doc 단위로 잘라
    표기한다. 반환: {hash, text, docs}(docs = ES hit 개수)."""
    cats = [c.strip() for c in PKB_CATEGORIES.split(",") if c.strip()]
    filt = [{"terms": {"category": cats}}, *_PKB_PROFILE_FILTER, *_PKB_LIFECYCLE_FILTER]
    res = es().search(index=PKB_INDEX, size=10_000,
                      query={"bool": {"filter": filt}},
                      sort=[{"doc_id": "asc"}, {"chunk_index": "asc"}],
                      source=["content", "doc_id", "chunk_index"])
    hits = res["hits"]["hits"]
    contents = [h["_source"]["content"] for h in hits]
    full = "\n\n".join(contents)
    digest = hashlib.sha256(full.encode()).hexdigest()

    parts, total = [], 0
    for c in contents:
        if total + len(c) > PKB_TEXT_CAP:
            parts.append("[... 이하 잘림 ...]")
            break
        parts.append(c)
        total += len(c)
    return {"hash": digest, "text": "\n\n".join(parts), "docs": len(hits)}


@activity.defn
def resume_state_hash() -> str:
    """data/resume_state.json에 남은 마지막 반영 PKB 해시. 없으면 빈 문자열."""
    if not RESUME_STATE.exists():
        return ""
    return json.loads(RESUME_STATE.read_text()).get("hash", "")


@activity.defn
def save_resume_proposals(items: list[dict], hash: str) -> int:
    """제안 각각에 id(sha1(target+section+proposed)[:8])를 부여해
    jobfeed/resume_proposals.json + data/resume_state.json에 저장. commit+push."""
    for it in items:
        it["id"] = hashlib.sha1(
            f"{it['target']}{it['section']}{it['proposed']}".encode()).hexdigest()[:8]
    path = JOBFEED / RESUME_PROPOSALS
    path.write_text(json.dumps({"hash": hash, "items": items}, ensure_ascii=False, indent=1))
    RESUME_STATE.parent.mkdir(parents=True, exist_ok=True)
    RESUME_STATE.write_text(json.dumps({"hash": hash}, ensure_ascii=False, indent=1))
    _commit_and_push(
        [f"jobfeed/{RESUME_PROPOSALS}", str(RESUME_STATE.relative_to(JOBFEED.parent))],
        f"resume: 갱신 제안 {len(items)}건")
    return len(items)


@activity.defn
def apply_resume(ids: list[str]) -> str:
    """승인 항목을 사실베이스·이력서.md에 반영. change=current를 proposed로 정확 치환,
    add=대상 파일 끝 `## 미분류 추가(자동 제안 승인)` 절에 append, remove=current 삭제.
    원문 불일치 등 실패 항목은 건너뛰고 보고. 반영분은 proposals에서 제거. commit+push."""
    path = JOBFEED / RESUME_PROPOSALS
    data = json.loads(path.read_text()) if path.exists() else {"hash": "", "items": []}
    items = data.get("items", [])
    by_id = {it["id"]: it for it in items}

    applied, failed = [], []
    for pid in ids:
        it = by_id.get(pid)
        if not it:
            failed.append(f"{pid}: 제안 없음")
            continue
        try:
            target = resume_target(it["target"])
        except ValueError:
            failed.append(f"{pid}: 알 수 없는 대상 {it['target']}")
            continue
        if not target.exists():
            failed.append(f"{pid}: 알 수 없는 대상 {it['target']}")
            continue
        text = target.read_text()
        kind = it["kind"]
        if kind in ("change", "remove") and it["current"] not in text:
            failed.append(f"{pid}: 원문 불일치 — 건너뜀")
            continue
        if kind == "change":
            text = text.replace(it["current"], it["proposed"], 1)
        elif kind == "remove":
            text = text.replace(it["current"], "", 1)
        elif kind == "add":
            if _ADD_HEADING not in text:
                text = text.rstrip("\n") + f"\n\n{_ADD_HEADING}\n\n{it['proposed']}\n"
            else:
                text = text.rstrip("\n") + f"\n\n{it['proposed']}\n"
        else:
            failed.append(f"{pid}: 알 수 없는 kind {kind}")
            continue
        target.write_text(text)
        applied.append(pid)

    remaining = [it for it in items if it["id"] not in applied]
    path.write_text(json.dumps({**data, "items": remaining}, ensure_ascii=False, indent=1))
    paths = [str(p.relative_to(JOBFEED.parent))
             for p in {resume_target("factbase"), resume_target("이력서.md")}] \
        + [f"jobfeed/{RESUME_PROPOSALS}"]
    _commit_and_push(paths, f"resume: 자동 제안 반영 {len(applied)}건")

    msg = f"반영 {len(applied)}건"
    if failed:
        msg += " · 실패: " + "; ".join(failed)
    return msg


_SHA = re.compile(r"[0-9a-f]{7,40}")


@activity.defn
def git_revert(key: str, sha: str) -> str:
    """git show {sha}:{경로} 내용을 파일에 되쓰고 commit+push. 히스토리는 지우지 않으므로
    되돌린 것도 다시 되돌릴 수 있다. sha는 subprocess 인자로 들어가므로 형식 검증 필수."""
    if not _SHA.fullmatch(sha):
        raise ValueError(f"잘못된 sha 형식: {sha}")
    path = resume_target(key)
    rel = str(path.relative_to(JOBFEED.parent))  # 정상 배치에서는 FACTBASE도 이 안쪽 — 밖이면 ValueError
    repo = str(JOBFEED.parent)
    # 이름을 바꾸기 전 커밋은 옛 이름으로만 읽힌다 — 되쓰기·커밋은 현재 이름(rel)으로 한다
    r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{git_path_at(repo, sha, rel)}"],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(f"git show 실패\n{r.stderr}")
    path.write_text(r.stdout)
    return _commit_and_push([rel], f"resume: {rel} → {sha[:7]} 되돌리기")


def _chat_path(sid: str):
    """sid를 검증한 뒤 버퍼 경로로. chat_* activity 4개가 공유 — sid가 경로가 되는 유일한 지점."""
    if not SID_RE.fullmatch(sid):
        raise ValueError(f"잘못된 sid 형식: {sid}")
    return CHAT_DIR / f"{sid}.json"


@activity.defn
def chat_load(sid: str, key: str) -> dict:
    """세션 버퍼를 읽는다. 없으면 key 대상 원문으로 새로 만든다."""
    path = _chat_path(sid)
    if path.exists():
        return json.loads(path.read_text())
    target = resume_target(key)
    if not target.exists():
        raise ValueError(f"알 수 없는 대상: {key}")
    doc = target.read_text()
    session = {
        "sid": sid, "target": key,
        "base_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "base_doc": doc, "doc": doc, "turns": [],
        "created": date.today().isoformat(),
    }
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, ensure_ascii=False, indent=1))
    return session


@activity.defn
def chat_append(sid: str, message: str, out: dict) -> dict:
    """LLM 출력(out={"reply","edits"})을 버퍼 doc에 적용하고 turns에 쌓는다. 갱신된 세션 반환.
    current가 문서에 정확히 한 번 나올 때만 치환 — 빈 인용·원문 불일치·중복 인용은
    건너뛰고 skipped에 사유를 남긴다(str.replace를 무조건 쓰면 엉뚱한 곳을 고친다)."""
    path = _chat_path(sid)
    s = json.loads(path.read_text())
    doc = s["doc"]
    applied, skipped = 0, []
    for e in out["edits"]:
        current, proposed, why = e["current"], e["proposed"], e["why"]
        n = doc.count(current)
        if not current:
            skipped.append(f"빈 인용 — 건너뜀: {why}")
        elif n == 0:
            skipped.append(f"원문 불일치 — 건너뜀: {current[:40]}…")
        elif n > 1:
            skipped.append(f"인용이 {n}곳에 중복 — 건너뜀: {current[:40]}…")
        else:
            doc = doc.replace(current, proposed, 1)
            applied += 1
    s["doc"] = doc
    s["turns"].append({"role": "user", "text": message})
    s["turns"].append({"role": "assistant", "text": out["reply"],
                        "applied": applied, "skipped": skipped})
    path.write_text(json.dumps(s, ensure_ascii=False, indent=1))
    return s


@activity.defn
def chat_save(sid: str) -> str:
    """base_sha256이 현재 파일 해시와 같을 때만 doc를 쓰고 commit+push. 버퍼는 done/으로."""
    path = _chat_path(sid)
    s = json.loads(path.read_text())
    target = resume_target(s["target"])
    if hashlib.sha256(target.read_bytes()).hexdigest() != s["base_sha256"]:
        raise RuntimeError("대상 파일이 세션 시작 후 바뀌었습니다 — 저장 취소")
    target.write_text(s["doc"])
    rel = str(target.relative_to(JOBFEED.parent))
    msg = _commit_and_push([rel], f"resume: {rel} 채팅 수정 {len(s['turns']) // 2}턴")
    CHAT_DONE.mkdir(parents=True, exist_ok=True)
    path.rename(CHAT_DONE / f"{sid}.json")
    return msg


@activity.defn
def chat_discard(sid: str) -> str:
    """버퍼 삭제. 커밋 없음."""
    _chat_path(sid).unlink(missing_ok=True)
    return "버림"


@activity.defn
def reindex_facts() -> str:
    """사실베이스 반영 후 jobscout_facts 재색인 — ApplyResume 마지막 단계."""
    from scripts.index_es import index_facts
    n = index_facts(es())
    return f"jobscout_facts: {n}건"
