"""공유 상수·타입. 머신별 값(서버 주소·데이터 경로)은 .env로 — .env.example 참조."""
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_env = os.environ.get
ROOT = Path(__file__).parent.parent
TEMPORAL = _env("JOBSCOUTER_TEMPORAL", "localhost:7233")
ES_URL = _env("JOBSCOUTER_ES", "http://localhost:9200")
# jobfeed = candidates.json·jobs.jsonl·기업평판.md가 있는 곳
JOBFEED = Path(_env("JOBSCOUTER_JOBFEED", str(ROOT / "jobfeed")))
# 사실베이스 = 판정 근거가 되는 본인 확인 완료 경력 사실 (개인 문서 — 저장소 밖)
FACTBASE = Path(_env("JOBSCOUTER_FACTBASE", str(JOBFEED.parent / "이력서_사실베이스.md")))
# 루브릭 프롬프트 = 개인 채점 기준 (저장소 밖). prompts/rubric_v1.example.md가 템플릿
PROMPTS = Path(_env("JOBSCOUTER_PROMPTS", str(ROOT / "prompts")))
DATA = ROOT / "data"
Q_WF, Q_IO, Q_LLM = "jobscout-wf", "jobscout-io", "jobscout-llm"
Q_CHAT = "jobscout-chat"                       # 판정 레이트리밋과 분리 — 채팅이 판정 뒤에 안 밀리게
JUDGE_MODEL = _env("JOBSCOUTER_MODEL", "gpt-6-astra")
REASONING_EFFORT = _env("JOBSCOUTER_REASONING_EFFORT", "xhigh")
# 루브릭 버전 — judge(캐시 키·판정 기록)와 load_targets(현 버전 판정 완료 건 제외)가 공유.
# 올리면 옛 버전의 pending 판정은 재판정 대상이 된다. exclude 판정은 버전과 무관하게 유지한다 —
# 제외는 늘리는 방향으로만 바뀌어 왔고, 제외건 재판정은 LLM 지출만 낸다
# v2(2026-09-07): 스택 불일치·스킬 대조 불가를 exclude로 — 기준을 루브릭의 언어 이름이 아니라 사실베이스 보유 스킬에서 읽는다
RUBRIC_VERSION = "v2"
PROPOSALS = "proposals.json"   # JOBFEED 아래 — 판정됐지만 등재/거부 전인 후보
RESUME_PROPOSALS = "resume_proposals.json"   # JOBFEED 아래 — ResumeSync 제안, 사람 승인 대기

PKB_INDEX = "pkb_documents"   # 서버 ES — 개인 지식베이스. ResumeSync만 읽는다(쓰기 금지)
# personal-docs/src/pkb/retrieve.py의 profile_filter("curated")는 doc_type이
# concept/guide/moc이고 status가 canonical/active인 문서만 남긴다. 2026-08-25 실측 기준
# 그 조건을 만족하는 카테고리는 전부 "agent"(기술 학습 노트)뿐이라 경력·프로젝트 발췌로는
# 못 쓴다 — 그래서 카테고리를 별도로 좁힌다. 같은 시점 category terms 집계
# (`curl .../pkb_documents/_search -d '{"size":0,"aggs":{"c":{"terms":{"field":"category","size":50}}}}'`)
# 전체 32개 중 경력·프로젝트·자기소개 성격인 career(1956건)·about(129건)·
# "상용 서비스 개발 및 운영"(240건)만 기본값으로 선택 — backend·spring·redis 등
# 나머지는 기술 학습 노트라 이력서 갱신 근거로 부적절해 제외했다. 사용자가 PKB에서
# 이 카테고리 문서를 canonical/active로 승격하면 다음 ResumeSync부터 반영된다.
PKB_CATEGORIES = _env("JOBSCOUTER_PKB_CATEGORIES", "career,about,상용 서비스 개발 및 운영")
# ResumeSync 결과는 사람 승인을 거치므로 PKB의 curated(canonical/active)보다 넓게 읽는다 —
# 2026-08-25 실측: 경력 문서는 전부 evergreen/draft-rewrite/in-progress라 curated만으론 0건
PKB_STATUSES = _env("JOBSCOUTER_PKB_STATUSES", "canonical,active,evergreen,draft-rewrite,in-progress")

