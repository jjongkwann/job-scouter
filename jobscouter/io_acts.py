"""io 큐 activity — 자격증명 없음. jobfeed 스크립트 subprocess + 공개 API."""
import json
import re
import ssl
import subprocess
import urllib.request

from temporalio import activity

from jobscouter.config import JOBFEED, PY, Target


SCRIPTS = {"fetch_jobs.py", "refresh_due.py", "build.py"}

try:  # python.org 빌드 대비 — fetch_jobs.py와 동일 처리
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None
_HDR = {"User-Agent": "Mozilla/5.0", "wanted-os": "web"}
REQ_CAP = 300  # DESIGN: requirements 300자 캡


def _norm(s: str) -> str:
    """fetch_jobs.py의 회사명 정규화와 동일해야 제외 집합이 맞는다."""
    s = re.sub(r"\(주\)|주식회사|㈜|Inc\.?|Ltd\.?", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"\s+", "", s).lower()


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return json.load(r)


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
    return f"등재 {len(rows)}건 · git: {'커밋됨' if r.returncode == 0 else r.stdout + r.stderr}"
