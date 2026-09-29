"""원티드 받은 제안. 수신 이력은 공고의 등재·제외 여부와 별도로 보존한다."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

SOURCE_URL = "https://www.wanted.co.kr/status/proposal?kind=OFFER"
FILENAME = "wanted_offers.json"


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^\d+$")
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    job_id: str = Field(default="", pattern=r"^\d*$")
    company_id: str = Field(default="", pattern=r"^\d*$")
    received_at: str = Field(default="", max_length=100)
    status: str = Field(default="", max_length=100)
    status_code: str = Field(default="", max_length=50)
    status_at: str = Field(default="", max_length=100)
    expires_at: str = Field(default="", max_length=100)
    offer_type: str = Field(default="", max_length=50)
    offer_mode: str = Field(default="", max_length=50)
    message: str = Field(default="", max_length=50000)


def load(jobfeed: Path) -> dict:
    path = jobfeed / FILENAME
    return json.loads(path.read_text()) if path.exists() else {"collected_at": "", "items": []}


def merge(jobfeed: Path, items: list[dict], collected_at: str) -> dict:
    """전체 입력 검증 후 ID로 갱신. 목록에서 사라진 제안과 별도 조사 문서는 지우지 않는다."""
    incoming = [Offer.model_validate(item).model_dump() for item in items]
    if len({item["id"] for item in incoming}) != len(incoming):
        raise ValueError("원티드 제안 ID 중복")
    data = load(jobfeed)
    merged = {item["id"]: item for item in data["items"]}
    for item in incoming:
        merged[item["id"]] = {**merged.get(item["id"], {}), **item}
    data = {"collected_at": collected_at, "items": list(merged.values())}
    path = jobfeed / FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    tmp.replace(path)
    return data