# 데이터 repo 레이아웃(JOBFEED.parent가 루트) — 웹앱 열람·지원서류 초안이 쓴다
RESUME = JOBFEED.parent / "이력서.md"
SETTINGS = JOBFEED.parent / "settings.json"   # 개인값(검색어·통근 밴드) — 데이터 repo
COMPANIES = ("daangn", "toss", "samsung", "lg", "sk", "hyundai", "autoever", "mobis")


def settings() -> dict:
    """검색어·통근 밴드·공식 채용 사이트. companies 생략 시 모두 수집한다."""
    try:
        d = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        d = {}
    companies = d.get("companies", list(COMPANIES))
    if not isinstance(companies, list) or any(c not in COMPANIES for c in companies):
        raise ValueError(f"companies는 다음 이름의 배열이어야 합니다: {', '.join(COMPANIES)}")
    return {"keywords": list(d.get("keywords") or []), "zones": list(d.get("zones") or []),
            "companies": list(dict.fromkeys(companies))}


REFERENCES = JOBFEED.parent / "references"
APPLICATIONS = JOBFEED.parent / "applications"
APP_EXAMPLE = _env("JOBSCOUTER_APP_EXAMPLE", "example")   # 형식 앵커 — applications/ 아래 회사 폴더명
CHAT_DIR = JOBFEED.parent / "tmp" / "chat"     # 데이터 repo .gitignore의 tmp/ 아래 — 커밋 안 됨
CHAT_DONE = CHAT_DIR / "done"
SID_RE = re.compile(r"[0-9a-f]{8,32}")


def _norm(s: str) -> str:
    """회사명 정규화 — fetch_jobs.py·io_acts·web이 전부 이 기준으로 맞춰야 제외/매칭 집합이 맞는다."""
    s = re.sub(r"\(주\)|주식회사|㈜|Inc\.?|Ltd\.?", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"\s+", "", s).lower()


def _app_slug(company: str) -> str:
    """회사명 → 폴더 slug. 영문 소문자·숫자·`_`, 한글은 그대로. io_acts·web이 공유(applications/
    폴더명·존재 확인에 같은 기준을 써야 한다)."""
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "_", company).strip("_")
    return s.lower() or "company"


def job_cid(j: dict) -> str:
    """jobs.jsonl 한 줄 → candidates.json 관례 id. io_acts(판정 대상)·web(마감 표시)이 공유."""
    prefix = {"wanted": "", "jumpit": "j"}.get(j["src"], f"{j['src']}_")
    return f"{prefix}{j['id']}"


def job_reference(cid: str) -> dict[str, str]:
    """저장된 ID → 출처·공식 URL. 기존 숫자/점핏 ID는 바꾸지 않는다."""
    cid = str(cid)
    if re.fullmatch(r"\d+", cid):
        return {"src": "wanted", "url": f"https://www.wanted.co.kr/wd/{cid}"}
    if re.fullmatch(r"j\d+", cid):
        return {"src": "jumpit", "url": f"https://jumpit.saramin.co.kr/position/{cid[1:]}"}
    src, _, pid = cid.partition("_")
    patterns = {"daangn": r"\d+", "toss": r"\d+", "samsung": r"\d+_\d+",
                "sk": r"R\d+", "hyundai": r"\d{4}_[A-Za-z0-9]+_\d+",
                "autoever": r"\d+", "mobis": r"\d+", "lg": r"\d+_\d+"}
    if src not in patterns or not re.fullmatch(patterns[src], pid):
        raise ValueError(f"알 수 없는 공고 ID: {cid}")
    urls = {"daangn": f"https://careers.daangn.com/jobs/role/{pid}/",
            "toss": f"https://toss.im/career/job-detail?job_id={pid}",
            "samsung": f"https://www.samsungcareers.com/hr/?no={pid.split('_')[0]}",
            "sk": f"https://www.skcareers.com/Recruit/Detail/{pid}",
            "autoever": f"https://career.hyundai-autoever.com/ko/o/{pid}",
            "mobis": f"https://careers.mobis.com/jobs-view?seq={pid}",
            "lg": f"https://careers.lg.com/apply/detail?id={pid.split('_')[0]}"}
    if src == "hyundai":
        year, kind, number = pid.split("_")
        urls[src] = (f"https://talent.hyundai.com/apply/applyView.hc?recuYy={year}"
                     f"&recuType={kind}&recuCls={number}")
    return {"src": src, "url": urls[src]}


