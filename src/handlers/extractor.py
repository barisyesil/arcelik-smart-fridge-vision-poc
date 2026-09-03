"""S3 ObjectCreated -> Gemini -> Observation + InventoryItem.

Handler kuralı: event'i parse et, provider'ı ve repository'yi çağır, sonucu yaz.
İş mantığı `core/`'da; buraya yazma.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from datetime import UTC, datetime

import boto3

from adapters.repository import DynamoRepository, IdempotencyConflict
from adapters.vision import GeminiProvider, StubVisionProvider, VisionError
from core.inventory import items_from_observation, new_id, parse_object_key
from core.models import Observation

TABLE_NAME = os.environ.get("TABLE_NAME", "")
#: Anahtarın kendisi değil, SSM parametre ADI ortam değişkeninde tutulur.
GEMINI_PARAM_NAME = os.environ.get("GEMINI_PARAM_NAME", "/smartfridge/dev/gemini-api-key")
#: "stub" verilirse Gemini'ye hiç çıkılmaz — gerçek anahtar olmadan
#: S3 -> Lambda -> DynamoDB zinciri uçtan uca test edilebilir.
VISION_PROVIDER_MODE = os.environ.get("VISION_PROVIDER", "gemini")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

_s3_client = None
_ssm_client = None
_repository: DynamoRepository | None = None
_vision_provider = None
_gemini_api_key: str | None = None


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


def _get_gemini_api_key() -> str:
    """SSM'den bir kez oku, sıcak çağrılar arasında paylaş.

    Her invoke'ta SSM'e gitmek hem gecikme hem gereksiz API çağrısı demektir;
    değer konteyner ömrü boyunca değişmez.
    """
    global _gemini_api_key
    if _gemini_api_key is None:
        global _ssm_client
        if _ssm_client is None:
            _ssm_client = boto3.client("ssm")
        response = _ssm_client.get_parameter(Name=GEMINI_PARAM_NAME, WithDecryption=True)
        _gemini_api_key = response["Parameter"]["Value"]
    return _gemini_api_key


def _get_vision_provider():
    global _vision_provider
    if _vision_provider is None:
        if VISION_PROVIDER_MODE == "stub":
            _vision_provider = StubVisionProvider()
        else:
            _vision_provider = GeminiProvider(_get_gemini_api_key())
    return _vision_provider


def _s3_records(event: dict) -> list[dict]:
    """S3 olayından (bucket, key, etag) üçlülerini çıkar."""
    records = []
    for record in event.get("Records") or []:
        s3 = record.get("s3") or {}
        bucket = (s3.get("bucket") or {}).get("name")
        obj = s3.get("object") or {}
        if bucket and obj.get("key"):
            records.append({"bucket": bucket, "key": obj["key"], "etag": obj.get("eTag", "")})
    return records


def _log(event_name: str, **fields) -> None:
    # Görsel içeriğini veya LLM'in tam yanıtını asla loglama.
    logger.info(json.dumps({"event": event_name, **fields}))


def _process_one(repo: DynamoRepository, record: dict, upload_id: str) -> None:
    repo.mark_upload_processing(upload_id)

    upload_record = repo.get_upload(upload_id)
    if upload_record is None:
        raise RuntimeError(f"UploadRecord bulunamadı: {upload_id}")

    s3_object = _get_s3_client().get_object(Bucket=record["bucket"], Key=record["key"])
    image_bytes = s3_object["Body"].read()
    mime_type = s3_object.get("ContentType") or "image/jpeg"
    # S3'ün nesne zaman damgası fotoğrafın çekildiği ana en yakın sinyaldir;
    # Lambda'nın ne zaman çalıştığı (yeniden denemelerde gecikebilir) değil.
    captured_at = s3_object.get("LastModified") or datetime.now(UTC)

    result = _get_vision_provider().extract(image_bytes, mime_type)

    now = datetime.now(UTC)
    observation = Observation(
        observation_id=new_id("obs"),
        user_id=upload_record.user_id,
        upload_id=upload_id,
        captured_at=captured_at,
        source_bucket=record["bucket"],
        source_key=record["key"],
        foods=tuple(result.foods),
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        latency_ms=result.latency_ms,
    )
    items, warnings = items_from_observation(observation, now)
    observation = replace(observation, warnings=tuple(warnings))

    repo.commit_extraction(observation, items)
    _log(
        "extraction_completed",
        upload_id=upload_id,
        item_count=len(items),
        latency_ms=result.latency_ms,
        warnings=warnings,
    )


def handler(event, context):  # noqa: ANN001
    records = _s3_records(event)
    if not records:
        # Bozuk ya da boş olay: işlenecek nesne yok. AWS istemcisini kurmadan
        # dön — böylece hem gereksiz bağlantı açılmaz hem de bu yol birim
        # testlerinde AWS ortamı (region/kimlik) gerektirmez.
        _log("no_processable_records", record_count=len(event.get("Records") or []))
        return {"processed": 0}

    repo = _get_repository()
    processed = 0

    for record in records:
        upload_id = parse_object_key(record["key"])
        if upload_id is None:
            _log("unrecognized_object_key", key=record["key"])
            continue

        try:
            repo.acquire_idempotency_lock(record["bucket"], record["key"], record["etag"])
        except IdempotencyConflict:
            _log("duplicate_skipped", upload_id=upload_id)
            continue

        try:
            _process_one(repo, record, upload_id)
            processed += 1
        except VisionError as exc:
            _log("extraction_failed", upload_id=upload_id, error_type=type(exc).__name__)
            repo.mark_upload_failed(upload_id, error_code="VISION_ERROR")
            raise  # Lambda yeniden dener; 3 başarısızlık sonrası DLQ'ya düşer.
        except Exception as exc:  # noqa: BLE001 — hata tipini kaydedip yeniden fırlat
            _log("extraction_failed", upload_id=upload_id, error_type=type(exc).__name__)
            repo.mark_upload_failed(upload_id, error_code=type(exc).__name__)
            raise

    return {"processed": processed}
