"""Read-only catalog and compiled open-slide site for application portfolios."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, TypeAdapter

from jobscouter.config import DATA

router = APIRouter(prefix="/api/application-slides")
_EXTENSIONS = {".html", ".js", ".css", ".woff2", ".woff", ".otf", ".ttf", ".svg", ".png", ".jpg", ".ico"}
_PRIVATE_PARTS = {"src", "source", "sources", "private", "internal", "config", "configs", "node_modules"}


class _Entry(BaseModel):
    id: str = Field(min_length=1)
    ids: list[str]
    slide_id: str = Field(alias="slideId", pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    pages: int = Field(strict=True, gt=0)


def _file(dist: Path, relative: str) -> Path | None:
    parts = relative.split("/")
    if (not relative or "\\" in relative or "\x00" in relative
            or any(not p or p.startswith(".") or p.lower() in _PRIVATE_PARTS for p in parts)
            or parts[-1].lower() == "config.js" or ".config." in parts[-1].lower()):
        return None
    path = dist.joinpath(*parts).resolve()
    if not path.is_relative_to(dist) or path.suffix not in _EXTENSIONS:
        return None
    return path if path.is_file() else None


def _catalog() -> tuple[Path, list[_Entry]]:
    root = Path(os.environ.get("JOBSCOUTER_APPLICATION_SLIDES", str(DATA / "application-slide-studio"))).resolve()
    dist = root / "dist"
    manifest = root / "manifest.json"
    try:
        if not manifest.resolve().is_relative_to(root):
            raise ValueError("Manifest outside slide workspace")
        try:
            raw = manifest.read_text(encoding="utf-8")
        except FileNotFoundError:
            raw = "[]"
        entries = TypeAdapter(list[_Entry]).validate_python(json.loads(raw))
        if (len({entry.slide_id for entry in entries}) != len(entries)
                or len({entry.id for entry in entries}) != len(entries)):
            raise ValueError("Duplicate catalog id")
        if dist.is_symlink() or _file(dist, "index.html") is None:
            entries = []
        return dist, entries
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "슬라이드 manifest를 읽을 수 없습니다") from exc


@router.get("")
def slide_catalog():
    _, entries = _catalog()
    return {"items": [{**entry.model_dump(), "url": f"/slides/s/{entry.slide_id}"} for entry in entries]}


@router.api_route("/site/{path:path}", methods=["GET", "HEAD"])
def application_slide_site(path: str):
    dist, entries = _catalog()
    if not entries:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    routes = {route for entry in entries for route in (f"s/{entry.slide_id}", f"s/{entry.slide_id}/presenter")}
    target = _file(dist, "index.html" if path in {"", "themes", "assets"} or path in routes else path)
    if target is None:
        raise HTTPException(404, "슬라이드 파일을 찾을 수 없습니다")
    return FileResponse(target)
