"""io 큐 activity — 자격증명 없음. jobfeed 스크립트 subprocess + 공개 API."""
import json
import re
import ssl
import subprocess
import urllib.request
from datetime import date

from temporalio import activity

from jobscouter.config import APPLICATIONS, JOBFEED, PROPOSALS, PY, Target, _norm


SCRIPTS = {"fetch_jobs.py", "refresh_due.py", "build.py"}
# proposals.json에 남기는 필드 — usage·exclude·cached는 판정 내부용이라 뺀다
PROP_FIELDS = ["id", "company", "title", "url", "src", "scores", "total",
               "reason", "quotes", "confidence", "rubric_version"]

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


@activity.defn
def sync_repo() -> str:
    """사이클 시작 시 jobfeed repo를 원격과 동기화(미니 워커 ↔ 맥북).
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
        subprocess.run(["git", "-C", repo, "commit", "-m", "job-scouter: 미커밋 산출물 정리"],
                       capture_output=True, text=True)
    r = subprocess.run(["git", "-C", repo, "pull", "--ff-only"],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        tail = "\n".join(out.splitlines()[-6:])
        raise RuntimeError(f"git pull exit {r.returncode}\n{tail}")
    return out.splitlines()[-1] if out else "완료"


@activity.defn
def run_script(name: str) -> str:
    """jobfeed 스크립트 하나를 돌리고 출력 꼬리를 돌려준다."""
    if name not in SCRIPTS:  # activity 인자가 subprocess 경로로 흘러간다 — allowlist로 차단
        raise ValueError(f"허용되지 않은 스크립트: {name}")
    r = subprocess.run([PY, str(JOBFEED / name)], capture_output=True, text=True,
                       timeout=540, cwd=JOBFEED)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
    if r.returncode != 0:
        raise RuntimeError(f"{name} exit {r.returncode}\n{tail}")
    return tail


@activity.defn
def load_targets() -> list[Target]:
    """jobs.jsonl − (rows ∪ skipped ∪ 🚫회사) = 미점수 전부."""
    cand = json.loads((JOBFEED / "candidates.json").read_text())
    known = {str(r[2]) for r in cand["rows"]} | set(cand["skipped"])
    bad = {_norm(r[1]) for r in cand["rows"] if r[4] and r[4][0] == "bad"}
    rep = JOBFEED / "기업평판.md"
    if rep.exists():
        for ln in rep.read_text().splitlines():
            if "🚫" in ln and ln.startswith("|") and len(ln.split("|")) > 1:
                bad.add(_norm(ln.split("|")[1].strip()))

    out, seen = [], set()
    for line in (JOBFEED / "jobs.jsonl").read_text().splitlines():
        j = json.loads(line)
        cid = str(j["id"]) if j["src"] == "wanted" else f"j{j['id']}"
        if cid in known or cid in seen or _norm(j["company"]) in bad:
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
    repo = str(JOBFEED.parent)
    subprocess.run(["git", "-C", repo, "add", "jobfeed/candidates.json"], check=True)
    r = subprocess.run(["git", "-C", repo, "commit", "-m",
                        f"job-scouter: 자동 등재 {len(rows)}건 (rubric {vers.pop()})"],
                       capture_output=True, text=True)
    msg = f"등재 {len(rows)}건 · git: {'커밋됨' if r.returncode == 0 else r.stdout + r.stderr}"
    if r.returncode == 0 and _has_remote(repo):
        p = subprocess.run(["git", "-C", repo, "push"], capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"git push 실패\n{p.stdout + p.stderr}")
        msg += " · push됨"
    return msg


def _commit_and_push(paths: list[str], message: str) -> str:
    """git add한 paths를 커밋(+원격 있으면 push). 변경 없으면 git commit이 자연히
    no-op — 여기서 따로 diff를 재구현하지 않는다."""
    repo = str(JOBFEED.parent)
    # 데이터 repo의 .gitignore에 걸린 경로(예: new.md)는 git add가 exit 1 — 걸러낸다
    paths = [p for p in paths if subprocess.run(
        ["git", "-C", repo, "check-ignore", "-q", p]).returncode != 0]
    if paths:
        subprocess.run(["git", "-C", repo, "add", "--", *paths], check=True)
    r = subprocess.run(["git", "-C", repo, "commit", "-m", message],
                       capture_output=True, text=True)
    if r.returncode != 0:
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
    """비제외 judged를 proposals.json에 id로 병합 + 이미 등재·거부된 id 정리.
    같은 커밋에 jobs.jsonl·new.md(fetch 산출물, 존재하는 것만)도 실어야 다음
    사이클의 sync_repo pull이 dirty 파일 충돌 없이 끝난다. 반환: 현재 proposals 건수."""
    path = JOBFEED / PROPOSALS
    props = json.loads(path.read_text()) if path.exists() else {}
    for j in judged:
        rec = {k: j[k] for k in PROP_FIELDS}
        rec["judged_at"] = date.today().isoformat()
        props[str(rec["id"])] = rec

    cand = json.loads((JOBFEED / "candidates.json").read_text())
    known = {str(r[2]) for r in cand["rows"]} | set(cand["skipped"])
    props = {pid: rec for pid, rec in props.items() if pid not in known}
    path.write_text(json.dumps(props, ensure_ascii=False, indent=1))

    names = [n for n in ("jobs.jsonl", "new.md", PROPOSALS) if (JOBFEED / n).exists()]
    _commit_and_push([f"jobfeed/{n}" for n in names], f"job-scouter: 스캔 — proposals {len(props)}건")
    return len(props)


@activity.defn
def load_proposals(ids: list[str]) -> list[dict]:
    """proposals.json에서 해당 id들의 판정 dict(commit_rows 입력 형식)를 돌려준다."""
    path = JOBFEED / PROPOSALS
    props = json.loads(path.read_text()) if path.exists() else {}
    return [props[str(i)] for i in ids if str(i) in props]


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


def _app_slug(company: str) -> str:
    """회사명 → 폴더 slug. 영문 소문자·숫자·`_`, 한글은 그대로."""
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "_", company).strip("_")
    return s.lower() or "company"


@activity.defn
def write_application(company: str, files: dict[str, str]) -> str:
    """지원서류 5종(files) + README(파일 목록·체크리스트 스텁)을
    applications/{slug}/에 쓴다. 이미 사람이 작업 중인 폴더는 덮어쓰지 않고
    `_draft` 접미로 비켜 쓴다. commit+push."""
    slug = _app_slug(company)
    folder = APPLICATIONS / slug
    if folder.exists():
        folder = APPLICATIONS / f"{slug}_draft"
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content)
    readme = (
        f"# {company} 지원서류\n\n상태: 초안 (자동 생성 {date.today().isoformat()})\n\n"
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
    """Publish 마지막 — refresh_due·build 산출물(candidates.json·reports/)을 커밋."""
    names = [n for n in ("candidates.json", "reports") if (JOBFEED / n).exists()]
    if not names:
        return "변경 없음"
    return _commit_and_push([f"jobfeed/{n}" for n in names], "job-scouter: publish 산출물")
