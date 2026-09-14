"""Prompt Lab sunucusu — Gemini'ye çıkmayan uçlar.

`extract` gerçek bir API anahtarı ister; burada test edilmez. Ama meta, prompt
listeleme ve kaydet/sil akışı anahtarsız çalışır ve AI mühendisi ortamının
ayakta olduğunu doğrular.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from playground import prompts as prompts_mod
from playground.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Kayıtlı sürümleri gerçek dosyaya değil, geçici dosyaya yaz.
    monkeypatch.setattr(prompts_mod, "_STORE_PATH", tmp_path / "prompt_versions.json")
    return TestClient(app)


def test_meta_lists_new_units_and_prompt(client):
    body = client.get("/playground/meta").json()
    assert "box" in body["units"]
    assert "bunch" in body["units"]
    assert body["default_prompt_id"].startswith("production-")
    assert any(m["id"] == "gemini-2.5-flash" for m in body["models"])


def test_prompts_include_production_first(client):
    versions = client.get("/playground/prompts").json()["versions"]
    assert versions[0]["is_production"] is True
    assert versions[0]["editable"] is False
    labels = {v["id"] for v in versions}
    assert "exp-strict-count" in labels


def test_save_and_delete_roundtrip(client):
    resp = client.post(
        "/playground/prompts",
        json={"id": "my-test", "label": "Denemem", "system_prompt": "Bir prompt."},
    )
    assert resp.status_code == 200
    assert resp.json()["editable"] is True

    versions = client.get("/playground/prompts").json()["versions"]
    assert any(v["id"] == "my-test" for v in versions)

    assert client.delete("/playground/prompts/my-test").status_code == 200
    versions = client.get("/playground/prompts").json()["versions"]
    assert not any(v["id"] == "my-test" for v in versions)


def test_cannot_overwrite_builtin(client):
    resp = client.post(
        "/playground/prompts",
        json={"id": "exp-minimal", "system_prompt": "hack"},
    )
    assert resp.status_code == 400


def test_extract_without_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    resp = client.post(
        "/playground/extract",
        files={"image": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        data={"prompt_id": "exp-minimal"},
    )
    assert resp.status_code == 503
