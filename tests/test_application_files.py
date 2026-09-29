import json
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobscouter.application_files import router


@pytest.fixture
def pack(tmp_path, monkeypatch):
    root = tmp_path / "pack"
    root.mkdir()
    monkeypatch.setenv("JOBSCOUTER_APPLICATION_PACK", str(root))
    app = FastAPI()
    app.include_router(router)
    entries = []
    for cid, folder, ids in [("base", "base", []), ("123", "jobs/테스트 회사_123", ["123", "remember_456"])]:
        files = []
        for kind in ("이력서", "포트폴리오"):
            for suffix in ("pdf", "pptx"):
                relative = f"{folder}/submit/지원자_{kind}.{suffix}"
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"%PDF-1.7\n0123456789" if suffix == "pdf" else b"pptx")
                files.append({"path": relative, "sha256": "test"})
        entries.append({"id": cid, "ids": ids, "company": "테스트 회사", "title": "AI 개발자",
                        "folder": folder, "source_urls": ["https://example.com/123"],
                        "review_notes": "원문 대조", "limitations": "개인 프로젝트", "pages": 7, "files": files})
        name = "기본_이력서_포트폴리오.zip" if cid == "base" else f"지원서류_{cid}.zip"
        (root / folder / name).write_bytes(b"zip")
    (root / "전체_기본본_공고120세트.zip").write_bytes(b"all-zip")
    (root / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False))
    return root, entries, TestClient(app)


def test_catalog_preserves_grouped_metadata_and_only_existing_files(pack):
    root, entries, client = pack
    (root / entries[1]["files"][0]["path"]).unlink()
    data = client.get("/api/application-files").json()
    assert data["stats"] == {"jobs": 1, "postings": 2, "documents": 7}
    item = data["items"][1]
    for key in ("id", "ids", "company", "title", "source_urls", "review_notes", "limitations", "pages"):
        assert item[key] == entries[1][key]
    assert len(item["files"]) == 3
    assert all(f["size"] > 0 for f in item["files"])
    assert {f["format"] for f in item["files"]} == {"pdf", "pptx"}
    assert {f["kind"] for f in item["files"]} == {"resume", "portfolio"}
    assert "%20" in item["files"][0]["url"]
    assert client.get(item["bundle"]["url"]).content == b"zip"
    bundle = client.get(data["bundle"]["url"])
    assert bundle.content == b"all-zip"
    assert bundle.headers["content-disposition"].startswith("attachment;")
    assert client.get(data["items"][0]["bundle"]["url"]).content == b"zip"


def test_pdf_inline_download_head_and_range(pack):
    _, _, client = pack
    files = client.get("/api/application-files").json()["items"][0]["files"]
    url = files[0]["url"]
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert client.get(url + "?download=true").headers["content-disposition"].startswith("attachment;")
    head = client.head(url)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(files[0]["size"])
    partial = client.get(url, headers={"Range": "bytes=0-4"})
    assert partial.status_code == 206 and partial.content == b"%PDF-"
    assert partial.headers["content-range"].startswith("bytes 0-4/")
    pptx = client.get(files[1]["url"])
    assert pptx.headers["content-disposition"].startswith("attachment;")


def test_catalog_links_a_grouped_package_to_its_canonical_slide(pack, monkeypatch):
    from jobscouter import application_files
    _, _, client = pack
    slide = {"id": "123", "url": "/slides/s/portfolio-123", "pages": 7}
    monkeypatch.setattr(application_files, "slide_catalog", lambda: {"items": [slide]})
    items = client.get("/api/application-files").json()["items"]
    assert items[0]["slide"] is None
    assert items[1]["slide"] == slide
    assert items[1]["ids"] == ["123", "remember_456"]


@pytest.mark.parametrize("relative", ["../secret.pdf", "/etc/passwd", "base\\secret.pdf", "base/../secret.pdf"])
def test_rejects_path_manipulation(pack, relative):
    _, _, client = pack
    response = client.get("/api/application-files/files/" + quote(relative, safe=""))
    assert response.status_code in (400, 404)


def test_unlisted_and_external_symlink_are_not_served(pack, tmp_path):
    root, entries, client = pack
    for relative in ("internal/source.md", "base/preview/x.pdf", "base/submit/unlisted.pdf"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("private")
        assert client.get("/api/application-files/files/" + quote(relative, safe="/")).status_code == 404
    outside = tmp_path / "secret.pdf"
    outside.write_text("outside")
    relative = entries[0]["files"][0]["path"]
    (root / relative).unlink()
    (root / relative).symlink_to(outside)
    assert client.get("/api/application-files/files/" + quote(relative, safe="/")).status_code == 404
    assert client.get("/api/application-files").json()["stats"]["documents"] == 7


def test_missing_manifest_is_empty_but_invalid_manifest_fails(pack):
    root, _, client = pack
    manifest = root / "manifest.json"
    manifest.unlink()
    assert client.get("/api/application-files").json() == {
        "items": [], "bundle": None, "stats": {"jobs": 0, "postings": 0, "documents": 0}}
    for invalid in ("{", "{}", '[{"id":"123"}]'):
        manifest.write_text(invalid)
        assert client.get("/api/application-files").status_code == 500


@pytest.mark.parametrize("relative", ["../secret.pdf", "base/preview/이력서.pdf", "base/submit/source.md"])
def test_manifest_cannot_publish_private_paths(pack, relative):
    root, entries, client = pack
    entries[0]["files"][0]["path"] = relative
    (root / "manifest.json").write_text(json.dumps(entries))
    assert client.get("/api/application-files").status_code == 500


def test_manifest_cannot_use_internal_folder(pack):
    root, entries, client = pack
    entries[1]["folder"] = "internal/private"
    entries[1]["files"] = []
    (root / "manifest.json").write_text(json.dumps(entries))
    assert client.get("/api/application-files").status_code == 500
