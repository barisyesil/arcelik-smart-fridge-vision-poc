"""Kalıcılık soyutlaması + DynamoDB uygulaması.

Anahtar üretimi burada değil, `core/inventory.py`'de. Bu dosya sadece "o
anahtarları DynamoDB'ye nasıl yazarım" sorusunu cevaplar. Tablo yalnızca `query`
ve `get_item` ile okunur, `scan` kullanılmaz.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from core.inventory import gsi1_keys, idempotency_key, item_sk, observation_sk, upload_keys, user_pk
from core.models import (
    SCHEMA_VERSION,
    ExtractedFood,
    FieldConfidence,
    FreshnessBasis,
    InventoryItem,
    ItemState,
    Observation,
    Quantity,
    UploadRecord,
    UploadStatus,
)
from core.taxonomy import FoodCategory, PackageState

#: IdempotencyLock ve UploadStatus kayıtları 7 gün sonra DynamoDB tarafından
#: silinir — bu kayıtlar geçicidir, süresiz saklanmalarının değeri yok.
_TTL_SECONDS = 7 * 86400
_DT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RepositoryError(RuntimeError):
    pass


class IdempotencyConflict(RepositoryError):
    """Bu S3 olayı zaten işlenmiş. Çağıran taraf sessizce çıkmalı."""


class ItemNotFound(RepositoryError):
    """Verilen user_id/item_id çiftine ait kalem yok."""


class InventoryRepository(Protocol):
    def acquire_idempotency_lock(self, bucket: str, key: str, etag: str) -> None:
        """Kilit alınamazsa `IdempotencyConflict` fırlatır."""
        ...

    def put_upload(self, record: UploadRecord) -> None: ...

    def get_upload(self, upload_id: str) -> UploadRecord | None: ...

    def mark_upload_processing(self, upload_id: str) -> None: ...

    def mark_upload_failed(self, upload_id: str, error_code: str) -> None: ...

    def commit_extraction(self, observation: Observation, items: list[InventoryItem]) -> None:
        """Observation + N Item + UploadStatus=COMPLETED tek atomik yazım.

        Ya hepsi yazılır ya hiçbiri — yarım işlenmiş durum oluşmaz. Bu olmadan,
        Lambda Observation'ı yazıp Item'lardan önce çökerse, idempotency kilidi
        zaten alınmış olduğu için bir yeniden deneme "zaten işlendi" sanıp atlar
        ve UploadStatus sonsuza dek PROCESSING'te kalır.
        """
        ...

    def list_active_items(self, user_id: str, limit: int = 100) -> list[InventoryItem]:
        """GSI1'den tazelik tarihine göre artan sırada."""
        ...

    def get_items(self, user_id: str, item_ids: list[str]) -> list[InventoryItem]:
        """Belirli id'lere ait kalemler — `GET /v1/uploads/{id}` yanıtı için.

        `item_ids` genelde tek bir fotoğraftan çıkan birkaç üründür; tek tek
        `get_item` yeterli, `batch_get_item`'ın eklediği karmaşıklığa değmez.
        """
        ...

    def update_item(self, user_id: str, item_id: str, changes: dict) -> InventoryItem:
        """`changes` içindeki alanlar üzerine yazılır; `state` değişirse GSI1
        anahtarları buna göre SET veya REMOVE edilir. Kalem yoksa `ItemNotFound`.
        """
        ...

    def delete_item(self, user_id: str, item_id: str) -> None: ...


# --- (De)serileştirme yardımcıları ---
#
# DynamoDB'nin resource API'si Python float kabul etmez (Decimal ister).
# Enum'lar StrEnum olsa da niyeti kodda görünür kılmak için açıkça .value
# kullanılır.


def _dt_to_str(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_DT_FORMAT)


def _str_to_dt(value: str) -> datetime:
    return datetime.strptime(value, _DT_FORMAT).replace(tzinfo=UTC)


def _quantity_to_dict(quantity: Quantity) -> dict:
    return asdict(quantity)


def _quantity_from_dict(data: dict) -> Quantity:
    return Quantity(value=int(data["value"]), unit=data["unit"])


def _confidence_to_dict(confidence: FieldConfidence) -> dict:
    return {
        "name": Decimal(str(round(confidence.name, 4))),
        "category": Decimal(str(round(confidence.category, 4))),
    }


def _confidence_from_dict(data: dict) -> FieldConfidence:
    return FieldConfidence(name=float(data["name"]), category=float(data["category"]))


def _extracted_food_to_dict(food: ExtractedFood) -> dict:
    return {
        "name": food.name,
        "raw_label": food.raw_label,
        "brand": food.brand,
        "category": food.category.value,
        "subcategory": food.subcategory,
        "package_state": food.package_state.value,
        "quantity": _quantity_to_dict(food.quantity),
        "confidence": _confidence_to_dict(food.confidence),
    }


