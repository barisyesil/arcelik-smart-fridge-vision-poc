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
    """ACTIVE dışına çıkan kalem GSI1'den düşer (sparse index).

    DRAFT: extraction'ın ürettiği ama kullanıcının HENÜZ onaylamadığı kalem.
    Envanterde (`GET /v1/items`) görünmez; yalnızca upload-status kontrol
    ekranına döner. Kullanıcı onaylayınca (`POST /v1/uploads/{id}/confirm`)
    ACTIVE'e geçer, reddedilirse silinir. Onaylanmayan draft'lar TTL ile
    otomatik temizlenir. Böylece "fotoğraf = otomatik ekleme" değil, "fotoğraf
    = onaya sun" olur.
    """

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"


# --- Mobil domain enum'ları (SRS bölüm 12.2) ---
#
# Bu enum'lar mobil uygulamanın swipe/değerlendirme/alışveriş/bildirim
# akışlarının backend karşılığıdır. Değerler API kontratının parçasıdır; UI
# Türkçe gösterir ama anahtarları değiştirmez.


class SwipeActionType(StrEnum):
    """Kontrol kartındaki hareketin backend karşılığı."""

    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"
    REVIEWED = "REVIEWED"


class DiscardReason(StrEnum):
    """`DISCARDED` için isteğe bağlı mikro anket cevabı."""

    OVERPURCHASED = "OVERPURCHASED"
    NO_OPPORTUNITY_TO_CONSUME = "NO_OPPORTUNITY_TO_CONSUME"
    SPOILED_EARLIER_THAN_EXPECTED = "SPOILED_EARLIER_THAN_EXPECTED"
    IMPROPER_STORAGE = "IMPROPER_STORAGE"
    WRONG_DETECTION = "WRONG_DETECTION"
    OTHER = "OTHER"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY"


class ObservedFreshnessState(StrEnum):
    """Kullanıcının yukarı-swipe panelinde seçtiği mevcut durum."""

    STILL_FRESH = "STILL_FRESH"
    BORDERLINE = "BORDERLINE"
    SPOILED = "SPOILED"
    UNSURE = "UNSURE"


class FreshnessAssessmentReason(StrEnum):
    LOOKS_FRESH = "LOOKS_FRESH"
    TEXTURE_CHANGED = "TEXTURE_CHANGED"
    SMELL_CHANGED = "SMELL_CHANGED"
    PACKAGE_DAMAGED = "PACKAGE_DAMAGED"
    OPENED_TODAY = "OPENED_TODAY"
    WRONG_DETECTION = "WRONG_DETECTION"
    OTHER = "OTHER"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY"


class NotificationMode(StrEnum):
    DAILY_DIGEST = "DAILY_DIGEST"
    CRITICAL_ONLY = "CRITICAL_ONLY"
    OFF = "OFF"


class ReplacementCandidateStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"
    REVERTED = "REVERTED"


