"""`VisionProvider` soyutlaması.

Kod asla doğrudan Gemini SDK'sına bağlanmaz. Başka bir sağlayıcıya geçiş bu
dosyayı değiştirmekle sınırlı kalır — handler'lar ve `core/` açılmaz.

Bu dosyada görsel içeriği, tam LLM yanıtını veya API anahtarını loglamak
yasaktır; sadece metadata (byte sayısı, süre, sonlanma sebebi) loglanır.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from google import genai
from google.genai import types

from core.extraction import PROMPT_VERSION, SYSTEM_PROMPT, build_response_schema, parse_extraction
from core.models import BoundingBox, ExtractedFood, FieldConfidence, Quantity
from core.taxonomy import FoodCategory, PackageState

logger = logging.getLogger(__name__)

#: Yaratıcılık değil tutarlılık isteniyor — aynı fotoğraf her seferinde aynı
#: sınıflandırmayı üretmeli. Düşük sıcaklık doğruluk ölçümünü tekrarlanabilir kılar.
_TEMPERATURE = 0.1
_DEFAULT_TIMEOUT_S = 45


class VisionError(RuntimeError):
    """Sağlayıcıdan kullanılabilir bir çıkarım alınamadı."""


@dataclass(frozen=True)
class VisionResult:
    """Çıkarım + gözleme yazılacak metadata.

    `latency_ms` ve `prompt_version` Observation kaydına gider; model veya prompt
    değiştiğinde doğruluk değişimini ölçebilmenin tek yolu bu.
    """

    foods: list[ExtractedFood] = field(default_factory=list)
    model_id: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0


class VisionProvider(Protocol):
    """Tek yöntem, tek sorumluluk: görsel bytes -> yapılandırılmış gıda listesi."""

    model_id: str

    def extract(self, image_bytes: bytes, mime_type: str) -> VisionResult: ...


class GeminiProvider:
    """Gemini 2.5 Flash uygulaması.

    API anahtarı kurucuya dışarıdan verilir; bu sınıf SSM'i tanımaz. Sır
    çözümlemesi handler'ın işidir. Böylece bu sınıf birim testinde sahte
    anahtarla kurulabilir.
    """

    model_id = "gemini-2.5-flash"

    def __init__(self, api_key: str, *, timeout_s: int = _DEFAULT_TIMEOUT_S) -> None:
        http_options = types.HttpOptions(timeout=timeout_s * 1000)
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=build_response_schema(),
            temperature=_TEMPERATURE,
        )

    def extract(self, image_bytes: bytes, mime_type: str) -> VisionResult:
        started = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.model_id,
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
                config=self._config,
            )
        except Exception as exc:  # noqa: BLE001 — sağlayıcı hatalarını tek yerde yakala
            # Görsel içeriğini veya tam yanıtı loglama, sadece metadata.
            logger.warning(
                json.dumps({"event": "gemini_call_failed", "error_type": type(exc).__name__})
            )
            raise VisionError(f"Gemini çağrısı başarısız: {type(exc).__name__}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise VisionError("Gemini yanıtı JSON olarak ayrıştırılamadı") from exc

        foods = parse_extraction(payload)
        logger.info(
            json.dumps(
                {
                    "event": "extraction_completed",
                    "product_count": len(foods),
                    "latency_ms": latency_ms,
                    "model": self.model_id,
                    "prompt_version": PROMPT_VERSION,
                }
            )
        )
        return VisionResult(
            foods=foods,
            model_id=self.model_id,
            prompt_version=PROMPT_VERSION,
            latency_ms=latency_ms,
        )


#: Stub modunun (VISION_PROVIDER=stub) varsayılan yanıtı. Gemini anahtarı
#: olmadan arayüzü test etmek için, her biri kutulu birkaç örnek ürün döner —
#: böylece "kutuya göre kırpma" akışı yerelde uçtan uca denenebilir. Kutular
#: 0-1000 ölçeğinde, fotoğrafın farklı çeyreklerine yayılmıştır; yüklenen
#: gerçek görselin neresine denk geldikleri önemli değil, amaç mekanizmayı
#: doğrulamak. Gerçek/hizalı kutular yalnızca gerçek Gemini çağrısından gelir.
_STUB_FOODS: list[ExtractedFood] = [
    ExtractedFood(
        name="süt",
        brand="Sütaş",
        raw_label="Sütaş Günlük Süt 1L",
        category=FoodCategory.DAIRY,
        subcategory="milk_fresh",
        package_state=PackageState.UNOPENED,
        quantity=Quantity(value=1, unit="bottle"),
        confidence=FieldConfidence(name=0.92, category=0.96),
        bounding_box=BoundingBox(ymin=120, xmin=60, ymax=640, xmax=340),
    ),
    ExtractedFood(
        name="domates",
        category=FoodCategory.PRODUCE_VEGETABLE,
        subcategory="tomato",
        package_state=PackageState.OPENED,
        quantity=Quantity(value=3, unit="piece"),
        confidence=FieldConfidence(name=0.81, category=0.88),
        bounding_box=BoundingBox(ymin=420, xmin=520, ymax=760, xmax=880),
    ),
    ExtractedFood(
        name="kaşar peyniri",
        brand=None,
        category=FoodCategory.DAIRY,
        subcategory="cheese_hard",
        package_state=PackageState.UNKNOWN,
        quantity=Quantity(value=1, unit="pack"),
        confidence=FieldConfidence(name=0.55, category=0.6),
        bounding_box=BoundingBox(ymin=140, xmin=600, ymax=380, xmax=940),
    ),
]


class StubVisionProvider:
    """Testler ve uçtan uca akışı Gemini'siz denemek için sabit yanıt döner.

    `handlers/extractor.py` bunu `VISION_PROVIDER=stub` ortam değişkeniyle
    devreye alabilir — gerçek bir Gemini anahtarı olmadan uçtan uca akış
    doğrulanabilsin. Açık `foods` verilmezse kutulu `_STUB_FOODS` döner; böylece
    stub modunda arayüz kırpma akışını test edecek veriye sahip olur.
    """

    model_id = "stub-vision-0"

    def __init__(self, foods: list[ExtractedFood] | None = None) -> None:
        self._foods = _STUB_FOODS if foods is None else foods

    def extract(self, image_bytes: bytes, mime_type: str) -> VisionResult:
        return VisionResult(foods=list(self._foods), model_id=self.model_id, latency_ms=0)
