"""fridge-api Lambda'sının tek CDK `handler=` referansı burasıdır.

POST /v1/uploads, GET /v1/uploads/{id}, GET /v1/items, PATCH+DELETE /v1/items/{id}
— beşi de bu tek fonksiyona düşer, buradan içeride dağıtılır. Rota başına Lambda
ayırmak soğuk başlangıç sayısını ve CDK yüzeyini gereksiz büyütürdü.

`presign.create_upload` de bu dosyadan çağrılır — kendi başına bir Lambda
handler'ı değildir.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict

import boto3

from adapters.repository import DynamoRepository, ItemNotFound, RepositoryError
from core.models import InventoryItem, ItemState, UploadStatus
from core.taxonomy import FoodCategory, PackageState
from handlers._http import (
    json_body,
    not_implemented,
    path_param,
    respond,
    respond_empty,
    route_key,
    user_id_from,
)
from handlers.presign import create_upload

logger = logging.getLogger()

TABLE_NAME = os.environ.get("TABLE_NAME", "")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")

#: Kaynak fotoğrafın presigned GET ömrü. Arayüz bu URL ile görseli çekip her
#: ürünü bounding box'a göre kırpar; işlem tamamlanır tamamlanmaz kullanıldığı
#: için kısa bir süre yeterli.
SOURCE_IMAGE_URL_EXPIRY_S = 300

_s3_client = None

ROUTES = (
    "POST /v1/uploads",
    "GET /v1/uploads/{upload_id}",
    "GET /v1/items",
    "PATCH /v1/items/{item_id}",
    "DELETE /v1/items/{item_id}",
)

_repository: DynamoRepository | None = None


def _get_repository() -> DynamoRepository:
    global _repository
    if _repository is None:
        table = boto3.resource("dynamodb").Table(TABLE_NAME)
        _repository = DynamoRepository(table)
    return _repository


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _source_image_url(object_key: str) -> str | None:
    """Kaynak fotoğraf için kısa ömürlü presigned GET URL'si.

    Kutuya göre kırpma şimdilik tarayıcıda yapıldığı için arayüzün Gemini'nin
    gördüğü aynı görsele erişmesi gerekir. Bucket dışarıya kapalı; erişimin tek
    yolu bu imzalı URL. Üretim başarısız olursa (izin/ağ) `None` döneriz —
    kırpma özelliği kaybolur ama envanter listesi çalışmaya devam eder.
    """
    if not BUCKET_NAME:
        return None
    try:
        return _get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": object_key},
            ExpiresIn=SOURCE_IMAGE_URL_EXPIRY_S,
        )
    except Exception:  # noqa: BLE001 — presign hatası özelliği düşürür, isteği değil
        logger.warning('{"event": "source_image_presign_failed"}')
        return None


def _item_to_json(item: InventoryItem) -> dict:
    """İstemcinin gördüğü ürün nesnesi — API kontratı v1 ile birebir eşleşir."""
    return {
        "item_id": item.item_id,
        "name": item.name,
        "brand": item.brand,
        "raw_label": item.raw_label,
        "category": item.category.value,
        "subcategory": item.subcategory,
        "package_state": item.package_state.value,
        "quantity": asdict(item.quantity),
        "estimated_freshness_date": item.estimated_freshness_date.isoformat(),
        "freshness_basis": item.freshness_basis.value,
        "confidence": asdict(item.confidence) if item.confidence else None,
        "needs_review": item.needs_review,
        "state": item.state.value,
        # Arayüz bu kutuyu kaynak görsele uygulayıp ürünü ayrı görsel olarak
        # kırpar. Kutu yoksa `None` — arayüz kırpma yapmaz.
        "bounding_box": asdict(item.bounding_box) if item.bounding_box else None,
    }


def _get_upload_status(event: dict) -> dict:
    upload_id = path_param(event, "upload_id")
    record = _get_repository().get_upload(upload_id)
    if record is None:
        return respond(404, {"error": "upload_not_found", "upload_id": upload_id})

    items = []
    source_image_url = None
    if record.status is UploadStatus.COMPLETED and record.item_ids:
        found = _get_repository().get_items(record.user_id, list(record.item_ids))
        items = [_item_to_json(item) for item in found]
        # Tek presigned URL tüm ürünler için: hepsi aynı kaynak fotoğraftan
        # kırpılır. Yalnızca kırpılacak kutusu olan bir ürün varsa üret —
        # kutusuz sonuçta görsele hiç ihtiyaç yok.
        if any(item["bounding_box"] for item in items):
            source_image_url = _source_image_url(record.object_key)

    return respond(
        200,
        {
            "upload_id": record.upload_id,
            "status": record.status.value,
            "observation_id": record.observation_id,
            "items": items,
            "source_image_url": source_image_url,
            "error": record.error_code,
        },
    )


def _list_items(event: dict) -> dict:
    user_id = user_id_from(event)
    items = _get_repository().list_active_items(user_id)
    return respond(200, {"items": [_item_to_json(item) for item in items]})


#: Beyaz liste: PATCH gövdesinden geçerse repository.update_item bunları yazar.
#: Rastgele alan enjeksiyonuna kapalı.
_PATCHABLE_FIELDS = (
    "name",
    "brand",
    "category",
    "subcategory",
    "package_state",
    "quantity",
    "state",
)


def _validate_patch_changes(changes: dict) -> str | None:
    """Geçersizse hata mesajı, geçerliyse None. Enum doğrulaması handler'da
    yapılır çünkü bu bir girdi doğrulamasıdır, `core/`'un iş kuralı değil.
    """
    try:
        if "category" in changes:
            FoodCategory(changes["category"])
        if "package_state" in changes:
            PackageState(changes["package_state"])
        if "state" in changes:
            ItemState(changes["state"])
    except ValueError as exc:
        return str(exc)

    if "quantity" in changes:
        quantity = changes["quantity"]
        if not isinstance(quantity, dict) or "value" not in quantity or "unit" not in quantity:
            return "quantity {value, unit} biçimine uymuyor"

    return None


def _patch_item(event: dict) -> dict:
    user_id = user_id_from(event)
    item_id = path_param(event, "item_id")
    body = json_body(event)
    changes = {k: v for k, v in body.items() if k in _PATCHABLE_FIELDS}

    if not changes:
        return respond(400, {"error": "no_updatable_fields", "allowed": list(_PATCHABLE_FIELDS)})

    validation_error = _validate_patch_changes(changes)
    if validation_error:
        return respond(400, {"error": "invalid_field_value", "detail": validation_error})

    try:
        item = _get_repository().update_item(user_id, item_id, changes)
    except ItemNotFound:
        return respond(404, {"error": "item_not_found", "item_id": item_id})
    except RepositoryError as exc:
        return respond(400, {"error": "invalid_update", "detail": str(exc)})

    return respond(200, _item_to_json(item))


def _delete_item(event: dict) -> dict:
    user_id = user_id_from(event)
    item_id = path_param(event, "item_id")
    _get_repository().delete_item(user_id, item_id)
    return respond_empty(204)


def handler(event, context):  # noqa: ANN001
    route = route_key(event)

    if route == "POST /v1/uploads":
        return create_upload(event)
    if route == "GET /v1/uploads/{upload_id}":
        return _get_upload_status(event)
    if route == "GET /v1/items":
        return _list_items(event)
    if route == "PATCH /v1/items/{item_id}":
        return _patch_item(event)
    if route == "DELETE /v1/items/{item_id}":
        return _delete_item(event)

    if route not in ROUTES:
        # Bilinmeyen rota altyapı hatasıdır (API GW yanlış bağladı), eksik
        # uygulama değil — ayırt edilebilir olması hata ayıklamayı kolaylaştırır.
        return respond(404, {"error": "unknown_route", "route": route})

    return not_implemented(route)
