"""Tazelik tahmini.

LLM'e asla tarih sorulmaz. Tarih burada hesaplanır:

    estimated_freshness_date = fotoğraf_tarihi + raf_ömrü(kategori, alt_kategori, ambalaj)

Bu dosya saf Python'dur; AWS, ağ veya "şu an" kavramı yoktur. Gözlem zamanı her
zaman dışarıdan verilir — böylece test edilebilir ve saat dilimi hatası sisteme
sızmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from core.models import FreshnessBasis
from core.taxonomy import FoodCategory, PackageState

_DATA_PATH = Path(__file__).with_name("shelf_life.json")


class ShelfLifeDataError(RuntimeError):
    """shelf_life.json bozuk veya eksik."""


@dataclass(frozen=True)
class FreshnessEstimate:
    estimated_freshness_date: date
    shelf_life_days: int
    basis: FreshnessBasis
    #: "subcategory" | "category" | "global_default" | "user".
    #: "Tahminlerin %X'i global_default'a düştü" metriği buradan çıkar —
    #: tablonun nerede zayıf olduğunu gösterir.
    resolved_from: str
    #: Kullanılan gün sayısının kaynağı (örn. "USDA_FOODKEEPER_2025" | "lit.").
    source: str | None = None
    #: docs/kaynaklar/shelf-life-rules.v1.json içindeki ilgili kural (varsa).
    rule_id: str | None = None

    @property
    def warning(self) -> str | None:
        """Tablo bu ürünü tanımadıysa gözleme not düşülecek uyarı."""
        if self.resolved_from == "global_default":
            return "shelf_life_fallback:global_default"
        return None


@lru_cache(maxsize=1)
def _load_data() -> dict:
    try:
        with _DATA_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ShelfLifeDataError(f"shelf_life.json okunamadı: {exc}") from exc
    if "categories" not in data or "global_default" not in data:
        raise ShelfLifeDataError("shelf_life.json beklenen anahtarları taşımıyor")
    return data


def _pick(entry: dict, package_state: PackageState) -> tuple[int, str | None, str | None]:
    """(gün, kaynak, rule_id) — ambalaj durumuna göre doğru state'i seç.

    Kaynak tablonun çoğu kalemi kapalı üründe ambalaj tarihini esas alır; oradaki
    sayı sadece açıldıktan sonrası içindir. Ambalaj tarihi hiç okunmadığı için
    `unopened_days` muhafazakâr bir tahmin olabilir, `opened_days` ise kaynak
    tablodan gelir — bu yüzden `unopened_source`/`opened_source` ayrı tutulur.

    `unknown` gelirse `opened_days` (kısa olan) alınır: fazla iyimser tahmin
    bozulmuş gıdayı taze gösterir, fazla kötümser tahmin sadece erken uyarı
    üretir — yanılmanın maliyeti simetrik değil.
    """
    if package_state is PackageState.UNOPENED:
        return entry["unopened_days"], entry.get("unopened_source"), entry.get("rule_id")
    return entry["opened_days"], entry.get("opened_source"), entry.get("rule_id")


def shelf_life_days(
    category: FoodCategory,
    subcategory: str | None = None,
    package_state: PackageState = PackageState.UNKNOWN,
) -> tuple[int, str, str | None, str | None]:
    """(gün, hangi seviyeden çözüldü, kaynak, rule_id).

    Çözümleme sırası: alt kategori -> kategori -> global default.
    """
    data = _load_data()
    cat_entry = data["categories"].get(category.value)

    if cat_entry is not None:
        if subcategory:
            sub_entry = cat_entry.get("subcategories", {}).get(subcategory)
            if sub_entry is not None:
                days, source, rule_id = _pick(sub_entry, package_state)
                return days, "subcategory", source, rule_id
        days, source, rule_id = _pick(cat_entry["default"], package_state)
        return days, "category", source, rule_id

    days, source, rule_id = _pick(data["global_default"], package_state)
    return days, "global_default", source, rule_id


def estimate_freshness(
    captured_at: datetime | date,
    category: FoodCategory,
    subcategory: str | None = None,
    package_state: PackageState = PackageState.UNKNOWN,
) -> FreshnessEstimate:
    """Fotoğraf tarihinden tahmini tazelik tarihini üret."""
    captured_date = captured_at.date() if isinstance(captured_at, datetime) else captured_at
    days, resolved_from, source, rule_id = shelf_life_days(category, subcategory, package_state)
    return FreshnessEstimate(
        estimated_freshness_date=captured_date + timedelta(days=days),
        shelf_life_days=days,
        basis=FreshnessBasis.CATEGORY_HEURISTIC,
        resolved_from=resolved_from,
        source=source,
        rule_id=rule_id,
    )


def user_provided_freshness(value: date) -> FreshnessEstimate:
    """Kullanıcı tarihi kendisi girdiğinde sezgisel tahmin devre dışı kalır.

    `shelf_life_days` burada anlamsız olduğu için -1 döner; bu değeri
    "hesaplanmadı" olarak okuyun, 0 ile karıştırmayın.
    """
    return FreshnessEstimate(
        estimated_freshness_date=value,
        shelf_life_days=-1,
        basis=FreshnessBasis.USER_PROVIDED,
        resolved_from="user",
    )
