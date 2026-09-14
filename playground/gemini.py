"""Prompt Lab için senkron Gemini çağrısı.

`adapters/vision.py`'deki `GeminiProvider`'dan AYRI tutulur çünkü Lab'ın farklı
ihtiyaçları var: (1) sistem promptunu çağrı başına değiştirebilmek, (2) token
kullanımını (`usage_metadata`) ve tam prompt'u geri döndürmek. Üretim
provider'ı bunları yapmaz ve yapmamalı (loglama kısıtları). Yine de ÇIKTI
SÖZLEŞMESİ ortaktır: `core.extraction.build_response_schema` ve
`parse_extraction` birebir kullanılır — Lab'da gördüğün ürün yapısı üretimdekiyle
aynıdır.

Not: Üretimden farklı olarak burada ham JSON yanıtı çağırana döndürülür; bu
BİLİNÇLİ — mühendisin modelin ne ürettiğini görmesi gerekir. Bu kod üretime
gitmez.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from google import genai
from google.genai import types

from core.extraction import build_response_schema, parse_extraction


@dataclass(frozen=True)
class ExtractRun:
    """Tek bir Lab çağrısının tüm gözlemlenebilir çıktısı."""

    products: list[dict]
    raw_response: str
    system_prompt: str
    response_schema: dict
    usage: dict
    model: str
    temperature: float
    latency_ms: int


class PlaygroundGeminiError(RuntimeError):
    """Lab çağrısı başarısız — mesaj UI'da gösterilir (üretimden farklı)."""


def _usage_dict(response: object) -> dict:
    """`usage_metadata`'yı sade bir dict'e indir; alanlar sürüme göre değişebilir."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    prompt_tokens = getattr(meta, "prompt_token_count", None) or 0
    output_tokens = getattr(meta, "candidates_token_count", None) or 0
    total = getattr(meta, "total_token_count", None) or (prompt_tokens + output_tokens)
    return {
        "prompt_tokens": int(prompt_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total),
    }


def run_extraction(
    *,
    api_key: str,
    image_bytes: bytes,
    mime_type: str,
    system_prompt: str,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
) -> ExtractRun:
    """Verilen sistem promptuyla tek bir çıkarım çalıştır ve her şeyi döndür."""
    schema = build_response_schema()
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )

    started = time.monotonic()
    try:
        response = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 — Lab'da hata mesajını yüzeye çıkar
        raise PlaygroundGeminiError(f"{type(exc).__name__}: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    raw = response.text or ""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = {}

    foods = parse_extraction(payload)
    products = [asdict(food) for food in foods]

    return ExtractRun(
        products=products,
        raw_response=raw,
        system_prompt=system_prompt,
        response_schema=schema,
        usage=_usage_dict(response),
        model=model,
        temperature=temperature,
        latency_ms=latency_ms,
    )
