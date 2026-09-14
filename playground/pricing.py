"""Model fiyatlandırması + maliyet hesabı (yalnızca Prompt Lab için).

DİKKAT: Bu fiyatlar zamanla değişir. Buradaki değerler tahmini maliyet göstermek
içindir, faturalandırma için DEĞİL. Güncel fiyatı Google'ın resmi sayfasından
doğrula ve gerekiyorsa `PRICING` tablosunu güncelle (1 milyon token başına USD).

Fiyatlar 1M (1.000.000) token başına USD. Gemini görselleri de token olarak
sayar; `usage_metadata.prompt_token_count` görsel + sistem promptu + şema dahil
girdi tokenlarını, `candidates_token_count` çıktı tokenlarını verir.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    #: Girdi (prompt) tokenları — 1M token başına USD.
    input_per_1m: float
    #: Çıktı (üretilen) tokenlar — 1M token başına USD.
    output_per_1m: float
    #: İnsan tarafından okunur not; UI'da fiyatın kaynağını/tarihini gösterir.
    note: str = ""


#: Tahmini fiyatlar. Doğrula: https://ai.google.dev/gemini-api/docs/pricing
#: (Değerler yaklaşıktır; kendi tier'ına göre değişebilir.)
PRICING: dict[str, ModelPricing] = {
    "gemini-2.5-flash": ModelPricing(
        input_per_1m=0.30,
        output_per_1m=2.50,
        note="tahmini — güncel fiyatı doğrula",
    ),
    "gemini-2.5-flash-lite": ModelPricing(
        input_per_1m=0.10,
        output_per_1m=0.40,
        note="tahmini — güncel fiyatı doğrula",
    ),
    "gemini-2.5-pro": ModelPricing(
        input_per_1m=1.25,
        output_per_1m=10.00,
        note="tahmini — güncel fiyatı doğrula; ≤200k token kademesi",
    ),
}

#: Fiyatı bilinmeyen model için varsayılan (0 maliyet göstermemek adına flash).
_FALLBACK = PRICING["gemini-2.5-flash"]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """Girdi/çıktı token sayısından tahmini USD maliyeti hesapla.

    Bilinmeyen model için flash fiyatına düşer ve `is_estimate=True`,
    `model_known=False` işaretler — UI bunu "gerçek fiyat farklı olabilir"
    uyarısıyla gösterebilsin.
    """
    pricing = PRICING.get(model, _FALLBACK)
    input_usd = input_tokens / 1_000_000 * pricing.input_per_1m
    output_usd = output_tokens / 1_000_000 * pricing.output_per_1m
    return {
        "input_usd": round(input_usd, 6),
        "output_usd": round(output_usd, 6),
        "total_usd": round(input_usd + output_usd, 6),
        "currency": "USD",
        "model_known": model in PRICING,
        "input_per_1m": pricing.input_per_1m,
        "output_per_1m": pricing.output_per_1m,
        "note": pricing.note,
    }