class ShoppingItemState(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REMOVED = "REMOVED"


class ReviewReason(StrEnum):
    """`GET /v1/review-queue` her kalem için neden kuyrukta olduğunu söyler."""

    USER_SCHEDULED = "USER_SCHEDULED"
    OVERDUE = "OVERDUE"
    CRITICAL = "CRITICAL"
    APPROACHING = "APPROACHING"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FridgeStatus(StrEnum):
    """Provision edilmiş buzdolabı kaydının durumu."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


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
    """Bir ürün grubundaki miktar; kesin sayı ya da tahmini aralık.

    Aynı üründen birden çok fiziksel adet TEK satırda toplanır (10 domates =
    tek `domates` satırı, value=10). Model tam sayamıyorsa `value` alt sınırı,
    `value_max` üst sınırı taşır ("8-10 tane" -> value=8, value_max=10). Kesin
    sayıda `value_max` None kalır. Böylece istemci "10 tane" ile "yaklaşık
    8-10 tane"yi ayırt edebilir; birim `unit` ile serbestçe seçilir (tane,
    paket, koli, demet...).
    """

    value: int
    unit: str = "piece"
    #: Tahmini aralığın üst sınırı. None ise `value` kesin sayıdır. Verildiğinde
    #: her zaman `value_max >= value` olur (parse aşamasında güvene alınır).
    value_max: int | None = None

    @property
    def is_estimate(self) -> bool:
        """Kesin sayı değil, bir aralık mı? Doğruluk ölçümünde işaretlemek için."""
        return self.value_max is not None and self.value_max != self.value


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
    #: Gözlem hangi buzdolabına ait. Veri buzdolabı bazında partition'lanır
    #: (hane modeli); `user_id` yalnızca fotoğrafı kimin yüklediğini kaydeder.
    fridge_id: str
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
    """Değişebilir. Kullanıcı düzeltir, tüketir, siler.

    Sistem tahmini (`estimated_freshness_date`) ile kullanıcı düzeltmesi
    (`user_adjusted_freshness_date`) AYRI saklanır — kullanıcı geri bildirimi
    orijinal tahmini ezmez (BR-002, FR-SYNC-003). Kontrol sıralamasında
    kullanılan "etkin tarih" `effective_freshness_date` ile türetilir.
    """

    item_id: str
    #: Partition sahibi buzdolabı (hane modeli). `user_id` audit içindir.
    fridge_id: str
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
    bounding_box: BoundingBox | None = None
    #: Kullanıcı değerlendirmesinden türeyen tarih; sistem tahminini EZMEZ.
    user_adjusted_freshness_date: date | None = None
    #: Kullanıcının bu kalemi son gözden geçirme ve kuyruğa yeniden giriş zamanı.
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    #: Kullanıcı bu kalem için özel takip istedi mi (kuyruğa zorla girer).
    user_requested_review: bool = False
    #: Local URI ya da ileride thumbnail referansı (mobil kart görseli).
    image_ref: str | None = None
    #: Optimistic concurrency / senkron sürümü. Her yazımda artar.
    version: int = 1
    schema_version: str = SCHEMA_VERSION

    @property
    def effective_freshness_date(self) -> date:
        """Kontrol sıralamasında kullanılan tarih (BR-002)."""
        return self.user_adjusted_freshness_date or self.estimated_freshness_date


@dataclass(frozen=True)
class UploadRecord:
    """`GET /v1/uploads/{upload_id}` bu kaydı okur."""

    upload_id: str
    user_id: str
    fridge_id: str
    status: UploadStatus
    created_at: datetime
    object_key: str
    observation_id: str | None = None
    item_ids: tuple[str, ...] = field(default_factory=tuple)
    error_code: str | None = None
    schema_version: str = SCHEMA_VERSION


# --- Mobil cloud entity'leri (SRS bölüm 12) ---


@dataclass(frozen=True)
class FridgeRegistryEntry:
    """Önceden provision edilmiş buzdolabı. Kayıt sırasında bu ID doğrulanır."""

    fridge_id: str
    label: str
    status: FridgeStatus
    created_at: datetime


@dataclass(frozen=True)
class NotificationPreferences:
    """Kullanıcının bildirim tercihleri (kaynak otorite backend'dir)."""

    mode: NotificationMode = NotificationMode.DAILY_DIGEST
    digest_time: str = "18:30"  # HH:mm, kullanıcı yerel saati
    quiet_hours_start: str | None = "22:00"
    quiet_hours_end: str | None = "08:00"
    timezone_id: str = "Europe/Istanbul"


@dataclass
class UserProfile:
    """Kullanıcı hesabı. `user_id` = Cognito JWT `sub`. Bir buzdolabına bağlıdır."""

    user_id: str
    fridge_id: str
    display_name: str
    created_at: datetime
    updated_at: datetime
    notification_preferences: NotificationPreferences = field(
        default_factory=NotificationPreferences
    )
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class SwipeAction:
    """Değişmez swipe olayı. `client_action_id` ile idempotent (BR-007)."""

    action_id: str
    client_action_id: str
    fridge_id: str
    item_id: str
    user_id: str
    type: SwipeActionType
    occurred_at: datetime
    previous_item_state: ItemState
    discard_reason: DiscardReason | None = None
    reverted_at: datetime | None = None
    #: Bu aksiyonun doğurduğu öneri (varsa). Undo bunu REVERTED yapar.
    replacement_candidate_id: str | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class FreshnessAssessment:
    """Değişmez kullanıcı değerlendirmesi. Sistem tahminini ezmez (BR-009)."""

    assessment_id: str
    fridge_id: str
    item_id: str
    user_id: str
    assessed_at: datetime
    observed_state: ObservedFreshnessState
    system_predicted_fresh_until_before: date
    rule_version: str
    user_estimated_days_remaining: int | None = None
    user_estimated_fresh_until: date | None = None
    next_review_at: datetime | None = None
    reason: FreshnessAssessmentReason | None = None
    source: str = "USER"
    schema_version: str = SCHEMA_VERSION


@dataclass
class ReplacementCandidate:
    """Tüketilen/atılan üründen doğan alışveriş önerisi (BR-010)."""

    candidate_id: str
    fridge_id: str
    source_item_id: str
    source_action_id: str
    name: str
    category: FoodCategory
    reason: SwipeActionType  # CONSUMED veya DISCARDED
    status: ReplacementCandidateStatus
    created_at: datetime
    suggested_quantity: Quantity | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass
class ShoppingListItem:
    """Buzdolabı bazında paylaşılan alışveriş listesi kaydı."""

    shopping_item_id: str
    fridge_id: str
    name: str
    state: ShoppingItemState
    created_at: datetime
    updated_at: datetime
    category: FoodCategory | None = None
    quantity: Quantity | None = None
    source_candidate_id: str | None = None
    note: str | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass
class DeviceRegistration:
    """Push için cihaz kaydı (kullanıcıya bağlı). Push gönderimi sonraki faz."""

    installation_id: str
    user_id: str
    push_token: str
    platform: str  # "android"
    created_at: datetime
    updated_at: datetime
    schema_version: str = SCHEMA_VERSION


@dataclass
class ItemReminder:
    """Yalnız açık kullanıcı talebiyle oluşan bireysel hatırlatma (BR-011)."""

    item_id: str
    fridge_id: str
    scheduled_at: datetime
    version: int
    enabled: bool = True
    last_delivered_at: datetime | None = None
    schema_version: str = SCHEMA_VERSION
