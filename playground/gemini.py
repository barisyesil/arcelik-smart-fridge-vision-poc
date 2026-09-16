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

#: `media_resolution`: Gemini'nin görseli işlerken kullandığı token çözünürlüğü.
#: Düşük çözünürlük az token/ucuz ama küçük ve arkadaki ürünleri kaçırabilir ve
#: bounding box'lar kayar; yüksek çözünürlük daha isabetli tanıma + daha hizalı
#: kutu ama daha çok token/maliyet. "default" = SDK varsayılanı (ayar gönderilmez).
#: Lab'ın amacı tam olarak bu takası GERÇEK fotoğrafta ölçmek: aynı görseli
#: farklı çözünürlüklerle çalıştır, "Token" ve "Tahmini maliyet" kartlarını
#: doğruluk/kutu isabetiyle karşılaştır, kazananı üretime taşı.
_MEDIA_RESOLUTIONS = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}


def media_resolution_keys() -> list[str]:
    """UI'ın seçici için kullandığı geçerli anahtarlar ('default' = ayarsız)."""
    return ["default", *_MEDIA_RESOLUTIONS]


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
    media_resolution: str = "default"
    #: Uygulanan düşünme bütçesi: None = model varsayılanı (ayar gönderilmedi),
    #: 0 = düşünme kapalı, >0 = üst sınır token. UI bunu geri gösterir.
    thinking_budget: int | None = None


class PlaygroundGeminiError(RuntimeError):
    """Lab çağrısı başarısız — mesaj UI'da gösterilir (üretimden farklı)."""


def _usage_dict(response: object) -> dict:
    """`usage_metadata`'yı sade bir dict'e indir; alanlar sürüme göre değişebilir.

    ÖNEMLİ: Gemini 2.5 modelleri, görünür JSON çıktısından AYRI olarak gizli
    "düşünme" (thinking) tokenları üretir. Bunlar `candidates_token_count`'ta
    DEĞİL, `thoughts_token_count`'tadır ama `total_token_count`'a dahildir ve
    ÇIKTI fiyatından faturalanır. Bu yüzden `prompt + output != total` görünür;
    aradaki farkın büyük kısmı thoughts'tur. Hepsini ayrı ayrı döndürüyoruz ki
    UI "14k nereye gitti?" sorusunu net gösterebilsin.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {
            "prompt_tokens": 0,
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
        }
    prompt_tokens = getattr(meta, "prompt_token_count", None) or 0
    output_tokens = getattr(meta, "candidates_token_count", None) or 0
    thoughts_tokens = getattr(meta, "thoughts_token_count", None) or 0
    cached_tokens = getattr(meta, "cached_content_token_count", None) or 0
    total = getattr(meta, "total_token_count", None) or (
        prompt_tokens + output_tokens + thoughts_tokens
    )
    return {
        "prompt_tokens": int(prompt_tokens),
        "output_tokens": int(output_tokens),
        "thoughts_tokens": int(thoughts_tokens),
        "cached_tokens": int(cached_tokens),
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
    media_resolution: str = "default",
    thinking_budget: int | None = None,
) -> ExtractRun:
    """Verilen sistem promptuyla tek bir çıkarım çalıştır ve her şeyi döndür.

    `media_resolution`: "default" (SDK varsayılanı, ayar gönderilmez) ya da
    "low"/"medium"/"high". Geçersiz değer "default" gibi ele alınır.

    `thinking_budget`: None = model varsayılanı (thinking_config gönderilmez),
    0 = düşünme KAPALI (2.5-flash/flash-lite destekler; en büyük maliyet kaldıracı
    — bu görev yapılandırılmış çıkarım, çoğu zaman düşünmeye ihtiyaç duymaz),
    >0 = düşünme token üst sınırı.
    """
    schema = build_response_schema()
    client = genai.Client(api_key=api_key)
    resolution_key = media_resolution if media_resolution in _MEDIA_RESOLUTIONS else "default"
    config_kwargs: dict = {
        "system_instruction": system_prompt,
        "response_mime_type": "application/json",
        "response_schema": schema,
        "temperature": temperature,
    }
    if resolution_key != "default":
        config_kwargs["media_resolution"] = _MEDIA_RESOLUTIONS[resolution_key]
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    config = types.GenerateContentConfig(**config_kwargs)

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
        media_resolution=resolution_key,
        thinking_budget=thinking_budget,
    )