def _serialize_observation(observation: Observation) -> dict:
    return {
        "PK": user_pk(observation.user_id),
        "SK": observation_sk(observation.captured_at, observation.observation_id),
        "entity_type": "OBSERVATION",
        "observation_id": observation.observation_id,
        "user_id": observation.user_id,
        "upload_id": observation.upload_id,
        "captured_at": _dt_to_str(observation.captured_at),
        "source_bucket": observation.source_bucket,
        "source_key": observation.source_key,
        "model_id": observation.model_id,
        "prompt_version": observation.prompt_version,
        "latency_ms": observation.latency_ms,
        "warnings": list(observation.warnings),
        "foods": [_extracted_food_to_dict(f) for f in observation.foods],
        "schema_version": observation.schema_version,
    }


def _serialize_item(item: InventoryItem) -> dict:
    row = {
        "PK": user_pk(item.user_id),
        "SK": item_sk(item.item_id),
        "entity_type": "ITEM",
        "item_id": item.item_id,
        "user_id": item.user_id,
        "name": item.name,
        "brand": item.brand,
        "raw_label": item.raw_label,
        "category": item.category.value,
        "subcategory": item.subcategory,
        "package_state": item.package_state.value,
        "quantity": _quantity_to_dict(item.quantity),
        "estimated_freshness_date": item.estimated_freshness_date.isoformat(),
        "freshness_basis": item.freshness_basis.value,
        "created_at": _dt_to_str(item.created_at),
        "updated_at": _dt_to_str(item.updated_at),
        "observation_id": item.observation_id,
        "state": item.state.value,
        "confidence": _confidence_to_dict(item.confidence) if item.confidence else None,
        "needs_review": item.needs_review,
        "schema_version": item.schema_version,
    }
    row.update(gsi1_keys(item.user_id, item))
    return row


