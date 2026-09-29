"""Read-only access to reviewed application packages listed in the manifest."""
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter

from jobscouter.config import DATA
from jobscouter.application_slides import slide_catalog

router = APIRouter(prefix="/api/application-files")
_BUNDLE = "전체_기본본_공고120세트.zip"
_MEDIA = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}


class _File(BaseModel):
    path: str


class _Entry(BaseModel):
    id: str
    ids: list[str]
    company: str
    title: str
    folder: str
    source_urls: list[str]
    review_notes: str
    limitations: str
    pages: int
    files: list[_File]


def _relative(value: str) -> PurePosixPath:
    if (not value or "\\" in value or "\x00" in value
            or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("Invalid relative path")
    return PurePosixPath(value)


def _existing(root: Path, relative: str) -> Path | None:
    path = root.joinpath(*_relative(relative).parts).resolve()
    if not path.is_relative_to(root):
        return None
    return path if path.is_file() else None


def _catalog() -> tuple[dict, dict[str, Path]]:
    root = Path(os.environ.get("JOBSCOUTER_APPLICATION_PACK", str(DATA / "application-pack-20260929"))).resolve()
    manifest = root / "manifest.json"
    try:
        if not manifest.resolve().is_relative_to(root):
            raise ValueError("Manifest outside package")
        try:
            raw = manifest.read_text(encoding="utf-8")
        except FileNotFoundError:
            raw = "[]"
        entries = TypeAdapter(list[_Entry]).validate_python(json.loads(raw))
        allowed: dict[str, Path] = {}

        def register(relative: str) -> dict | None:
            path = _existing(root, relative)
            if path is None:
                return None
            allowed[relative] = path
            return {"name": PurePosixPath(relative).name,
                    "url": "/api/application-files/files/" + "/".join(quote(p, safe="") for p in relative.split("/")),
                    "size": path.stat().st_size}

        items = []
        for entry in entries:
            folder = _relative(entry.folder)
            _relative(entry.id)
            if "/" in entry.id:
                raise ValueError("Invalid package id")
            if ((entry.id == "base" and folder != PurePosixPath("base"))
                    or (entry.id != "base" and (len(folder.parts) != 2 or folder.parts[0] != "jobs"))):
                raise ValueError("Invalid package folder")
            files = []
            for file in entry.files:
                relative = _relative(file.path)
                kind = {"이력서": "resume", "포트폴리오": "portfolio"}.get(relative.stem.rsplit("_", 1)[-1])
                if relative.parent != folder / "submit" or relative.suffix not in (".pdf", ".pptx") or kind is None:
                    raise ValueError("Invalid submission file")
                item = register(file.path)
                if item:
                    files.append({**item, "format": relative.suffix[1:], "kind": kind})
            bundle_name = "기본_이력서_포트폴리오.zip" if entry.id == "base" else f"지원서류_{entry.id}.zip"
            items.append({**entry.model_dump(exclude={"folder", "files"}), "files": files,
                          "bundle": register(str(folder / bundle_name))})
        return {"items": items, "bundle": register(_BUNDLE) if entries else None,
                "stats": {"jobs": sum(e.id != "base" for e in entries),
                          "postings": len({sid for e in entries if e.id != "base" for sid in e.ids}),
                          "documents": sum(len(item["files"]) for item in items)}}, allowed
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "지원서류 manifest를 읽을 수 없습니다") from exc


@router.get("")
def list_application_files():
    catalog = _catalog()[0]
    slides = {item["id"]: item for item in slide_catalog()["items"]}
    for item in catalog["items"]:
        item["slide"] = slides.get(item["id"])
    return catalog


@router.api_route("/files/{path:path}", methods=["GET", "HEAD"])
def application_file(path: str, download: bool = False):
    try:
        _relative(path)
    except ValueError as exc:
        raise HTTPException(400, "잘못된 경로") from exc
    target = _catalog()[1].get(path)
    if target is None:
        raise HTTPException(404, "지원서류를 찾을 수 없습니다")
    return FileResponse(target, media_type=_MEDIA[PurePosixPath(path).suffix],
                        filename=PurePosixPath(path).name,
                        content_disposition_type="inline" if path.endswith(".pdf") and not download else "attachment")
