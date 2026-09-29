import json
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobscouter.application_slides import router


@pytest.fixture
def studio(tmp_path, monkeypatch):
    root = tmp_path / "studio"
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/slides/assets/app.js"></script>')
    (dist / "assets/app.js").write_text("console.log('slides')")
    entries = [{"id": "base", "ids": [], "slideId": "base", "title": "기본 포트폴리오", "pages": 7},
               {"id": "123", "ids": ["123", "remember_456"], "slideId": "job-123",
                "title": "개발자 포트폴리오", "pages": 6, "sourcePptx": "/private/source.pptx", "sha256": "abc"}]
    (root / "manifest.json").write_text(json.dumps(entries))
    monkeypatch.setenv("JOBSCOUTER_APPLICATION_SLIDES", str(root))
    app = FastAPI()
    app.include_router(router)
    return root, entries, TestClient(app)


def test_catalog_and_root_normalization(studio):
    root, entries, client = studio
    data = client.get("/api/application-slides").json()
    assert data["items"] == [
        {**{key: entry[key] for key in ("id", "ids", "title", "pages")},
         "slide_id": entry["slideId"], "url": f'/slides/s/{entry["slideId"]}'} for entry in entries]
    redirect = client.get("/api/application-slides/site", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("/api/application-slides/site/")


@pytest.mark.parametrize("route", ["", "themes", "assets", "s/base", "s/job-123", "s/job-123/presenter"])
def test_direct_navigation(studio, route):
    root, _, client = studio
    url = "/api/application-slides/site/" + route
    response = client.get(url)
    assert response.status_code == 200 and response.text == (root / "dist/index.html").read_text()
    assert response.headers["content-type"].startswith("text/html")
    head = client.head(url)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == response.headers["content-length"]


@pytest.mark.parametrize("suffix", ["js", "css", "woff2", "woff", "otf", "ttf", "svg", "png", "jpg", "ico", "html"])
def test_compiled_assets_get_and_head(studio, suffix):
    root, _, client = studio
    (root / f"dist/assets/file.{suffix}").write_bytes(b"asset")
    url = f"/api/application-slides/site/assets/file.{suffix}"
    assert client.get(url).content == b"asset"
    head = client.head(url)
    assert head.status_code == 200 and head.content == b"" and head.headers["content-length"] == "5"


@pytest.mark.parametrize("path", ["s/unknown", "s/base/other", "themes/unknown", "arbitrary", "assets/missing.js",
                                       "../manifest.json", "/etc/passwd", "assets\\app.js", "assets/.hidden.js",
                                       "manifest.json", "src/main.tsx", "vite.config.ts", "assets/app.js.map"])
def test_no_spa_fallback_or_private_files(studio, path):
    root, _, client = studio
    (root / "dist/assets/.hidden.js").write_text("private")
    (root / "dist/assets/app.js.map").write_text("private")
    assert client.get("/api/application-slides/site/" + quote(path, safe="")).status_code == 404


def test_external_symlink_is_not_served(studio, tmp_path):
    root, _, client = studio
    secret = tmp_path / "secret.js"
    secret.write_text("secret")
    (root / "dist/assets/secret.js").symlink_to(secret)
    assert client.get("/api/application-slides/site/assets/secret.js").status_code == 404
    (root / "dist/index.html").unlink()
    (root / "dist/index.html").symlink_to(secret)
    assert client.get("/api/application-slides").json() == {"items": []}


@pytest.mark.parametrize("path", ["src/main.js", "private/data.html", "config.js", "vite.config.js"])
def test_sources_and_config_accidentally_in_dist_are_not_served(studio, path):
    root, _, client = studio
    target = root / "dist" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("private")
    assert client.get("/api/application-slides/site/" + path).status_code == 404


@pytest.mark.parametrize("slide_id", ["../secret", "with space", "", "x/presenter"])
def test_invalid_slide_ids_fail_manifest_validation(studio, slide_id):
    root, entries, client = studio
    entries[0]["slideId"] = slide_id
    (root / "manifest.json").write_text(json.dumps(entries))
    assert client.get("/api/application-slides").status_code == 500


def test_missing_and_invalid_manifest_or_build(studio):
    root, entries, client = studio
    manifest = root / "manifest.json"
    manifest.unlink()
    assert client.get("/api/application-slides").json() == {"items": []}
    assert client.get("/api/application-slides/site/").status_code == 404
    for invalid in ("{", "{}", '[{"id":"123"}]', json.dumps([entries[0], entries[0]]),
                    json.dumps([entries[0], {**entries[1], "id": entries[0]["id"]}])):
        manifest.write_text(invalid)
        assert client.get("/api/application-slides").status_code == 500
    manifest.write_text(json.dumps(entries))
    (root / "dist/index.html").unlink()
    assert client.get("/api/application-slides").json() == {"items": []}
    assert client.get("/api/application-slides/site/assets/app.js").status_code == 404
