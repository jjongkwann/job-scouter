"""후보목록 파생값·검증·지원서류 폴더 색인. io_acts(쓰기)·api(읽기)가 공유 — 계산은 여기 한 곳."""
import json
import re
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from jobscouter.config import APP_FILES, APPLICATIONS, JOBFEED, _norm, job_cid, settings

KST = ZoneInfo("Asia/Seoul")
MAX = [35, 25, 20, 20]  # 스택/도메인/레벨/역할 배점 상한
PENALTY_MIN = -25  # 5번째(선택) 원소 = 미보유 필수요건 감점. 항목당 -5, 상한 -25
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
REP_MUL = {"good": 1.00, "warn": 0.88, "bad": 0.65, "none": 0.95}
REP_BONUS, REP_CONF = 0.12, 40      # good 보너스는 리뷰수/REP_CONF에 비례(상한 1)
ZONE_ADJ = {0: 8, 1: 3, 2: 0, 3: -12, 4: -45, 9: 0}
REP_LABEL = {"good": "괜찮음", "warn": "주의", "bad": "회피"}
_RAIL = {"✅": "good", "⚠️": "warn", "🚫": "bad"}
# 연결 키는 회사명이 아니라 문서에 적힌 공고 URL — 폴더명은 사람이 영문으로 바꿔 두는 일이 잦다
_JOB_URL = re.compile(r"wanted\.co\.kr/wd/(\d+)|jumpit\.saramin\.co\.kr/position/(\d+)")


def zone(addr: str | None) -> tuple[int, str]:
    """settings()['zones'] 순서대로 첫 매치. 비수도권 시·도를 맨 앞에 두는 건 데이터 쪽 책임."""
    if not addr:
        return (9, "미확인")
    for n, label, pat in settings()["zones"]:
        if re.search(pat, addr):
            return (int(n), label)
    return (9, "미확인")


def due_label(raw: str | None, today: date) -> tuple[str, str]:
    """(표시, css) — 마감이 지난 후보도 목록에 남으므로 대시보드에서 바로 가려낼 수 있게."""
    if not raw or raw == "상시":
        return (raw or "", "")
    try:
        left = (date.fromisoformat(raw[:10]) - today).days
    except ValueError:
        return (raw, "")   # 외부 API가 준 값 — 못 읽으면 그대로 보여준다
    if left < 0:
        return (f"마감 지남 {raw[5:10]}", "gone")
    return (f"D-{left}" if left else "D-day", "u0" if left <= 3 else "u1" if left <= 7 else "")


def cand_due(raw, today: date) -> tuple[str, str]:
    """candidates.json 마감 표기 — None=상시 · 'closed'=마감됨 · 'YYYY-MM-DD'."""
    if raw == "closed":
        return ("마감됨", "gone")
    if not raw:
        return ("상시", "always")
    return due_label(raw, today)


def days_left(raw, today: date) -> int | None:
    if not raw or raw == "closed" or raw == "상시":
        return None
    try:
        return (date.fromisoformat(str(raw)[:10]) - today).days
    except ValueError:
        return None


def validate(rows: list) -> list[str]:
    """build.py check() 그대로 — 배점 상한·중복·필드 수·평판 정합성·마감 형식을 검사한다."""
    errs = []
    ids = Counter(r[2] for r in rows)
    errs += [f"중복 wdId {i}" for i, c in ids.items() if c > 1]
    for r in rows:
        # 8개는 에이전트가 방금 추가한 행(마감·근무지는 refresh_due.py가 채운다), 9개는 채워진 행
        if len(r) not in (8, 9):
            errs.append(f"{r[1]}: 필드 {len(r)}개 (8~9개여야 함)")
            continue
        if len(r[3]) not in (4, 5):
            errs.append(f"{r[1]}: 점수 {len(r[3])}개 (4개 또는 5개[+감점])")
            continue
        for i, (v, m) in enumerate(zip(r[3], MAX)):
            if not 0 <= v <= m:
                errs.append(f"{r[1]}: {['스택','도메인','레벨','역할'][i]} {v} (상한 {m})")
        # 감점은 음수여야 한다. 양수면 총점을 부풀리는 방향이라 축의 의미가 뒤집힌다
        if len(r[3]) == 5 and not PENALTY_MIN <= r[3][4] <= 0:
            errs.append(f"{r[1]}: 감점 {r[3][4]} (범위 {PENALTY_MIN}~0, 항목당 -5)")
        if r[4] and r[4][0] not in ("good", "warn", "bad"):
            errs.append(f"{r[1]}: 평판 판정 '{r[4][0]}' 알 수 없음")
        # 판정을 달았으면 표본 수가 있어야 한다. 추천도의 신뢰도 가중이 리뷰수로 계산되므로
        # null이면 ✅가 보너스를 통째로 잃는다(실측: 베이글랩스가 "✅0건"으로 찍힘).
        # 스킬 규칙상 0~2건은 애초에 "정보 없음"이라 판정을 달면 안 된다.
        if r[4] and not (isinstance(r[4][2], int) and r[4][2] >= 3):
            errs.append(f"{r[1]}: 평판 판정 '{r[4][0]}'인데 리뷰수가 {r[4][2]!r} "
                        f"(3건 이상이어야 판정 가능 — 그 미만은 사유에 적고 평판은 null)")
        if not r[4] and not r[5]:
            errs.append(f"{r[1]}: 평판이 없으면 사유를 적어야 함")
        # 마감: None(상시) / "YYYY-MM-DD" / "closed" 셋 중 하나. refresh_due.py가 채운다
        if r[7] is not None and r[7] != "closed" and not _DATE.fullmatch(str(r[7])):
            errs.append(f"{r[1]}: 마감 '{r[7]}' 형식 이상 (null|YYYY-MM-DD|closed)")
    return errs


