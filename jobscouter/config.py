"""공유 상수·타입. 머신별 값(서버 주소·데이터 경로)은 .env로 — .env.example 참조."""
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_env = os.environ.get
ROOT = Path(__file__).parent.parent
TEMPORAL = _env("JOBSCOUTER_TEMPORAL", "localhost:7233")
ES_URL = _env("JOBSCOUTER_ES", "http://localhost:9200")
# jobfeed = fetch_jobs.py·refresh_due.py·build.py·candidates.json·jobs.jsonl·기업평판.md가 있는 곳
JOBFEED = Path(_env("JOBSCOUTER_JOBFEED", str(ROOT / "jobfeed")))
# 사실베이스 = 판정 근거가 되는 본인 확인 완료 경력 사실 (개인 문서 — 저장소 밖)
FACTBASE = Path(_env("JOBSCOUTER_FACTBASE", str(JOBFEED.parent / "이력서_사실베이스.md")))
# 루브릭 프롬프트 = 개인 채점 기준 (저장소 밖). prompts/rubric_v1.example.md가 템플릿
PROMPTS = Path(_env("JOBSCOUTER_PROMPTS", str(ROOT / "prompts")))
DATA = ROOT / "data"
# jobfeed 스크립트 인터프리터 — certifi가 있는 파이썬이어야 원티드 API가 붙는다
PY = _env("JOBSCOUTER_PY", sys.executable)
Q_WF, Q_IO, Q_LLM = "jobscout-wf", "jobscout-io", "jobscout-llm"
JUDGE_MODEL = _env("JOBSCOUTER_MODEL", "claude-sonnet-5")
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
JK_MD = JOBFEED.parent / "JK.md"
REFERENCES = JOBFEED.parent / "references"
DRAFTS = JOBFEED.parent / "drafts"
APPLICATIONS = JOBFEED.parent / "applications"
APP_EXAMPLE = _env("JOBSCOUTER_APP_EXAMPLE", "example")   # 형식 앵커 — applications/ 아래 회사 폴더명


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


@dataclass
class ScanParams:
    budget_tokens: int = 2_000_000   # 초과 시 잔여는 미점수 강등
    chunk: int = 8                   # 동시 judge 수 — 청크 사이에서 예산 체크
    max_usd: float = 0.5             # judge 1회 지출 상한 (--max-budget-usd) — 루브릭+사실베이스 ~25k 토큰이라 첫 호출 ~$0.1


@dataclass
class PublishParams:
    ids: list[str] = field(default_factory=list)          # 등재 승인된 proposal id
    rejects: list[dict] = field(default_factory=list)     # [{"id","why"}, ...]


@dataclass
class Target:
    id: str        # 원티드 "365172" | 점핏 "j54800311" — candidates.json 관례
    company: str
    title: str
    src: str       # "wanted" | "jumpit"
    url: str


@dataclass
class JudgeInput:
    target: Target
    requirements: str
    search_context: str = ""   # Phase 3: 판례·평판·사실 발췌
    max_usd: float = 0.5       # 폭주 방지 — 타입으로 강제


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
