"""Envanter iş mantığı ve DynamoDB anahtar üretimi. boto3 kullanmaz.

Anahtar üretimi burada, `adapters/repository.py`'de değil: anahtar şeması bir
iş kararıdır, altyapı detayı değil. `repository.py` bu anahtarları alıp yazar;
kendisi kurmaz. Böylece erişim desenleri AWS olmadan test edilebilir.

Veri partition'ı **buzdolabı** bazındadır (hane modeli): envanter, gözlem,
swipe olayı, değerlendirme, alışveriş ve öneriler `FRIDGE#{fridge_id}` altında
toplanır; aynı dolaba kayıtlı kullanıcılar aynı veriyi paylaşır. Kullanıcıya
özel kayıtlar (profil, cihaz, tercih) `USER#{user_id}` altındadır.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from core.freshness import estimate_freshness
from core.models import ExtractedFood, InventoryItem, ItemState, Observation

# --- Partition anahtarları ---


def fridge_pk(fridge_id: str) -> str:
    return f"FRIDGE#{fridge_id}"


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


# --- Sort key üreticileri ---


def observation_sk(captured_at: datetime, observation_id: str) -> str:
    # ISO 8601 UTC — sözlüksel sıralama = kronolojik sıralama.
    return f"OBS#{captured_at.strftime('%Y-%m-%dT%H:%M:%SZ')}#{observation_id}"


def item_sk(item_id: str) -> str:
    return f"ITEM#{item_id}"


def action_sk(action_id: str) -> str:
    # Doğrudan erişim (undo için): zaman öneki YOK, action_id anahtarı benzersiz.
    # Kronolojik listeleme gerekirse ileride ayrı bir GSI eklenir.
    return f"ACTION#{action_id}"


def assessment_sk(assessed_at: datetime, assessment_id: str) -> str:
    return f"ASSESS#{assessed_at.strftime('%Y-%m-%dT%H:%M:%SZ')}#{assessment_id}"


def candidate_sk(candidate_id: str) -> str:
    return f"CAND#{candidate_id}"


def shopping_sk(shopping_item_id: str) -> str:
    return f"SHOP#{shopping_item_id}"


def reminder_sk(item_id: str) -> str:
    # Kalem başına tek hatırlatma: item_id anahtarı benzersiz kılar.
    return f"REMINDER#{item_id}"


def device_sk(installation_id: str) -> str:
    return f"DEVICE#{installation_id}"


# --- Sabit anahtar kayıtları ---


def fridge_meta_keys(fridge_id: str) -> dict[str, str]:
    """Provision edilmiş buzdolabı kaydı."""
    return {"PK": fridge_pk(fridge_id), "SK": "META"}


def profile_keys(user_id: str) -> dict[str, str]:
    return {"PK": user_pk(user_id), "SK": "PROFILE"}


def upload_keys(upload_id: str) -> dict[str, str]:
    return {"PK": f"UPLOAD#{upload_id}", "SK": "STATUS"}


def client_action_keys(fridge_id: str, client_action_id: str) -> dict[str, str]:
    """`client_action_id` idempotency kilidi (BR-007, FR-SYNC-002).

    Buzdolabı bazında benzersiz: aynı client_action_id iki farklı dolapta
    çakışmasın. Kilit değeri, oluşturulan gerçek `action_id`'yi taşır ki tekrar
    gelen istek aynı sonucu döndürebilsin.
    """
    return {"PK": f"CLIENTACT#{fridge_id}#{client_action_id}", "SK": "LOCK"}


#: S3 olay bildirimi sadece bu prefix'i dinler.
UPLOAD_PREFIX = "uploads/"


def object_key(fridge_id: str, upload_id: str, when: datetime) -> str:
    """S3 nesne anahtarı — sunucuda üretilir, istemciye bırakılmaz.

    `fridge_id` başta: buzdolabı bazlı IAM izni ve toplu yaşam döngüsü mümkün
    olsun diye. `upload_id` sonda; `presign` (üretir) ve `extractor` (S3
    olayından geri okur) arasındaki tek bağ budur.
    """
    return f"{UPLOAD_PREFIX}{fridge_id}/{when:%Y-%m-%d}/{upload_id}.jpg"


def parse_object_key(key: str) -> str | None:
    """S3 anahtarından `upload_id`'yi çıkarır. Beklenmeyen biçimse `None`."""
    parts = key.split("/")
    if len(parts) != 4 or parts[0] != "uploads" or not parts[3].endswith(".jpg"):
        return None
    return parts[3].removesuffix(".jpg")


def idempotency_key(bucket: str, key: str, etag: str) -> dict[str, str]:
    """S3 olayları en az bir kez teslim edilir; bu kilit zorunludur."""
    digest = hashlib.sha256(f"{bucket}/{key}/{etag}".encode()).hexdigest()
    return {"PK": f"IDEM#{digest}", "SK": "LOCK"}


def gsi1_keys(fridge_id: str, item: InventoryItem) -> dict[str, str]:
    """Sparse GSI1 anahtarları — buzdolabı bazında aktif ürünler, etkin tarihe göre.

    Sıralama `effective_freshness_date` üzerinden: kullanıcı düzeltmesi varsa o,
    yoksa sistem tahmini. Kontrol kuyruğu bu sırayı kullanır.
    ACTIVE olmayan kalem için boş sözlük döner (çağıran REMOVE eder).
    """
    if item.state is not ItemState.ACTIVE:
        return {}
    return {
        "GSI1PK": f"FRIDGE#{fridge_id}#ACTIVE",
        "GSI1SK": f"FRESH#{item.effective_freshness_date.isoformat()}#{item.item_id}",
    }


# --- İş mantığı ---


def new_id(prefix: str) -> str:
    """uuid4 tabanlı kimlik. Aralık sorgusunda kullanılmadığı için zamana göre
    sıralanabilirlik gerekmiyor.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def build_item(
    food: ExtractedFood,
    *,
    fridge_id: str,
    user_id: str,
    observation_id: str,
    captured_at: datetime,
    now: datetime,
) -> tuple[InventoryItem, str | None]:
    """(kalem, uyarı). Uyarı, raf ömrü tablosu ürünü tanımadıysa dolar."""
    estimate = estimate_freshness(captured_at, food.category, food.subcategory, food.package_state)
    item = InventoryItem(
        item_id=new_id("itm"),
        fridge_id=fridge_id,
        user_id=user_id,
        name=food.name,
        brand=food.brand,
        raw_label=food.raw_label,
        category=food.category,
        subcategory=food.subcategory,
        package_state=food.package_state,
        quantity=food.quantity,
        estimated_freshness_date=estimate.estimated_freshness_date,
        freshness_basis=estimate.basis,
        created_at=now,
        updated_at=now,
        observation_id=observation_id,
        confidence=food.confidence,
        needs_review=food.confidence.needs_review,
        bounding_box=food.bounding_box,
    )
    return item, estimate.warning


def items_from_observation(
    observation: Observation, now: datetime
) -> tuple[list[InventoryItem], list[str]]:
    """(kalemler, uyarılar). Her gözlem ekleme yapar, uzlaştırma yoktur."""
    items: list[InventoryItem] = []
    warnings: list[str] = []

    for food in observation.foods:
        item, warning = build_item(
            food,
            fridge_id=observation.fridge_id,
            user_id=observation.user_id,
            observation_id=observation.observation_id,
            captured_at=observation.captured_at,
            now=now,
        )
        items.append(item)
        if warning and warning not in warnings:
            warnings.append(warning)

    return items, warnings
