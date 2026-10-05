"""Tests for same-origin static serving (m0-service-002 phase 1).

Covers: original content bytes served verbatim under /content/, the
frontend bundle under /client/, the root index (present and explicitly
missing), missing files/directories, path-traversal and symlink-escape
rejection, configurable roots, and existing run-route compatibility.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from living_kanto.api.app import _safe_file, create_app
from tests.helpers import make_run_metadata, make_world_state


def _png_1x1() -> bytes:
    """Build a valid 1x1 RGBA PNG programmatically (no external assets)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = zlib.compress(b"\x00\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


PNG = _png_1x1()
INDEX_HTML = "<html><body>living-kanto</body></html>"
APP_JS = "console.log('living-kanto');\n"
SECRET = "top-secret-content"


@pytest.fixture
def tree(tmp_path):
    """base dir + separate content/client roots + a secret outside both."""
    base = tmp_path / "base"
    content = tmp_path / "content"
    client_root = tmp_path / "client"
    (content / "sprites").mkdir(parents=True)
    (content / "sprites" / "pikachu.png").write_bytes(PNG)
    (content / "maps").mkdir()
    (content / "maps" / "route1.json").write_text('{"name": "route1"}')
    (client_root).mkdir()
    (client_root / "index.html").write_text(INDEX_HTML)
    (client_root / "app.js").write_text(APP_JS)
    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET)
    return base, content, client_root, secret


@pytest.fixture
def client(tree):
    base, content, client_root, _ = tree
    app = create_app(base, content_root=content, client_root=client_root)
    with TestClient(app) as c:
        yield c


def test_content_serves_original_png_bytes_verbatim(client):
    r = client.get("/content/sprites/pikachu.png")
    assert r.status_code == 200, r.text
    assert r.content == PNG
    assert r.headers["content-type"] == "image/png"


def test_content_serves_nested_text_file(client):
    r = client.get("/content/maps/route1.json")
    assert r.status_code == 200
    assert r.text == '{"name": "route1"}'


def test_content_missing_file_is_404(client):
    assert client.get("/content/nope.png").status_code == 404


def test_content_directory_is_not_served(client):
    # A directory inside the root is not a file: 404, no listing.
    assert client.get("/content/sprites").status_code == 404


def test_content_path_traversal_blocked(client, tree):
    _, _, _, secret = tree
    # Encoded traversal must not reach the file outside the root.
    r = client.get("/content/..%2F..%2Fsecret.txt")
    assert r.status_code == 404
    assert SECRET not in r.text
    # Plain traversal (normalized or not) must never leak the secret.
    r2 = client.get("/content/../secret.txt")
    assert r2.status_code in (404, 405)
    assert SECRET not in r2.text


def test_content_symlink_escape_blocked(client, tree):
    _, content, _, secret = tree
    (content / "link.png").symlink_to(secret)
    r = client.get("/content/link.png")
    assert r.status_code == 404
    assert SECRET not in r.text


def test_client_serves_bundle_files(client):
    r = client.get("/client/app.js")
    assert r.status_code == 200
    assert r.text == APP_JS
    r2 = client.get("/client/index.html")
    assert r2.status_code == 200
    assert INDEX_HTML in r2.text


def test_client_missing_file_is_404(client):
    assert client.get("/client/absent.js").status_code == 404


def test_root_serves_index_when_present(client):
    r = client.get("/")
    assert r.status_code == 200
    assert INDEX_HTML in r.text


def test_root_symlink_index_escape_blocked(client, tree):
    """GET / must not serve an index.html symlinked outside client_root."""
    _, _, client_root, secret = tree
    (client_root / "index.html").unlink()
    (client_root / "index.html").symlink_to(secret)
    r = client.get("/")
    assert r.status_code == 404
    assert SECRET not in r.text
    # /client/index.html is already covered by _safe_file; keep it in sync.
    r2 = client.get("/client/index.html")
    assert r2.status_code == 404
    assert SECRET not in r2.text


def test_root_serves_real_index_file(client):
    """GET / still serves a real (non-symlink) index.html with 200."""
    r = client.get("/")
    assert r.status_code == 200
    assert INDEX_HTML in r.text


def test_root_explicit_missing_client(tmp_path):
    base = tmp_path / "base"
    app = create_app(base)  # no client dir anywhere
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 404
        body = r.json()
        assert body["detail"] == "client bundle missing"
        assert str(base / "client" / "index.html") == body["checked"]
        # Static routes stay 404 (not 500) when the root is absent.
        assert c.get("/client/app.js").status_code == 404
        assert c.get("/content/x.png").status_code == 404


def test_default_roots_under_base_dir(tmp_path):
    base = tmp_path / "base"
    (base / "content").mkdir(parents=True)
    (base / "content" / "a.png").write_bytes(PNG)
    (base / "client").mkdir()
    (base / "client" / "index.html").write_text(INDEX_HTML)
    with TestClient(create_app(base)) as c:
        assert c.get("/content/a.png").content == PNG
        assert c.get("/").status_code == 200


def test_run_routes_still_work_alongside_static(client):
    payload = {
        "metadata": make_run_metadata(run_id="test-run-001").to_dict(),
        "state": make_world_state(run_id="test-run-001").to_dict(),
    }
    r = client.post("/runs", json=payload)
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]
    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["metadata"]["run_id"] == run_id


def test_safe_file_helper_rejects_escapes(tree):
    _, content, client_root, secret = tree
    assert _safe_file(content, "sprites/pikachu.png") == (content / "sprites" / "pikachu.png").resolve()
    assert _safe_file(content, "../secret.txt") is None
    assert _safe_file(content, "..%2Fsecret.txt") is None
    assert _safe_file(content, "/etc/passwd") is None
    assert _safe_file(content, "") is None
    assert _safe_file(content, "sprites") is None  # directory, not a file
    assert _safe_file(client_root, "app.js") is not None