def _deserialize_item(data: dict) -> InventoryItem:
    confidence_raw = data.get("confidence")
    return InventoryItem(
        item_id=data["item_id"],
        user_id=data["user_id"],
        name=data["name"],
        brand=data.get("brand"),
        raw_label=data.get("raw_label"),
        category=FoodCategory(data["category"]),
        subcategory=data.get("subcategory"),
        package_state=PackageState(data["package_state"]),
        quantity=_quantity_from_dict(data["quantity"]),
        estimated_freshness_date=date.fromisoformat(data["estimated_freshness_date"]),
        freshness_basis=FreshnessBasis(data["freshness_basis"]),
        created_at=_str_to_dt(data["created_at"]),
        updated_at=_str_to_dt(data["updated_at"]),
        observation_id=data["observation_id"],
        state=ItemState(data["state"]),
        confidence=_confidence_from_dict(confidence_raw) if confidence_raw else None,
        needs_review=bool(data.get("needs_review", False)),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


def _serialize_upload(record: UploadRecord) -> dict:
    return {
        **upload_keys(record.upload_id),
        "entity_type": "UPLOAD",
        "upload_id": record.upload_id,
        "user_id": record.user_id,
        "status": record.status.value,
        "created_at": _dt_to_str(record.created_at),
        "object_key": record.object_key,
        "observation_id": record.observation_id,
        "item_ids": list(record.item_ids),
        "error_code": record.error_code,
        "schema_version": record.schema_version,
        "expires_at": int(record.created_at.timestamp()) + _TTL_SECONDS,
    }


def _deserialize_upload(data: dict) -> UploadRecord:
    return UploadRecord(
        upload_id=data["upload_id"],
        user_id=data["user_id"],
        status=UploadStatus(data["status"]),
        created_at=_str_to_dt(data["created_at"]),
        object_key=data["object_key"],
        observation_id=data.get("observation_id"),
        item_ids=tuple(data.get("item_ids") or ()),
        error_code=data.get("error_code"),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


#: PATCH /v1/items/{id} ile değiştirilebilen tek alanlar. Beyaz liste —
#: `changes` dict'i istek gövdesinden geliyor, rastgele alan yazımına izin
#: vermemek temel bir savunma önlemi.
UPDATABLE_ITEM_FIELDS = frozenset(
    {"name", "brand", "category", "subcategory", "package_state", "quantity", "state"}
)


class DynamoRepository:
    """Tek tablo `fridge-main` uygulaması.

    `table` bir boto3 DynamoDB resource `Table` nesnesidir (dependency
    injection) — moto ile test edilebilsin diye handler bunu dışarıdan verir.
    """

    def __init__(self, table) -> None:  # noqa: ANN001
        self._table = table
        self._table_name = table.name
        self._client = table.meta.client

    def acquire_idempotency_lock(self, bucket: str, key: str, etag: str) -> None:
        lock_key = idempotency_key(bucket, key, etag)
        try:
            self._table.put_item(
                Item={**lock_key, "expires_at": int(time.time()) + _TTL_SECONDS},
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise IdempotencyConflict(f"{bucket}/{key} zaten işlenmiş") from exc
            raise

    def put_upload(self, record: UploadRecord) -> None:
        self._table.put_item(Item=_serialize_upload(record))

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        response = self._table.get_item(Key=upload_keys(upload_id))
        item = response.get("Item")
        return _deserialize_upload(item) if item else None

    def mark_upload_processing(self, upload_id: str) -> None:
        self._table.update_item(
            Key=upload_keys(upload_id),
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": UploadStatus.PROCESSING.value},
        )

    def mark_upload_failed(self, upload_id: str, error_code: str) -> None:
        self._table.update_item(
            Key=upload_keys(upload_id),
            UpdateExpression="SET #s = :s, error_code = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": UploadStatus.FAILED.value, ":e": error_code},
        )

    def commit_extraction(self, observation: Observation, items: list[InventoryItem]) -> None:
        # `table.meta.client`, native Python -> DynamoDB tip dönüşümünü üzerinde
        # taşıyan client'tır. Bu yüzden Item ve ExpressionAttributeValues'a
        # native değerler veriliyor; elle `{"S": ...}` sarmalamak burada yanlış
        # ve moto altında sessizce bozuk bir transaction'a yol açar (native değer
        # bekleyen dönüşüm katmanı, zaten sarmalanmış değeri bir kez daha sarmalar).
        transact_items = [
            {"Put": {"TableName": self._table_name, "Item": _serialize_observation(observation)}},
            *(
                {"Put": {"TableName": self._table_name, "Item": _serialize_item(item)}}
                for item in items
            ),
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": upload_keys(observation.upload_id),
                    "UpdateExpression": "SET #s = :s, observation_id = :oid, item_ids = :ids",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":s": UploadStatus.COMPLETED.value,
                        ":oid": observation.observation_id,
                        ":ids": [item.item_id for item in items],
                    },
                }
            },
        ]
        self._client.transact_write_items(TransactItems=transact_items)

    def list_active_items(self, user_id: str, limit: int = 100) -> list[InventoryItem]:
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_id}#ACTIVE"),
            ScanIndexForward=True,
            Limit=limit,
        )
        return [_deserialize_item(item) for item in response.get("Items", [])]

    def get_items(self, user_id: str, item_ids: list[str]) -> list[InventoryItem]:
        items = []
        for item_id in item_ids:
            response = self._table.get_item(Key={"PK": user_pk(user_id), "SK": item_sk(item_id)})
            raw = response.get("Item")
            if raw is not None:
                items.append(_deserialize_item(raw))
        return items

    def update_item(self, user_id: str, item_id: str, changes: dict) -> InventoryItem:
        unknown = set(changes) - UPDATABLE_ITEM_FIELDS
        if unknown:
            raise RepositoryError(f"Güncellenemeyen alanlar: {sorted(unknown)}")

        key = {"PK": user_pk(user_id), "SK": item_sk(item_id)}
        current = self._table.get_item(Key=key).get("Item")
        if current is None:
            raise ItemNotFound(f"Kalem bulunamadı: {item_id}")

        merged = {**current, **changes, "updated_at": _dt_to_str(datetime.now(UTC))}
        item = _deserialize_item(merged)
        new_gsi1 = gsi1_keys(user_id, item)

        # Her alan adı alias'lanır (ör. "#f0"), çıplak yazılmaz: DynamoDB'nin
        # ayrılmış kelime listesi geniştir ve "name" ile "state" — PATCH'in en
        # sık değiştirdiği iki alan — ikisi de bu listede.
        expr_names = {"#state": "state"}
        expr_values = {":state": item.state.value, ":updated_at": merged["updated_at"]}
        set_parts = ["#state = :state", "updated_at = :updated_at"]

        for index, field in enumerate(f for f in changes if f != "state"):
            alias = f"#f{index}"
            expr_names[alias] = field
            expr_values[f":{field}"] = merged[field]
            set_parts.append(f"{alias} = :{field}")

        remove_parts: list[str] = []
        if new_gsi1:
            set_parts += ["GSI1PK = :gsi1pk", "GSI1SK = :gsi1sk"]
            expr_values[":gsi1pk"] = new_gsi1["GSI1PK"]
            expr_values[":gsi1sk"] = new_gsi1["GSI1SK"]
        else:
            remove_parts = ["GSI1PK", "GSI1SK"]

        update_expression = "SET " + ", ".join(set_parts)
        if remove_parts:
            update_expression += " REMOVE " + ", ".join(remove_parts)

        self._table.update_item(
            Key=key,
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        return item

    def delete_item(self, user_id: str, item_id: str) -> None:
        self._table.delete_item(Key={"PK": user_pk(user_id), "SK": item_sk(item_id)})
