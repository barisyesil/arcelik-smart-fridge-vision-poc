"""POST /v1/uploads — presigned POST üretir, UploadStatus=PENDING yazar.

Bu modül kendi başına bir Lambda değildir. `fridge-api` Lambda'sının tek CDK
`handler=` referansı `handlers.inventory_api.handler`dır; o, "POST /v1/uploads"
rotasını buradaki `create_upload`'a yönlendirir. Bir Lambda kaynağının tek giriş
noktası olabilir.

Handler kuralı: event'i parse et, core'u çağır, sonucu yaz. İş mantığı yok.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import boto3

from adapters.repository import DynamoRepository
from core.inventory import UPLOAD_PREFIX, new_id, object_key
from core.models import UploadRecord, UploadStatus
from handlers._http import respond
from handlers.context import resolve_context

BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
TABLE_NAME = os.environ.get("TABLE_NAME", "")

# Presigned POST (PUT değil): PUT boyut sınırlayamaz, POST koşulları sınırlayabilir.
PRESIGN_CONDITIONS = [
    ["content-length-range", 1024, 5 * 1024 * 1024],
    ["starts-with", "$Content-Type", "image/"],
]
PRESIGN_EXPIRY_S = 300

# Modül seviyesinde bir kez kur, sıcak çağrılar arasında paylaş. Import anında
# çağrı yapmıyorlar, sadece nesne oluşturuyorlar — bu yüzden testlerde AWS
# erişimi gerekmez.
_s3_client = None
_repository: DynamoRepository | None = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _get_repository() -> DynamoRepository:
    global _repository
    if _repository is None:
        table = boto3.resource("dynamodb").Table(TABLE_NAME)
        _repository = DynamoRepository(table)
    return _repository


def create_upload(event):  # noqa: ANN001
    ctx = resolve_context(event, _get_repository())
    upload_id = new_id("upl")
    created_at = datetime.now(UTC)
    # Nesne anahtarı sunucuda üretilir, istemcinin dosya adına güvenilmez.
    # Buzdolabı bazlı prefix: aynı dolabın yüklemeleri birlikte gruplanır ve
    # extractor upload_id'yi S3 olayından geri çıkarabilir.
    key = object_key(ctx.fridge_id, upload_id, created_at)

    presigned = _get_s3_client().generate_presigned_post(
        Bucket=BUCKET_NAME,
        Key=key,
        # Kopya şart: boto3 bu listeyi yerinde değiştirip bucket/key koşullarını
        # ekliyor. PRESIGN_CONDITIONS modül seviyesinde ve sıcak çağrılar arasında
        # paylaşılan bir sabit; kopyalamazsak her çağrı bir önceki upload_id'nin
        # koşullarını listede bırakır ve S3 en eski (artık geçersiz) key ile
        # karşılaştırıp yeni yüklemeleri 403'ler.
        Conditions=list(PRESIGN_CONDITIONS),
        ExpiresIn=PRESIGN_EXPIRY_S,
    )

    _get_repository().put_upload(
        UploadRecord(
            upload_id=upload_id,
            user_id=ctx.user_id,
            fridge_id=ctx.fridge_id,
            status=UploadStatus.PENDING,
            created_at=created_at,
            object_key=key,
        )
    )

    return respond(
        201,
        {
            "upload_id": upload_id,
            "object_key": key,
            "url": presigned["url"],
            "fields": presigned["fields"],
            "status": UploadStatus.PENDING.value,
        },
    )


__all__ = [
    "BUCKET_NAME",
    "PRESIGN_CONDITIONS",
    "PRESIGN_EXPIRY_S",
    "UPLOAD_PREFIX",
    "create_upload",
]
