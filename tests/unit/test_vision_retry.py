"""`GeminiProvider`'ın geçici hata yeniden deneme (retry) davranışı.

Gerçek Gemini SDK'sına ağ çağrısı yapılmaz: `_client.models.generate_content`
sahte bir nesneyle değiştirilir. Amaç, 503/429 gibi GEÇİCİ hatalarda üssel
backoff'la yeniden denendiğini, kalıcı hatalarda (400) ise anında düşüldüğünü
doğrulamak. `time.sleep` yamalanır — testler backoff süresi kadar beklemez.
"""

from __future__ import annotations

import json

import pytest
from google.genai import errors as genai_errors

from adapters.vision import GeminiProvider, VisionError, _is_transient


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    """`generate_content` çağrıldıkça `_outcomes`'tan sıradakini uygular.

    Öğe bir Exception ise fırlatılır (hata simülasyonu), değilse döndürülür.
    """

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider_with(outcomes: list, monkeypatch, **kwargs) -> GeminiProvider:
    """Sahte SDK istemcisiyle kurulmuş bir provider döndür; sleep'i sıfırla."""
    # Yapıcı gerçek `genai.Client` kurar ama ağ çağrısı yapmaz; sahte anahtar yeter.
    provider = GeminiProvider("fake-key", retry_base_delay_s=0.0, **kwargs)
    fake_models = _FakeModels(outcomes)
    # `_client.models` salt-okunur bir property; nesnenin metodunu yamalıyoruz.
    monkeypatch.setattr(provider._client.models, "generate_content", fake_models.generate_content)
    monkeypatch.setattr("adapters.vision.time.sleep", lambda _s: None)
    return provider, fake_models


def _server_error() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"status": "UNAVAILABLE"}})


def _valid_payload() -> str:
    return json.dumps(
        {
            "products": [
                {
                    "name": "süt",
                    "category": "dairy",
                    "quantity": {"value": 1, "unit": "bottle"},
                    "confidence": {"name": 0.9, "category": 0.95},
                }
            ]
        }
    )


def test_is_transient_classifies_errors():
    assert _is_transient(_server_error()) is True
    assert _is_transient(genai_errors.ClientError(429, {"error": {}})) is True
    assert _is_transient(genai_errors.ClientError(400, {"error": {}})) is False
    assert _is_transient(ValueError("boom")) is False


def test_retries_transient_then_succeeds(monkeypatch):
    """İki 503'ten sonra başarılı yanıt: üçüncü denemede çıkarım tamamlanır."""
    provider, models = _provider_with(
        [_server_error(), _server_error(), _FakeResponse(_valid_payload())],
        monkeypatch,
        max_attempts=3,
    )
    result = provider.extract(b"imgbytes", "image/jpeg")
    assert models.calls == 3
    assert [f.name for f in result.foods] == ["süt"]


def test_gives_up_after_max_attempts(monkeypatch):
    """Tüm denemeler 503 ise VisionError fırlatılır ve tam max_attempts denenir."""
    provider, models = _provider_with(
        [_server_error(), _server_error(), _server_error()],
        monkeypatch,
        max_attempts=3,
    )
    with pytest.raises(VisionError):
        provider.extract(b"imgbytes", "image/jpeg")
    assert models.calls == 3


def test_non_transient_fails_immediately(monkeypatch):
    """400 gibi kalıcı hata yeniden DENENMEZ — tek çağrıdan sonra düşer."""
    provider, models = _provider_with(
        [genai_errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT"}})],
        monkeypatch,
        max_attempts=3,
    )
    with pytest.raises(VisionError):
        provider.extract(b"imgbytes", "image/jpeg")
    assert models.calls == 1
