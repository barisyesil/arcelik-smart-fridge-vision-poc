"""Saf veri modelleri. AWS SDK'sı, HTTP, JSON serileştirme yok — sadece şekil.

`Observation` değişmezdir (frozen), `InventoryItem` değişebilir: fotoğraf bir kez
gözlemlenir ve o gözlem bir daha yazılmaz; envanter kalemi ise kullanıcı
tarafından düzeltilebilir, tüketilebilir, silinebilir.

Alan adları API kontratının parçasıdır; yeniden adlandırmak istemciyi kırar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from core.taxonomy import FoodCategory, PackageState

#: Tüm olaylar ve kalıcı kayıtlar bu alanı taşır. String, çünkü minor sürüm
#: (1.0 -> 1.1) geriye uyumlu ekleme, major (2.0) kırıcı değişiklik demek.
SCHEMA_VERSION = "1.0"

#: Bu eşiğin altındaki ürün `needs_review=True` işaretlenir; arayüz bunu
#: rozet olarak gösterir.
REVIEW_CONFIDENCE_THRESHOLD = 0.70


class UploadStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FreshnessBasis(StrEnum):
    """Tazelik tarihi bir tahmindir, üreticinin bastığı tarih değildir."""

    CATEGORY_HEURISTIC = "CATEGORY_HEURISTIC"
    USER_PROVIDED = "USER_PROVIDED"


class ItemState(StrEnum):
    """ACTIVE dışına çıkan kalem GSI1'den düşer (sparse index)."""

    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"


@dataclass(frozen=True)
class FieldConfidence:
    """Güven skoru tek sayı değil, alan bazında tutulur.

    "Adı düşük güvenli ama kategorisi kesin" durumunu ayırt edebilmek için
    ad ve kategori skorları ayrı; tek skor bu bilgiyi yok ederdi.
    """

    name: float
    category: float

    @property
    def needs_review(self) -> bool:
        return min(self.name, self.category) < REVIEW_CONFIDENCE_THRESHOLD


@dataclass(frozen=True)
class Quantity:
    value: int
    unit: str = "piece"


@dataclass(frozen=True)
class BoundingBox:
    """Gemini 2.5'in ürün için döndürdüğü sınırlayıcı kutu.

    Gemini konvansiyonu: değerler `[ymin, xmin, ymax, xmax]` sırasında ve
    0-1000 aralığına normalize edilir (fotoğrafın gerçek piksel boyutundan
    BAĞIMSIZ). Çözünürlükten bağımsız olması bilinçli: kutu, Gemini'nin gördüğü
    S3'teki küçültülmüş görsele de, ileride farklı boyutta bir kopyaya da aynı
    şekilde uygulanır. Kırpma yapan taraf (şimdilik tarayıcı, ileride Lambda)
    bu oranları kendi görsel boyutuyla çarpar.

    Alan API kontratının parçasıdır: item DTO'sunda `bounding_box` olarak
    istemciye gider.
    """

    ymin: int
    xmin: int
    ymax: int
    xmax: int


@dataclass(frozen=True)
class ExtractedFood:
    """Modelin tek bir gıda için döndürdüğü ham çıkarım.

    Burada tarih yoktur; tarih `freshness.py`'de hesaplanır. `raw_label` modelin
    gördüğü etiketin aynen kendisidir ("Süzme Yoğurt 750g") — doğruluk ölçümünde
    "model neyi yanlış okudu" sorusunu cevaplayan alan budur; normalize edilmiş
    `name` bu bilgiyi siler.

    `bounding_box` modelin ürünü fotoğrafta nerede gördüğüdür; tanınmayan ya da
    geçersiz kutu `None` kalır ve ürün yine de envantere girer — kutu bir ek
    sinyaldir, ürünün varlığının ön koşulu değil.
    """

    name: str
    category: FoodCategory
    quantity: Quantity
    confidence: FieldConfidence
    raw_label: str | None = None
    brand: str | None = None
    subcategory: str | None = None
    package_state: PackageState = PackageState.UNKNOWN
    bounding_box: BoundingBox | None = None


@dataclass(frozen=True)
class Observation:
    """Değişmez. Bir fotoğrafın tek seferlik yorumu.

    `model_id` ve `prompt_version` her kayda yazılır: model veya prompt
    güncellendiğinde doğruluk değişimini ölçebilmenin tek yolu bu.
    """

    observation_id: str
    user_id: str
    upload_id: str
    captured_at: datetime
    source_bucket: str
    source_key: str
    foods: tuple[ExtractedFood, ...]
    model_id: str
    prompt_version: str
    latency_ms: int | None = None
    #: Sessizce yanlış tarih üretmek yerine bilinmezliği kaydeder.
    #: Örn. "shelf_life_fallback:global_default".
    warnings: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = SCHEMA_VERSION


@dataclass
class InventoryItem:
    """Değişebilir. Kullanıcı düzeltir, tüketir, siler."""

    item_id: str
    user_id: str
    name: str
    category: FoodCategory
    quantity: Quantity
    estimated_freshness_date: date
    freshness_basis: FreshnessBasis
    created_at: datetime
    updated_at: datetime
    observation_id: str
    brand: str | None = None
    raw_label: str | None = None
    subcategory: str | None = None
    package_state: PackageState = PackageState.UNKNOWN
    state: ItemState = ItemState.ACTIVE
    confidence: FieldConfidence | None = None
    needs_review: bool = False
    #: Ürünün kaynak fotoğraftaki konumu. Arayüz, kaynak görseli bu kutuya göre
    #: kırpıp ürünü ayrı bir görsel olarak gösterir. Kutu yoksa arayüz kırpma
    #: yapmaz, ürün metinle listelenir.
    bounding_box: BoundingBox | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class UploadRecord:
    """`GET /v1/uploads/{upload_id}` bu kaydı okur."""

    upload_id: str
    user_id: str
    status: UploadStatus
    created_at: datetime
    object_key: str
    observation_id: str | None = None
    item_ids: tuple[str, ...] = field(default_factory=tuple)
    error_code: str | None = None
    schema_version: str = SCHEMA_VERSION
