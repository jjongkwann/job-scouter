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