def reputation() -> dict[str, str]:
    """기업평판.md 표 → {_norm(회사): good|warn|bad|none}. 판정 열(4번째 셀)의 기호로 읽는다."""
    path = JOBFEED / "기업평판.md"
    if not path.exists():
        return {}
    out = {}
    for ln in path.read_text().splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if not ln.startswith("|") or len(cells) < 5:
            continue
        name = cells[1]
        if not name or name == "회사" or set(name) <= {"-", ":"}:
            continue
        out[_norm(name)] = next((v for k, v in _RAIL.items() if k in cells[4]), "none")
    return out


def dues() -> dict[str, str]:
    """{공고id: 'YYYY-MM-DD'|'상시'} — 마감은 proposals.json에 없고 jobs.jsonl에만 있다."""
    # ponytail: fetch 시점 값 — 조기 마감은 안 잡힌다. 필요하면 refresh_due.py를 proposals까지 확장
    path = JOBFEED / "jobs.jsonl"
    if not path.exists():
        return {}
    rows = (json.loads(ln) for ln in path.read_text().splitlines() if ln.strip())
    return {job_cid(j): (j.get("due") or "상시") for j in rows}


def candidate_rows(today: date | None = None) -> list[dict]:
    """candidates.json 행 → 화면용 dict(추천도·순위·마감·통근·평판).
    순위 #는 내려가지도 기한이 지나지도 않은 공고 전체 기준으로 한 번만 매긴다 — 후보목록과 같은 규칙이다."""
    path = JOBFEED / "candidates.json"
    if not path.exists():
        return []
    today = today or datetime.now(KST).date()
    out = []   # (row, _rec) — _rec은 순위 매기기용 지역 값, JSON에는 반올림한 rec만 실린다
    for r in json.loads(path.read_text())["rows"]:
        cid, total = str(r[2]), sum(r[3])
        addr = r[8] if len(r) > 8 else None   # 근무지는 refresh_due.py가 나중에 붙인다 — 새 행에는 없다
        zn, zlabel = zone(addr)
        rep = r[4]
        k = rep[0] if rep else "none"
        conf = (rep[2] or 0) if rep else 0
        mul = 1.0 + REP_BONUS * min(conf / REP_CONF, 1) if k == "good" else REP_MUL[k]
        due, due_cls = cand_due(r[7], today)
        _rec = total * mul + ZONE_ADJ[zn]
        row = {
            "id": cid, "company": r[1], "title": r[0], "scores": list(r[3]) + [0] * (5 - len(r[3])),
            "total": total, "rep": rep, "rep_key": k, "rep_label": REP_LABEL.get(k, ""),
            "rep_note": r[5] or "", "tags": r[6] or [], "addr": addr or "",
            "zone": zn, "zone_label": zlabel, "due": due, "due_cls": due_cls, "closed": r[7] == "closed",
            "days_left": days_left(r[7], today), "rec": round(_rec), "rank": None,
            "tier": "t1" if total >= 80 else "t2" if total >= 70 else "t3",
            "url": (f"https://jumpit.saramin.co.kr/position/{cid[1:]}" if cid.startswith("j")
                    else f"https://www.wanted.co.kr/wd/{cid}"),
        }
        out.append((row, _rec))
    for i, (row, _) in enumerate(sorted((x for x in out if not x[0]["closed"]
                                 and (x[0]["days_left"] is None or x[0]["days_left"] >= 0)),
                                key=lambda x: -x[1]), 1):
        row["rank"] = i
    return [row for row, _ in out]


def app_folders() -> list[dict]:
    """applications/*/ → [{slug, ids, files, docs, mtime}]. ids는 문서에서 읽은 공고 id."""
    # ponytail: 요청마다 폴더 전체를 다시 읽는다(수십 개 · 수 MB). LAN 1인용이라 캐시 없음 —
    # 느려지면 폴더 mtime을 키로 memoize
    out = []
    if not APPLICATIONS.exists():
        return out
    for d in sorted(APPLICATIONS.iterdir()):
        if not d.is_dir():
            continue
        ids: list[str] = []
        files = sorted(p.name for p in d.glob("*.md"))
        for name in files:
            for wanted, jumpit in _JOB_URL.findall((d / name).read_text(errors="replace")):
                cid = wanted or f"j{jumpit}"
                if cid not in ids:
                    ids.append(cid)
        out.append({"slug": d.name, "ids": ids, "files": files,
                    "docs": [f for f in files if f in APP_FILES],
                    "mtime": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d")})
    return out


def job_index() -> dict[str, dict]:
    """{공고 id: 폴더}. 한 폴더가 공고 여럿을 가리키면 그 전부가 같은 폴더로 온다.
    여러 폴더가 같은 공고를 가리키면 정렬상 앞 폴더가 이긴다 — 원본 `x_222`가 재생성 슬롯
    `x_222_draft`보다 앞이라 화면은 사람이 작업 중인 원본을 가리킨다."""
    out: dict[str, dict] = {}
    for f in app_folders():
        for cid in f["ids"]:
            out.setdefault(cid, f)
    return out