@dataclass
class ScanParams:
    budget_tokens: int = 2_000_000   # 초과 시 잔여는 미점수 강등
    chunk: int = 8                   # 동시 judge 수 — 청크 사이에서 예산 체크
    max_usd: float = 0.5             # 기존 Temporal 입력 재생용 필드. Codex는 사용하지 않는다(USD 상한 미지원).


@dataclass
class PublishParams:
    ids: list[str] = field(default_factory=list)          # 등재 승인된 proposal id
    rejects: list[dict] = field(default_factory=list)     # [{"id","why"}, ...]


@dataclass
class Target:
    id: str        # 원티드 "365172" | 점핏 "j54800311" | 기업 "daangn_7990084003"
    company: str
    title: str
    src: str       # wanted | jumpit | COMPANIES
    url: str


@dataclass
class JudgeInput:
    target: Target
    requirements: str
    search_context: str = ""   # Phase 3: 판례·평판·사실 발췌
    max_usd: float = 0.5       # 기존 Temporal 입력 재생용 필드. Codex는 사용하지 않는다.


@dataclass
class Judgment:
    id: str
    company: str
    title: str
    scores: list[int]          # [스택,도메인,레벨,역할,감점(-25~0)]
    total: int
    exclude: bool
    reason: str
    quotes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    rubric_version: str = ""
    usage: dict = field(default_factory=dict)   # {in,out,cache_read,model,ms}
    cached: bool = False

# 지원서류 5종 — draft_application 출력·write_application allowlist (LLM 출력 파일명을 경로로 쓰지 않는다)
APP_FILES = ["0_JD.md", "1_맞춤_이력서.md", "2_자기소개서.md",
             "3_면접지식맵.md", "4_포트폴리오_구성.md"]

_APP_DOC = re.compile(r"applications/([0-9A-Za-z_가-힣]+)/([^/]+\.md)")


def git_path_at(repo: str, sha: str, rel: str) -> str:
    """`sha` 시점의 `rel` 경로. 이름을 바꾼 파일은 옛 이름으로만 조회되는데,
    커밋을 지정한 git show/log에는 --follow가 듣지 않아 이름 표를 따로 만든다.
    이력 보기(web)와 되돌리기(io)가 같은 규칙을 써야 해서 여기 둔다. 못 찾으면 rel 그대로."""
    r = subprocess.run(
        ["git", "-C", repo, "-c", "core.quotePath=false", "log", "--follow",
         "--format=%x00%h", "--name-only", "--", rel],
        capture_output=True, text=True, timeout=20)
    for chunk in r.stdout.split("\0")[1:]:
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if len(lines) > 1 and (lines[0].startswith(sha) or sha.startswith(lines[0])):
            return lines[1]
    return rel


def resume_target(key: str) -> Path:
    """채팅·되돌리기·apply_resume이 건드릴 수 있는 파일만 절대경로로. 그 밖은 ValueError.
    LLM·브라우저가 준 문자열이 경로가 되는 유일한 지점 — allowlist를 여기 한 곳에 모은다."""
    if key == "factbase":
        return FACTBASE
    if key == "이력서.md":
        return RESUME
    m = _APP_DOC.fullmatch(key)
    if m and m.group(2) in APP_FILES + ["README.md"]:
        return APPLICATIONS / m.group(1) / m.group(2)
    raise ValueError(f"허용되지 않은 이력서 대상: {key}")
