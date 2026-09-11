"""Kalıcılık soyutlaması + DynamoDB uygulaması (tek tablo `fridge-main`).

Veri partition'ı buzdolabı bazındadır (hane modeli): envanter, gözlem, swipe
olayı, değerlendirme, alışveriş ve öneriler `FRIDGE#{fridge_id}` altında toplanır.
Profil/cihaz kullanıcıya (`USER#{user_id}`) bağlıdır. Anahtar üretimi
`core/inventory.py`'de; bu dosya yalnızca "o anahtarları nasıl yazarım/okurum"
sorusunu cevaplar. Tablo yalnızca `query`/`get_item` ile okunur, `scan` yok.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from core.inventory import (
    action_sk,
    assessment_sk,
    candidate_sk,
    client_action_keys,
    device_sk,
    fridge_meta_keys,
    fridge_pk,
    gsi1_keys,
    idempotency_key,
    item_sk,
    new_id,
    observation_sk,
    profile_keys,
    reminder_sk,
    shopping_sk,
    upload_keys,
    user_pk,
)
from core.models import (
    SCHEMA_VERSION,
    BoundingBox,
    DeviceRegistration,
    DiscardReason,
    ExtractedFood,
    FieldConfidence,
    FreshnessAssessment,
    FreshnessAssessmentReason,
    FreshnessBasis,
    FridgeRegistryEntry,
    FridgeStatus,
    InventoryItem,
    ItemReminder,
    ItemState,
    NotificationMode,
    NotificationPreferences,
    Observation,
    ObservedFreshnessState,
    Quantity,
    ReplacementCandidate,
    ReplacementCandidateStatus,
    ShoppingItemState,
    ShoppingListItem,
    SwipeAction,
    SwipeActionType,
    UploadRecord,
    UploadStatus,
    UserProfile,
)
from core.taxonomy import FoodCategory, PackageState

#: Geçici kayıtlar (idempotency kilidi, upload durumu) 7 gün sonra TTL ile silinir.
_TTL_SECONDS = 7 * 86400
_DT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RepositoryError(RuntimeError):
    pass


class IdempotencyConflict(RepositoryError):
    """Bu S3 olayı zaten işlenmiş. Çağıran taraf sessizce çıkmalı."""


class ItemNotFound(RepositoryError):
    """Verilen fridge/item çiftine ait kalem yok."""


class ConflictError(RepositoryError):
    """Kayıt beklenen durumda değil (ör. zaten kabul edilmiş öneri)."""


# --- (De)serileştirme yardımcıları ---


def _dt_to_str(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_DT_FORMAT)


def _str_to_dt(value: str) -> datetime:
    return datetime.strptime(value, _DT_FORMAT).replace(tzinfo=UTC)


def _opt_dt_to_str(value: datetime | None) -> str | None:
    return _dt_to_str(value) if value else None


def _opt_dt(value: object) -> datetime | None:
    return _str_to_dt(value) if isinstance(value, str) and value else None


def _opt_date_to_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _opt_date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _quantity_to_dict(quantity: Quantity) -> dict:
    return asdict(quantity)


def _quantity_from_dict(data: object) -> Quantity | None:
    if not isinstance(data, dict):
        return None
    return Quantity(value=int(data["value"]), unit=data["unit"])


def _confidence_to_dict(confidence: FieldConfidence) -> dict:
    return {
        "name": Decimal(str(round(confidence.name, 4))),
        "category": Decimal(str(round(confidence.category, 4))),
    }


def _confidence_from_dict(data: dict) -> FieldConfidence:
    return FieldConfidence(name=float(data["name"]), category=float(data["category"]))


def _bounding_box_to_dict(box: BoundingBox | None) -> dict | None:
    if box is None:
        return None
    return {"ymin": box.ymin, "xmin": box.xmin, "ymax": box.ymax, "xmax": box.xmax}


def _bounding_box_from_dict(data: object) -> BoundingBox | None:
    if not isinstance(data, dict):
        return None
    return BoundingBox(
        ymin=int(data["ymin"]),
        xmin=int(data["xmin"]),
        ymax=int(data["ymax"]),
        xmax=int(data["xmax"]),
    )


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
        "bounding_box": _bounding_box_to_dict(food.bounding_box),
    }


# --- Observation ---


def _serialize_observation(observation: Observation) -> dict:
    return {
        "PK": fridge_pk(observation.fridge_id),
        "SK": observation_sk(observation.captured_at, observation.observation_id),
        "entity_type": "OBSERVATION",
        "observation_id": observation.observation_id,
        "user_id": observation.user_id,
        "fridge_id": observation.fridge_id,
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


# --- InventoryItem ---


def _serialize_item(item: InventoryItem) -> dict:
    row = {
        "PK": fridge_pk(item.fridge_id),
        "SK": item_sk(item.item_id),
        "entity_type": "ITEM",
        "item_id": item.item_id,
        "fridge_id": item.fridge_id,
        "user_id": item.user_id,
        "name": item.name,
        "brand": item.brand,
        "raw_label": item.raw_label,
        "category": item.category.value,
        "subcategory": item.subcategory,
        "package_state": item.package_state.value,
        "quantity": _quantity_to_dict(item.quantity),
        "estimated_freshness_date": item.estimated_freshness_date.isoformat(),
        "user_adjusted_freshness_date": _opt_date_to_str(item.user_adjusted_freshness_date),
        "freshness_basis": item.freshness_basis.value,
        "created_at": _dt_to_str(item.created_at),
        "updated_at": _dt_to_str(item.updated_at),
        "observation_id": item.observation_id,
        "state": item.state.value,
        "confidence": _confidence_to_dict(item.confidence) if item.confidence else None,
        "needs_review": item.needs_review,
        "bounding_box": _bounding_box_to_dict(item.bounding_box),
        "last_reviewed_at": _opt_dt_to_str(item.last_reviewed_at),
        "next_review_at": _opt_dt_to_str(item.next_review_at),
        "user_requested_review": item.user_requested_review,
        "image_ref": item.image_ref,
        "version": item.version,
        "schema_version": item.schema_version,
    }
    row.update(gsi1_keys(item.fridge_id, item))
    return row


def _deserialize_item(data: dict) -> InventoryItem:
    confidence_raw = data.get("confidence")
    return InventoryItem(
        item_id=data["item_id"],
        fridge_id=data["fridge_id"],
        user_id=data["user_id"],
        name=data["name"],
        brand=data.get("brand"),
        raw_label=data.get("raw_label"),
        category=FoodCategory(data["category"]),
        subcategory=data.get("subcategory"),
        package_state=PackageState(data["package_state"]),
        quantity=_quantity_from_dict(data["quantity"]) or Quantity(value=1),
        estimated_freshness_date=date.fromisoformat(data["estimated_freshness_date"]),
        user_adjusted_freshness_date=_opt_date(data.get("user_adjusted_freshness_date")),
        freshness_basis=FreshnessBasis(data["freshness_basis"]),
        created_at=_str_to_dt(data["created_at"]),
        updated_at=_str_to_dt(data["updated_at"]),
        observation_id=data["observation_id"],
        state=ItemState(data["state"]),
        confidence=_confidence_from_dict(confidence_raw) if confidence_raw else None,
        needs_review=bool(data.get("needs_review", False)),
        bounding_box=_bounding_box_from_dict(data.get("bounding_box")),
        last_reviewed_at=_opt_dt(data.get("last_reviewed_at")),
        next_review_at=_opt_dt(data.get("next_review_at")),
        user_requested_review=bool(data.get("user_requested_review", False)),
        image_ref=data.get("image_ref"),
        version=int(data.get("version", 1)),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- UploadRecord ---


def _serialize_upload(record: UploadRecord) -> dict:
    return {
        **upload_keys(record.upload_id),
        "entity_type": "UPLOAD",
        "upload_id": record.upload_id,
        "user_id": record.user_id,
        "fridge_id": record.fridge_id,
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
        fridge_id=data["fridge_id"],
        status=UploadStatus(data["status"]),
        created_at=_str_to_dt(data["created_at"]),
        object_key=data["object_key"],
        observation_id=data.get("observation_id"),
        item_ids=tuple(data.get("item_ids") or ()),
        error_code=data.get("error_code"),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- Fridge registry & UserProfile ---


def _serialize_fridge(entry: FridgeRegistryEntry) -> dict:
    return {
        **fridge_meta_keys(entry.fridge_id),
        "entity_type": "FRIDGE",
        "fridge_id": entry.fridge_id,
        "label": entry.label,
        "status": entry.status.value,
        "created_at": _dt_to_str(entry.created_at),
    }


def _deserialize_fridge(data: dict) -> FridgeRegistryEntry:
    return FridgeRegistryEntry(
        fridge_id=data["fridge_id"],
        label=data.get("label", ""),
        status=FridgeStatus(data["status"]),
        created_at=_str_to_dt(data["created_at"]),
    )


def _prefs_to_dict(prefs: NotificationPreferences) -> dict:
    return {
        "mode": prefs.mode.value,
        "digest_time": prefs.digest_time,
        "quiet_hours_start": prefs.quiet_hours_start,
        "quiet_hours_end": prefs.quiet_hours_end,
        "timezone_id": prefs.timezone_id,
    }


def _prefs_from_dict(data: object) -> NotificationPreferences:
    if not isinstance(data, dict):
        return NotificationPreferences()
    return NotificationPreferences(
        mode=NotificationMode(data.get("mode", NotificationMode.DAILY_DIGEST.value)),
        digest_time=data.get("digest_time", "18:30"),
        quiet_hours_start=data.get("quiet_hours_start"),
        quiet_hours_end=data.get("quiet_hours_end"),
        timezone_id=data.get("timezone_id", "Europe/Istanbul"),
    )


def _serialize_profile(profile: UserProfile) -> dict:
    return {
        **profile_keys(profile.user_id),
        "entity_type": "PROFILE",
        "user_id": profile.user_id,
        "fridge_id": profile.fridge_id,
        "display_name": profile.display_name,
        "created_at": _dt_to_str(profile.created_at),
        "updated_at": _dt_to_str(profile.updated_at),
        "notification_preferences": _prefs_to_dict(profile.notification_preferences),
        "schema_version": profile.schema_version,
    }


def _deserialize_profile(data: dict) -> UserProfile:
    return UserProfile(
        user_id=data["user_id"],
        fridge_id=data["fridge_id"],
        display_name=data["display_name"],
        created_at=_str_to_dt(data["created_at"]),
        updated_at=_str_to_dt(data["updated_at"]),
        notification_preferences=_prefs_from_dict(data.get("notification_preferences")),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- SwipeAction ---


def _serialize_action(action: SwipeAction) -> dict:
    return {
        "PK": fridge_pk(action.fridge_id),
        "SK": action_sk(action.action_id),
        "entity_type": "ACTION",
        "action_id": action.action_id,
        "client_action_id": action.client_action_id,
        "fridge_id": action.fridge_id,
        "item_id": action.item_id,
        "user_id": action.user_id,
        "type": action.type.value,
        "occurred_at": _dt_to_str(action.occurred_at),
        "previous_item_state": action.previous_item_state.value,
        "discard_reason": action.discard_reason.value if action.discard_reason else None,
        "reverted_at": _opt_dt_to_str(action.reverted_at),
        "replacement_candidate_id": action.replacement_candidate_id,
        "schema_version": action.schema_version,
    }


def _deserialize_action(data: dict) -> SwipeAction:
    reason = data.get("discard_reason")
    return SwipeAction(
        action_id=data["action_id"],
        client_action_id=data["client_action_id"],
        fridge_id=data["fridge_id"],
        item_id=data["item_id"],
        user_id=data["user_id"],
        type=SwipeActionType(data["type"]),
        occurred_at=_str_to_dt(data["occurred_at"]),
        previous_item_state=ItemState(data["previous_item_state"]),
        discard_reason=DiscardReason(reason) if reason else None,
        reverted_at=_opt_dt(data.get("reverted_at")),
        replacement_candidate_id=data.get("replacement_candidate_id"),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- FreshnessAssessment ---


def _serialize_assessment(a: FreshnessAssessment) -> dict:
    return {
        "PK": fridge_pk(a.fridge_id),
        "SK": assessment_sk(a.assessed_at, a.assessment_id),
        "entity_type": "ASSESSMENT",
        "assessment_id": a.assessment_id,
        "fridge_id": a.fridge_id,
        "item_id": a.item_id,
        "user_id": a.user_id,
        "assessed_at": _dt_to_str(a.assessed_at),
        "observed_state": a.observed_state.value,
        "system_predicted_fresh_until_before": a.system_predicted_fresh_until_before.isoformat(),
        "rule_version": a.rule_version,
        "user_estimated_days_remaining": a.user_estimated_days_remaining,
        "user_estimated_fresh_until": _opt_date_to_str(a.user_estimated_fresh_until),
        "next_review_at": _opt_dt_to_str(a.next_review_at),
        "reason": a.reason.value if a.reason else None,
        "source": a.source,
        "schema_version": a.schema_version,
        # Idempotency: assessment_id ile aynı değerlendirme iki kez yazılmaz.
        "assessment_ref": a.assessment_id,
    }


def _deserialize_assessment(data: dict) -> FreshnessAssessment:
    reason = data.get("reason")
    days = data.get("user_estimated_days_remaining")
    return FreshnessAssessment(
        assessment_id=data["assessment_id"],
        fridge_id=data["fridge_id"],
        item_id=data["item_id"],
        user_id=data["user_id"],
        assessed_at=_str_to_dt(data["assessed_at"]),
        observed_state=ObservedFreshnessState(data["observed_state"]),
        system_predicted_fresh_until_before=date.fromisoformat(
            data["system_predicted_fresh_until_before"]
        ),
        rule_version=data["rule_version"],
        user_estimated_days_remaining=int(days) if days is not None else None,
        user_estimated_fresh_until=_opt_date(data.get("user_estimated_fresh_until")),
        next_review_at=_opt_dt(data.get("next_review_at")),
        reason=FreshnessAssessmentReason(reason) if reason else None,
        source=data.get("source", "USER"),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- ReplacementCandidate ---


def _serialize_candidate(c: ReplacementCandidate) -> dict:
    return {
        "PK": fridge_pk(c.fridge_id),
        "SK": candidate_sk(c.candidate_id),
        "entity_type": "CANDIDATE",
        "candidate_id": c.candidate_id,
        "fridge_id": c.fridge_id,
        "source_item_id": c.source_item_id,
        "source_action_id": c.source_action_id,
        "name": c.name,
        "category": c.category.value,
        "reason": c.reason.value,
        "status": c.status.value,
        "created_at": _dt_to_str(c.created_at),
        "suggested_quantity": _quantity_to_dict(c.suggested_quantity)
        if c.suggested_quantity
        else None,
        "schema_version": c.schema_version,
    }


def _deserialize_candidate(data: dict) -> ReplacementCandidate:
    return ReplacementCandidate(
        candidate_id=data["candidate_id"],
        fridge_id=data["fridge_id"],
        source_item_id=data["source_item_id"],
        source_action_id=data["source_action_id"],
        name=data["name"],
        category=FoodCategory(data["category"]),
        reason=SwipeActionType(data["reason"]),
        status=ReplacementCandidateStatus(data["status"]),
        created_at=_str_to_dt(data["created_at"]),
        suggested_quantity=_quantity_from_dict(data.get("suggested_quantity")),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- ShoppingListItem ---


def _serialize_shopping(s: ShoppingListItem) -> dict:
    return {
        "PK": fridge_pk(s.fridge_id),
        "SK": shopping_sk(s.shopping_item_id),
        "entity_type": "SHOPPING",
        "shopping_item_id": s.shopping_item_id,
        "fridge_id": s.fridge_id,
        "name": s.name,
        "state": s.state.value,
        "category": s.category.value if s.category else None,
        "quantity": _quantity_to_dict(s.quantity) if s.quantity else None,
        "source_candidate_id": s.source_candidate_id,
        "note": s.note,
        "created_at": _dt_to_str(s.created_at),
        "updated_at": _dt_to_str(s.updated_at),
        "schema_version": s.schema_version,
    }


def _deserialize_shopping(data: dict) -> ShoppingListItem:
    cat = data.get("category")
    return ShoppingListItem(
        shopping_item_id=data["shopping_item_id"],
        fridge_id=data["fridge_id"],
        name=data["name"],
        state=ShoppingItemState(data["state"]),
        category=FoodCategory(cat) if cat else None,
        quantity=_quantity_from_dict(data.get("quantity")),
        source_candidate_id=data.get("source_candidate_id"),
        note=data.get("note"),
        created_at=_str_to_dt(data["created_at"]),
        updated_at=_str_to_dt(data["updated_at"]),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# --- DeviceRegistration & ItemReminder ---


def _serialize_device(d: DeviceRegistration) -> dict:
    return {
        "PK": user_pk(d.user_id),
        "SK": device_sk(d.installation_id),
        "entity_type": "DEVICE",
        "installation_id": d.installation_id,
        "user_id": d.user_id,
        "push_token": d.push_token,
        "platform": d.platform,
        "created_at": _dt_to_str(d.created_at),
        "updated_at": _dt_to_str(d.updated_at),
        "schema_version": d.schema_version,
    }


def _serialize_reminder(r: ItemReminder) -> dict:
    return {
        "PK": fridge_pk(r.fridge_id),
        "SK": reminder_sk(r.item_id),
        "entity_type": "REMINDER",
        "item_id": r.item_id,
        "fridge_id": r.fridge_id,
        "scheduled_at": _dt_to_str(r.scheduled_at),
        "version": r.version,
        "enabled": r.enabled,
        "last_delivered_at": _opt_dt_to_str(r.last_delivered_at),
        "schema_version": r.schema_version,
    }


#: PATCH /v1/items/{id} ile değiştirilebilen alanlar (beyaz liste).
UPDATABLE_ITEM_FIELDS = frozenset(
    {"name", "brand", "category", "subcategory", "package_state", "quantity", "state"}
)

#: PATCH /v1/shopping-lists/current/items/{id} beyaz listesi.
UPDATABLE_SHOPPING_FIELDS = frozenset({"name", "category", "quantity", "state", "note"})


class InventoryRepository(Protocol):
    def acquire_idempotency_lock(self, bucket: str, key: str, etag: str) -> None: ...
    def put_upload(self, record: UploadRecord) -> None: ...
    def get_upload(self, upload_id: str) -> UploadRecord | None: ...
    def mark_upload_processing(self, upload_id: str) -> None: ...
    def mark_upload_failed(self, upload_id: str, error_code: str) -> None: ...
    def commit_extraction(self, observation: Observation, items: list[InventoryItem]) -> None: ...
    def list_active_items(self, fridge_id: str, limit: int = 100) -> list[InventoryItem]: ...
    def get_items(self, fridge_id: str, item_ids: list[str]) -> list[InventoryItem]: ...
    def update_item(self, fridge_id: str, item_id: str, changes: dict) -> InventoryItem: ...
    def delete_item(self, fridge_id: str, item_id: str) -> None: ...


class DynamoRepository:
    """Tek tablo `fridge-main` uygulaması. `table` boto3 DynamoDB resource Table."""

    def __init__(self, table) -> None:  # noqa: ANN001
        self._table = table
        self._table_name = table.name
        self._client = table.meta.client

    # --- Idempotency & upload (mevcut) ---

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

    # --- Fridge registry & profil ---

    def put_fridge(self, entry: FridgeRegistryEntry) -> None:
        self._table.put_item(Item=_serialize_fridge(entry))

    def get_fridge(self, fridge_id: str) -> FridgeRegistryEntry | None:
        item = self._table.get_item(Key=fridge_meta_keys(fridge_id)).get("Item")
        return _deserialize_fridge(item) if item else None

    def put_profile(self, profile: UserProfile) -> None:
        self._table.put_item(Item=_serialize_profile(profile))

    def get_profile(self, user_id: str) -> UserProfile | None:
        item = self._table.get_item(Key=profile_keys(user_id)).get("Item")
        return _deserialize_profile(item) if item else None

    def update_notification_preferences(
        self, user_id: str, prefs: NotificationPreferences
    ) -> UserProfile:
        key = profile_keys(user_id)
        current = self._table.get_item(Key=key).get("Item")
        if current is None:
            raise ItemNotFound(f"Profil bulunamadı: {user_id}")
        self._table.update_item(
            Key=key,
            UpdateExpression="SET notification_preferences = :p, updated_at = :u",
            ExpressionAttributeValues={
                ":p": _prefs_to_dict(prefs),
                ":u": _dt_to_str(datetime.now(UTC)),
            },
        )
        current["notification_preferences"] = _prefs_to_dict(prefs)
        current["updated_at"] = _dt_to_str(datetime.now(UTC))
        return _deserialize_profile(current)

    # --- Envanter okuma (fridge-scope) ---

    def list_active_items(self, fridge_id: str, limit: int = 100) -> list[InventoryItem]:
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"FRIDGE#{fridge_id}#ACTIVE"),
            ScanIndexForward=True,
            Limit=limit,
        )
        return [_deserialize_item(item) for item in response.get("Items", [])]

    def get_items(self, fridge_id: str, item_ids: list[str]) -> list[InventoryItem]:
        items = []
        for item_id in item_ids:
            response = self._table.get_item(
                Key={"PK": fridge_pk(fridge_id), "SK": item_sk(item_id)}
            )
            raw = response.get("Item")
            if raw is not None:
                items.append(_deserialize_item(raw))
        return items

    def _get_item_or_raise(self, fridge_id: str, item_id: str) -> InventoryItem:
        raw = self._table.get_item(Key={"PK": fridge_pk(fridge_id), "SK": item_sk(item_id)}).get(
            "Item"
        )
        if raw is None:
            raise ItemNotFound(f"Kalem bulunamadı: {item_id}")
        return _deserialize_item(raw)

    def update_item(self, fridge_id: str, item_id: str, changes: dict) -> InventoryItem:
        unknown = set(changes) - UPDATABLE_ITEM_FIELDS
        if unknown:
            raise RepositoryError(f"Güncellenemeyen alanlar: {sorted(unknown)}")

        key = {"PK": fridge_pk(fridge_id), "SK": item_sk(item_id)}
        current = self._table.get_item(Key=key).get("Item")
        if current is None:
            raise ItemNotFound(f"Kalem bulunamadı: {item_id}")

        now_str = _dt_to_str(datetime.now(UTC))
        merged = {**current, **changes, "updated_at": now_str}
        merged["version"] = int(current.get("version", 1)) + 1
        item = _deserialize_item(merged)
        new_gsi1 = gsi1_keys(fridge_id, item)

        expr_names = {"#state": "state"}
        expr_values = {
            ":state": item.state.value,
            ":updated_at": now_str,
            ":version": item.version,
        }
        set_parts = ["#state = :state", "updated_at = :updated_at", "version = :version"]

        for index, changed_field in enumerate(f for f in changes if f != "state"):
            alias = f"#f{index}"
            expr_names[alias] = changed_field
            expr_values[f":{changed_field}"] = merged[changed_field]
            set_parts.append(f"{alias} = :{changed_field}")

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

    def delete_item(self, fridge_id: str, item_id: str) -> None:
        self._table.delete_item(Key={"PK": fridge_pk(fridge_id), "SK": item_sk(item_id)})

    # --- Swipe aksiyonları (idempotent + atomik) ---

    def record_swipe_action(
        self,
        *,
        action: SwipeAction,
        new_item_state: ItemState,
        candidate: ReplacementCandidate | None,
        now: datetime,
    ) -> tuple[SwipeAction, ReplacementCandidate | None, InventoryItem]:
        """Idempotent + atomik swipe: kilit + olay + item durumu (+ öneri).

        Aynı `client_action_id` tekrar gelirse mevcut sonuç döner (BR-007).
        """
        item = self._get_item_or_raise(action.fridge_id, action.item_id)

        lock = client_action_keys(action.fridge_id, action.client_action_id)
        existing_lock = self._table.get_item(Key=lock).get("Item")
        if existing_lock is not None:
            # Duplicate: daha önce oluşturulan aksiyonu geri döndür.
            return self._replay_action(action.fridge_id, existing_lock["action_id"])

        action = SwipeAction(
            **{
                **{k: getattr(action, k) for k in action.__dataclass_fields__},
                "replacement_candidate_id": candidate.candidate_id if candidate else None,
            }
        )
        updated_item = self._apply_state_locally(item, new_item_state, now)

        transact_items: list[dict] = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": {
                        **lock,
                        "action_id": action.action_id,
                        "expires_at": int(time.time()) + _TTL_SECONDS,
                    },
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            {"Put": {"TableName": self._table_name, "Item": _serialize_action(action)}},
            {"Put": {"TableName": self._table_name, "Item": _serialize_item(updated_item)}},
        ]
        if candidate is not None:
            transact_items.append(
                {"Put": {"TableName": self._table_name, "Item": _serialize_candidate(candidate)}}
            )

        try:
            self._client.transact_write_items(TransactItems=transact_items)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                # Yarış: kilit bu arada alındıysa mevcut sonucu döndür.
                existing_lock = self._table.get_item(Key=lock).get("Item")
                if existing_lock is not None:
                    return self._replay_action(action.fridge_id, existing_lock["action_id"])
            raise
        return action, candidate, updated_item

    def _replay_action(
        self, fridge_id: str, action_id: str
    ) -> tuple[SwipeAction, ReplacementCandidate | None, InventoryItem]:
        action = self.get_action(fridge_id, action_id)
        if action is None:
            raise ConflictError(f"Idempotency kilidi var ama aksiyon yok: {action_id}")
        candidate = None
        if action.replacement_candidate_id:
            candidate = self.get_candidate(fridge_id, action.replacement_candidate_id)
        item = self._get_item_or_raise(fridge_id, action.item_id)
        return action, candidate, item

    @staticmethod
    def _apply_state_locally(
        item: InventoryItem, new_state: ItemState, now: datetime
    ) -> InventoryItem:
        item.state = new_state
        item.updated_at = now
        item.last_reviewed_at = now
        item.version += 1
        return item

    def get_action(self, fridge_id: str, action_id: str) -> SwipeAction | None:
        raw = self._table.get_item(
            Key={"PK": fridge_pk(fridge_id), "SK": action_sk(action_id)}
        ).get("Item")
        return _deserialize_action(raw) if raw else None

    def undo_action(self, fridge_id: str, action_id: str, now: datetime) -> SwipeAction:
        """Sağ/sol swipe'ı geri alır (BR-007): item eski duruma, öneri REVERTED."""
        action = self.get_action(fridge_id, action_id)
        if action is None:
            raise ItemNotFound(f"Aksiyon bulunamadı: {action_id}")
        if action.reverted_at is not None:
            return action  # zaten geri alınmış — idempotent

        item = self._get_item_or_raise(fridge_id, action.item_id)
        item.state = action.previous_item_state
        item.updated_at = now
        item.version += 1

        transact_items: list[dict] = [
            {"Put": {"TableName": self._table_name, "Item": _serialize_item(item)}},
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": {"PK": fridge_pk(fridge_id), "SK": action_sk(action_id)},
                    "UpdateExpression": "SET reverted_at = :r",
                    "ExpressionAttributeValues": {":r": _dt_to_str(now)},
                }
            },
        ]
        if action.replacement_candidate_id:
            transact_items.append(
                {
                    "Update": {
                        "TableName": self._table_name,
                        "Key": {
                            "PK": fridge_pk(fridge_id),
                            "SK": candidate_sk(action.replacement_candidate_id),
                        },
                        "UpdateExpression": "SET #s = :s",
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {
                            ":s": ReplacementCandidateStatus.REVERTED.value
                        },
                    }
                }
            )
        self._client.transact_write_items(TransactItems=transact_items)
        return _deserialize_action({**_serialize_action(action), "reverted_at": _dt_to_str(now)})

    # --- Freshness assessment (atomik: olay + item düzeltmesi) ---

    def record_assessment(
        self, assessment: FreshnessAssessment, item_updates: dict, now: datetime
    ) -> tuple[FreshnessAssessment, InventoryItem]:
        """Değerlendirme olayını yazar ve item'ın kullanıcı alanlarını günceller.

        Sistem tahmini (`estimated_freshness_date`) DEĞİŞMEZ (BR-009). Yalnızca
        `user_adjusted_freshness_date`, `next_review_at`, `last_reviewed_at`
        güncellenir; effective tarih değişince GSI1 anahtarı da güncellenir.
        """
        item = self._get_item_or_raise(assessment.fridge_id, assessment.item_id)

        # Duplicate assessment_id: aynı olay iki kez yazılmaz.
        existing = self._table.get_item(
            Key={
                "PK": fridge_pk(assessment.fridge_id),
                "SK": assessment_sk(assessment.assessed_at, assessment.assessment_id),
            }
        ).get("Item")
        if existing is not None:
            return _deserialize_assessment(existing), item

        for field_name, value in item_updates.items():
            setattr(item, field_name, value)
        item.last_reviewed_at = now
        item.updated_at = now
        item.version += 1

        transact_items = [
            {"Put": {"TableName": self._table_name, "Item": _serialize_assessment(assessment)}},
            {"Put": {"TableName": self._table_name, "Item": _serialize_item(item)}},
        ]
        self._client.transact_write_items(TransactItems=transact_items)
        return assessment, item

    # --- Replacement candidates ---

    def list_candidates(
        self, fridge_id: str, status: ReplacementCandidateStatus | None = None
    ) -> list[ReplacementCandidate]:
        response = self._table.query(
            KeyConditionExpression=Key("PK").eq(fridge_pk(fridge_id))
            & Key("SK").begins_with("CAND#")
        )
        candidates = [_deserialize_candidate(i) for i in response.get("Items", [])]
        if status is not None:
            candidates = [c for c in candidates if c.status is status]
        return candidates

    def get_candidate(self, fridge_id: str, candidate_id: str) -> ReplacementCandidate | None:
        raw = self._table.get_item(
            Key={"PK": fridge_pk(fridge_id), "SK": candidate_sk(candidate_id)}
        ).get("Item")
        return _deserialize_candidate(raw) if raw else None

    def accept_candidate(
        self, fridge_id: str, candidate_id: str, now: datetime
    ) -> ShoppingListItem:
        """Öneriyi kabul eder: durum ACCEPTED + alışveriş listesine kalem ekler."""
        candidate = self.get_candidate(fridge_id, candidate_id)
        if candidate is None:
            raise ItemNotFound(f"Öneri bulunamadı: {candidate_id}")
        if candidate.status is not ReplacementCandidateStatus.PENDING:
            raise ConflictError(f"Öneri {candidate.status.value} durumunda; kabul edilemez")

        shopping = ShoppingListItem(
            shopping_item_id=new_id("shop"),
            fridge_id=fridge_id,
            name=candidate.name,
            state=ShoppingItemState.ACTIVE,
            category=candidate.category,
            quantity=candidate.suggested_quantity,
            source_candidate_id=candidate_id,
            note=None,
            created_at=now,
            updated_at=now,
        )
        transact_items = [
            {"Put": {"TableName": self._table_name, "Item": _serialize_shopping(shopping)}},
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": {"PK": fridge_pk(fridge_id), "SK": candidate_sk(candidate_id)},
                    "UpdateExpression": "SET #s = :s",
                    "ExpressionAttributeNames": {"#s": "status"},
                    # Koşul: yalnızca hâlâ PENDING ise kabul et (çift kabulü önler).
                    "ConditionExpression": "#s = :pending",
                    "ExpressionAttributeValues": {
                        ":s": ReplacementCandidateStatus.ACCEPTED.value,
                        ":pending": ReplacementCandidateStatus.PENDING.value,
                    },
                }
            },
        ]
        self._client.transact_write_items(TransactItems=transact_items)
        return shopping

    def dismiss_candidate(self, fridge_id: str, candidate_id: str) -> None:
        try:
            self._table.update_item(
                Key={"PK": fridge_pk(fridge_id), "SK": candidate_sk(candidate_id)},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": ReplacementCandidateStatus.DISMISSED.value},
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ItemNotFound(f"Öneri bulunamadı: {candidate_id}") from exc
            raise

    # --- Shopping list ---

    def list_shopping(self, fridge_id: str) -> list[ShoppingListItem]:
        response = self._table.query(
            KeyConditionExpression=Key("PK").eq(fridge_pk(fridge_id))
            & Key("SK").begins_with("SHOP#")
        )
        return [_deserialize_shopping(i) for i in response.get("Items", [])]

    def put_shopping(self, item: ShoppingListItem) -> None:
        self._table.put_item(Item=_serialize_shopping(item))

    def update_shopping(
        self, fridge_id: str, shopping_item_id: str, changes: dict
    ) -> ShoppingListItem:
        unknown = set(changes) - UPDATABLE_SHOPPING_FIELDS
        if unknown:
            raise RepositoryError(f"Güncellenemeyen alanlar: {sorted(unknown)}")
        key = {"PK": fridge_pk(fridge_id), "SK": shopping_sk(shopping_item_id)}
        current = self._table.get_item(Key=key).get("Item")
        if current is None:
            raise ItemNotFound(f"Alışveriş kalemi bulunamadı: {shopping_item_id}")
        merged = {**current, **changes, "updated_at": _dt_to_str(datetime.now(UTC))}
        self._table.put_item(Item={**merged, **key, "entity_type": "SHOPPING"})
        return _deserialize_shopping({**merged, **key})

    def delete_shopping(self, fridge_id: str, shopping_item_id: str) -> None:
        self._table.delete_item(
            Key={"PK": fridge_pk(fridge_id), "SK": shopping_sk(shopping_item_id)}
        )

    # --- Devices & reminders ---

    def put_device(self, device: DeviceRegistration) -> None:
        self._table.put_item(Item=_serialize_device(device))

    def delete_device(self, user_id: str, installation_id: str) -> None:
        self._table.delete_item(Key={"PK": user_pk(user_id), "SK": device_sk(installation_id)})

    def put_reminder(self, reminder: ItemReminder) -> None:
        self._table.put_item(Item=_serialize_reminder(reminder))

    def delete_reminder(self, fridge_id: str, item_id: str) -> None:
        self._table.delete_item(Key={"PK": fridge_pk(fridge_id), "SK": reminder_sk(item_id)})
