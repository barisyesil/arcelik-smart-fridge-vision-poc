"""Envanter iş mantığı ve DynamoDB anahtar üretimi. boto3 kullanmaz.

Anahtar üretimi burada, `adapters/repository.py`'de değil: anahtar şeması bir
iş kararıdır, altyapı detayı değil. `repository.py` bu anahtarları alıp yazar;
kendisi kurmaz. Böylece erişim desenleri AWS olmadan test edilebilir.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from core.freshness import estimate_freshness
from core.models import ExtractedFood, InventoryItem, ItemState, Observation

# --- Anahtar üretimi ---


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


def observation_sk(captured_at: datetime, observation_id: str) -> str:
    # ISO 8601 UTC — sözlüksel sıralama = kronolojik sıralama.
    return f"OBS#{captured_at.strftime('%Y-%m-%dT%H:%M:%SZ')}#{observation_id}"


def item_sk(item_id: str) -> str:
    return f"ITEM#{item_id}"


def upload_keys(upload_id: str) -> dict[str, str]:
    return {"PK": f"UPLOAD#{upload_id}", "SK": "STATUS"}


#: S3 olay bildirimi sadece bu prefix'i dinler.
UPLOAD_PREFIX = "uploads/"


def object_key(user_id: str, upload_id: str, when: datetime) -> str:
    """S3 nesne anahtarı üretimi — anahtar sunucuda üretilir, istemciye bırakılmaz.

    `user_id` başta: kullanıcı bazlı IAM izni ve toplu silme mümkün olsun diye.
    `upload_id` sonda — bu, `presign` (üretir) ve `extractor` (S3 olayından geri
    okur) arasındaki tek bağdır. Ayrı bir UUID eklenmedi; `upload_id` zaten
    benzersiz, ikinci bir kimlik aynı bilgiyi iki kez taşırdı.
    """
    return f"{UPLOAD_PREFIX}{user_id}/{when:%Y-%m-%d}/{upload_id}.jpg"


def parse_object_key(key: str) -> str | None:
    """S3 anahtarından `upload_id`'yi çıkarır. Beklenmeyen bir biçimse `None`.

    `extractor.py` bunu S3 `ObjectCreated` olayında bulduğu anahtar için çağırır.
    `None` dönmesi yanlış prefix/format ile başka bir şeyin kovaya düştüğü
    anlamına gelir — işlemeyi durdurup loglamak doğru davranış.
    """
    parts = key.split("/")
    if len(parts) != 4 or parts[0] != "uploads" or not parts[3].endswith(".jpg"):
        return None
    return parts[3].removesuffix(".jpg")


def idempotency_key(bucket: str, key: str, etag: str) -> dict[str, str]:
    """S3 olayları en az bir kez teslim edilir; bu kilit zorunludur.

    ETag'i dahil ediyoruz: aynı anahtara yeni bir nesne yazılırsa (üzerine
    yazma) bu meşru bir yeni gözlemdir ve işlenmelidir.
    """
    digest = hashlib.sha256(f"{bucket}/{key}/{etag}".encode()).hexdigest()
    return {"PK": f"IDEM#{digest}", "SK": "LOCK"}


def gsi1_keys(user_id: str, item: InventoryItem) -> dict[str, str]:
    """Sparse GSI1 anahtarları.

    ACTIVE olmayan kalem için boş sözlük döner — çağıran taraf bu anahtarları
    REMOVE etmelidir. Boş string yazmak indeksi sparse olmaktan çıkarır ve
    tüketilmiş ürünler GSI1'in kapasitesini yemeye devam eder.
    """
    if item.state is not ItemState.ACTIVE:
        return {}
    return {
        "GSI1PK": f"USER#{user_id}#ACTIVE",
        "GSI1SK": f"FRESH#{item.estimated_freshness_date.isoformat()}#{item.item_id}",
    }


# --- İş mantığı ---


def new_id(prefix: str) -> str:
    """uuid4 tabanlı kimlik. Bu id'lerin hiçbiri aralık sorgusunda kullanılmadığı
    için (hepsi doğrudan erişim), zamana göre sıralanabilirlik gerekmiyor ve
    dış bağımlılık eklemeye değmez.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def build_item(
    food: ExtractedFood,
    *,
    user_id: str,
    observation_id: str,
    captured_at: datetime,
    now: datetime,
) -> tuple[InventoryItem, str | None]:
    """(kalem, uyarı). Uyarı, raf ömrü tablosu ürünü tanımadıysa dolar."""
    estimate = estimate_freshness(captured_at, food.category, food.subcategory, food.package_state)
    item = InventoryItem(
        item_id=new_id("itm"),
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
    )
    return item, estimate.warning


def items_from_observation(
    observation: Observation, now: datetime
) -> tuple[list[InventoryItem], list[str]]:
    """(kalemler, uyarılar). Her gözlem ekleme yapar, uzlaştırma yoktur.

    Aynı ürün iki kez fotoğraflanırsa envantere iki kez girer. Bu bir hata
    değil, bilinçli bir sadeleştirme — kullanıcı fazlasını siler.
    """
    items: list[InventoryItem] = []
    warnings: list[str] = []

    for food in observation.foods:
        item, warning = build_item(
            food,
            user_id=observation.user_id,
            observation_id=observation.observation_id,
            captured_at=observation.captured_at,
            now=now,
        )
        items.append(item)
        if warning and warning not in warnings:
            warnings.append(warning)

    return items, warnings
