"""fridge-api Lambda'sının tek CDK `handler=` referansı burasıdır.

Mobil ve web istemcinin tüm veri rotaları bu tek fonksiyona düşer ve buradan
içeride dağıtılır (rota başına Lambda soğuk başlangıç ve CDK yüzeyini gereksiz
büyütürdü). Kimlik doğrulanmış JWT `sub`'tan gelir; veri buzdolabı bazında
partition'lanır (hane modeli) ve her istek `handlers.context.resolve_context`
ile kullanıcının dolabına çözülür.

Handler kuralı: event'i parse et, core'u çağır, repository'yi çağır, sonucu yaz.
İş mantığı `core/`'da; buraya yazma.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime

import boto3

from adapters.repository import (
    ConflictError,
    DynamoRepository,
    ItemNotFound,
    RepositoryError,
)
from core.actions import build_replacement_candidate, build_swipe_action, resulting_item_state
from core.inventory import new_id
from core.models import (
    DeviceRegistration,
    DiscardReason,
    FoodCategory,
    FreshnessAssessment,
    FreshnessAssessmentReason,
    ItemReminder,
    ItemState,
    NotificationMode,
    NotificationPreferences,
    ObservedFreshnessState,
    PackageState,
    Quantity,
    ReplacementCandidateStatus,
    ShoppingItemState,
    ShoppingListItem,
    SwipeActionType,
    UploadStatus,
    UserProfile,
)
from core.recipes import dataset_version, recommend
from core.review import compute_review_queue
from handlers import dto
from handlers._http import (
    json_body,
    path_param,
    respond,
    respond_empty,
    route_key,
)
from handlers.context import ContextError, require_user, resolve_context
from handlers.presign import create_upload

logger = logging.getLogger()

TABLE_NAME = os.environ.get("TABLE_NAME", "")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")

SOURCE_IMAGE_URL_EXPIRY_S = 300

#: Tazelik kural tablosunun sürümü — her değerlendirme olayına yazılır ki
#: hangi kural sürümünün üzerine kullanıcı düzeltmesi geldiği ölçülebilsin.
RULE_VERSION = "rules-2026-09-v1"

ROUTES = (
    # Profil & kimlik
    "GET /v1/users/me",
    "PUT /v1/users/me",
    "PUT /v1/users/me/notification-preferences",
    "POST /v1/devices",
    "DELETE /v1/devices/{installation_id}",
    # Yükleme
    "POST /v1/uploads",
    "GET /v1/uploads/{upload_id}",
    # Envanter
    "GET /v1/items",
    "PATCH /v1/items/{item_id}",
    "DELETE /v1/items/{item_id}",
    "POST /v1/items/{item_id}/actions",
    "POST /v1/items/{item_id}/freshness-assessments",
    "PUT /v1/items/{item_id}/reminder",
    "DELETE /v1/items/{item_id}/reminder",
    # Aksiyon geri alma
    "POST /v1/item-actions/{action_id}/undo",
    # Kontrol kuyruğu
    "GET /v1/review-queue",
    # Alışveriş
    "GET /v1/shopping-lists/current",
    "POST /v1/shopping-lists/current/items",
    "PATCH /v1/shopping-lists/current/items/{shopping_item_id}",
    "DELETE /v1/shopping-lists/current/items/{shopping_item_id}",
    # Öneriler
    "GET /v1/replacement-candidates",
    "POST /v1/replacement-candidates/{candidate_id}/accept",
    "POST /v1/replacement-candidates/{candidate_id}/dismiss",
    # Tarifler
    "GET /v1/recipes/recommendations",
)

_repository: DynamoRepository | None = None
_s3_client = None


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


# --- Parse yardımcıları ---


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _query_params(event: dict) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def _parse_quantity(raw: object) -> Quantity | None:
    if not isinstance(raw, dict) or "value" not in raw:
        return None
    try:
        return Quantity(value=max(0, int(raw["value"])), unit=raw.get("unit", "piece"))
    except (TypeError, ValueError):
        return None


# --- Kaynak görsel (bbox kırpma için presigned GET) ---


def _source_image_url(object_key: str) -> str | None:
    if not BUCKET_NAME:
        return None
    try:
        return _get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": object_key},
            ExpiresIn=SOURCE_IMAGE_URL_EXPIRY_S,
        )
    except Exception:  # noqa: BLE001
        logger.warning('{"event": "source_image_presign_failed"}')
        return None


# --- Profil & kimlik ---


def _get_me(event: dict) -> dict:
    user_id = require_user(event)
    profile = _get_repository().get_profile(user_id)
    if profile is None:
        return respond(404, {"error": "profile_not_found"})
    return respond(200, dto.profile_to_json(profile))


def _put_me(event: dict) -> dict:
    """Kayıt/profil güncelleme: Ad-Soyad + buzdolabı ID (registry'de doğrulanır)."""
    user_id = require_user(event)
    body = json_body(event)
    display_name = (body.get("display_name") or "").strip()
    fridge_id = (body.get("fridge_id") or "").strip()
    if not display_name or not fridge_id:
        return respond(400, {"error": "missing_fields", "required": ["display_name", "fridge_id"]})

    repo = _get_repository()
    fridge = repo.get_fridge(fridge_id)
    if fridge is None or fridge.status.value != "ACTIVE":
        return respond(400, {"error": "invalid_fridge_id", "fridge_id": fridge_id})

    now = datetime.now(UTC)
    existing = repo.get_profile(user_id)
    profile = UserProfile(
        user_id=user_id,
        fridge_id=fridge_id,
        display_name=display_name,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        notification_preferences=existing.notification_preferences
        if existing
        else NotificationPreferences(),
    )
    repo.put_profile(profile)
    return respond(200 if existing else 201, dto.profile_to_json(profile))


def _put_notification_prefs(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    body = json_body(event)
    try:
        prefs = NotificationPreferences(
            mode=NotificationMode(body.get("mode", NotificationMode.DAILY_DIGEST.value)),
            digest_time=body.get("digest_time", "18:30"),
            quiet_hours_start=body.get("quiet_hours_start"),
            quiet_hours_end=body.get("quiet_hours_end"),
            timezone_id=body.get("timezone_id", "Europe/Istanbul"),
        )
    except ValueError as exc:
        return respond(400, {"error": "invalid_field_value", "detail": str(exc)})
    profile = _get_repository().update_notification_preferences(ctx.user_id, prefs)
    return respond(200, dto.prefs_to_json(profile.notification_preferences))


def _post_device(event: dict) -> dict:
    user_id = require_user(event)
    body = json_body(event)
    installation_id = (body.get("installation_id") or "").strip()
    push_token = (body.get("push_token") or "").strip()
    if not installation_id or not push_token:
        return respond(
            400, {"error": "missing_fields", "required": ["installation_id", "push_token"]}
        )
    now = datetime.now(UTC)
    _get_repository().put_device(
        DeviceRegistration(
            installation_id=installation_id,
            user_id=user_id,
            push_token=push_token,
            platform=body.get("platform", "android"),
            created_at=now,
            updated_at=now,
        )
    )
    return respond(201, {"installation_id": installation_id})


def _delete_device(event: dict) -> dict:
    user_id = require_user(event)
    installation_id = path_param(event, "installation_id")
    _get_repository().delete_device(user_id, installation_id)
    return respond_empty(204)


# --- Yükleme durumu ---


def _get_upload_status(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    upload_id = path_param(event, "upload_id")
    record = _get_repository().get_upload(upload_id)
    # Sahiplik: yükleme kaydı çağıranın dolabına ait değilse sızdırmadan 404.
    if record is None or record.fridge_id != ctx.fridge_id:
        return respond(404, {"error": "upload_not_found", "upload_id": upload_id})

    items = []
    source_image_url = None
    if record.status is UploadStatus.COMPLETED and record.item_ids:
        found = _get_repository().get_items(ctx.fridge_id, list(record.item_ids))
        items = [dto.item_to_json(item) for item in found]
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


# --- Envanter CRUD ---

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
        q = changes["quantity"]
        if not isinstance(q, dict) or "value" not in q or "unit" not in q:
            return "quantity {value, unit} biçimine uymuyor"
    return None


def _list_items(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    items = _get_repository().list_active_items(ctx.fridge_id)
    return respond(200, {"items": [dto.item_to_json(item) for item in items]})


def _patch_item(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    body = json_body(event)
    changes = {k: v for k, v in body.items() if k in _PATCHABLE_FIELDS}
    if not changes:
        return respond(400, {"error": "no_updatable_fields", "allowed": list(_PATCHABLE_FIELDS)})
    validation_error = _validate_patch_changes(changes)
    if validation_error:
        return respond(400, {"error": "invalid_field_value", "detail": validation_error})
    try:
        item = _get_repository().update_item(ctx.fridge_id, item_id, changes)
    except ItemNotFound:
        return respond(404, {"error": "item_not_found", "item_id": item_id})
    except RepositoryError as exc:
        return respond(400, {"error": "invalid_update", "detail": str(exc)})
    return respond(200, dto.item_to_json(item))


def _delete_item(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    _get_repository().delete_item(ctx.fridge_id, item_id)
    return respond_empty(204)


# --- Swipe aksiyonları ---


def _post_action(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    body = json_body(event)

    client_action_id = (body.get("client_action_id") or "").strip()
    if not client_action_id:
        return respond(400, {"error": "missing_fields", "required": ["client_action_id"]})
    try:
        action_type = SwipeActionType(body.get("type"))
    except ValueError:
        return respond(400, {"error": "invalid_field_value", "detail": "type"})
    discard_reason = None
    if body.get("discard_reason"):
        try:
            discard_reason = DiscardReason(body["discard_reason"])
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "discard_reason"})
    occurred_at = _parse_dt(body.get("occurred_at")) or datetime.now(UTC)
    now = datetime.now(UTC)

    repo = _get_repository()
    found = repo.get_items(ctx.fridge_id, [item_id])
    if not found:
        return respond(404, {"error": "item_not_found", "item_id": item_id})
    item = found[0]

    action = build_swipe_action(
        client_action_id=client_action_id,
        fridge_id=ctx.fridge_id,
        item=item,
        user_id=ctx.user_id,
        action_type=action_type,
        occurred_at=occurred_at,
        discard_reason=discard_reason,
    )
    new_state = resulting_item_state(action_type, item.state)
    candidate = build_replacement_candidate(
        fridge_id=ctx.fridge_id, item=item, action=action, now=now
    )
    saved_action, saved_candidate, saved_item = repo.record_swipe_action(
        action=action, new_item_state=new_state, candidate=candidate, now=now
    )
    return respond(
        201,
        {
            "action": dto.action_to_json(saved_action),
            "candidate": dto.candidate_to_json(saved_candidate) if saved_candidate else None,
            "item": dto.item_to_json(saved_item),
        },
    )


def _undo_action(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    action_id = path_param(event, "action_id")
    try:
        action = _get_repository().undo_action(ctx.fridge_id, action_id, datetime.now(UTC))
    except ItemNotFound:
        return respond(404, {"error": "action_not_found", "action_id": action_id})
    return respond(200, {"action": dto.action_to_json(action)})


# --- Tazelik değerlendirmesi ---


def _post_assessment(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    body = json_body(event)

    try:
        observed_state = ObservedFreshnessState(body.get("observed_state"))
    except ValueError:
        return respond(400, {"error": "invalid_field_value", "detail": "observed_state"})
    reason = None
    if body.get("reason"):
        try:
            reason = FreshnessAssessmentReason(body["reason"])
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "reason"})

    repo = _get_repository()
    found = repo.get_items(ctx.fridge_id, [item_id])
    if not found:
        return respond(404, {"error": "item_not_found", "item_id": item_id})
    item = found[0]

    now = datetime.now(UTC)
    user_fresh_until = _parse_date(body.get("user_estimated_fresh_until"))
    days = body.get("user_estimated_days_remaining")
    next_review_at = _parse_dt(body.get("next_review_at"))

    assessment = FreshnessAssessment(
        assessment_id=(body.get("assessment_id") or new_id("asmt")),
        fridge_id=ctx.fridge_id,
        item_id=item_id,
        user_id=ctx.user_id,
        assessed_at=_parse_dt(body.get("assessed_at")) or now,
        observed_state=observed_state,
        system_predicted_fresh_until_before=item.estimated_freshness_date,
        rule_version=RULE_VERSION,
        user_estimated_days_remaining=int(days) if isinstance(days, int) else None,
        user_estimated_fresh_until=user_fresh_until,
        next_review_at=next_review_at,
        reason=reason,
    )
    # Sistem tahmini DEĞİŞMEZ (BR-009): yalnızca kullanıcı alanları güncellenir.
    item_updates: dict = {}
    if user_fresh_until is not None:
        item_updates["user_adjusted_freshness_date"] = user_fresh_until
    if next_review_at is not None:
        item_updates["next_review_at"] = next_review_at

    saved_assessment, saved_item = repo.record_assessment(assessment, item_updates, now)
    return respond(
        201,
        {
            "assessment": dto.assessment_to_json(saved_assessment),
            "item": dto.item_to_json(saved_item),
        },
    )


# --- Kontrol kuyruğu ---


def _get_review_queue(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    now = datetime.now(UTC)
    items = _get_repository().list_active_items(ctx.fridge_id)
    entries = compute_review_queue(items, now)
    by_id = {item.item_id: item for item in items}
    return respond(
        200,
        {
            "queue": [
                {**dto.review_entry_to_json(e), "item": dto.item_to_json(by_id[e.item_id])}
                for e in entries
            ],
            "total_pending": len(entries),
        },
    )


# --- Reminder ---


def _put_reminder(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    body = json_body(event)
    scheduled_at = _parse_dt(body.get("scheduled_at"))
    if scheduled_at is None:
        return respond(400, {"error": "invalid_field_value", "detail": "scheduled_at"})
    now = datetime.now(UTC)
    reminder = ItemReminder(
        item_id=item_id,
        fridge_id=ctx.fridge_id,
        scheduled_at=scheduled_at,
        version=int(now.timestamp()),
        enabled=bool(body.get("enabled", True)),
    )
    _get_repository().put_reminder(reminder)
    return respond(200, dto.reminder_to_json(reminder))


def _delete_reminder(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    item_id = path_param(event, "item_id")
    _get_repository().delete_reminder(ctx.fridge_id, item_id)
    return respond_empty(204)


# --- Alışveriş listesi ---


def _get_shopping(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    items = _get_repository().list_shopping(ctx.fridge_id)
    active = [dto.shopping_to_json(s) for s in items if s.state is ShoppingItemState.ACTIVE]
    completed = [dto.shopping_to_json(s) for s in items if s.state is ShoppingItemState.COMPLETED]
    return respond(200, {"active": active, "completed": completed})


def _post_shopping(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    body = json_body(event)
    name = (body.get("name") or "").strip()
    if not name:
        return respond(400, {"error": "missing_fields", "required": ["name"]})
    category = None
    if body.get("category"):
        try:
            category = FoodCategory(body["category"])
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "category"})
    now = datetime.now(UTC)
    item = ShoppingListItem(
        shopping_item_id=new_id("shop"),
        fridge_id=ctx.fridge_id,
        name=name,
        state=ShoppingItemState.ACTIVE,
        category=category,
        quantity=_parse_quantity(body.get("quantity")),
        note=body.get("note"),
        created_at=now,
        updated_at=now,
    )
    _get_repository().put_shopping(item)
    return respond(201, dto.shopping_to_json(item))


_SHOPPING_PATCHABLE = ("name", "category", "quantity", "state", "note")


def _patch_shopping(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    shopping_item_id = path_param(event, "shopping_item_id")
    body = json_body(event)
    changes = {k: v for k, v in body.items() if k in _SHOPPING_PATCHABLE}
    if not changes:
        return respond(400, {"error": "no_updatable_fields", "allowed": list(_SHOPPING_PATCHABLE)})
    if "state" in changes:
        try:
            ShoppingItemState(changes["state"])
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "state"})
    if "category" in changes and changes["category"] is not None:
        try:
            FoodCategory(changes["category"])
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "category"})
    try:
        item = _get_repository().update_shopping(ctx.fridge_id, shopping_item_id, changes)
    except ItemNotFound:
        return respond(
            404, {"error": "shopping_item_not_found", "shopping_item_id": shopping_item_id}
        )
    except RepositoryError as exc:
        return respond(400, {"error": "invalid_update", "detail": str(exc)})
    return respond(200, dto.shopping_to_json(item))


def _delete_shopping(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    shopping_item_id = path_param(event, "shopping_item_id")
    _get_repository().delete_shopping(ctx.fridge_id, shopping_item_id)
    return respond_empty(204)


# --- Replacement candidates ---


def _get_candidates(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    status_param = _query_params(event).get("status")
    status = None
    if status_param:
        try:
            status = ReplacementCandidateStatus(status_param)
        except ValueError:
            return respond(400, {"error": "invalid_field_value", "detail": "status"})
    else:
        status = ReplacementCandidateStatus.PENDING
    candidates = _get_repository().list_candidates(ctx.fridge_id, status)
    return respond(200, {"candidates": [dto.candidate_to_json(c) for c in candidates]})


def _accept_candidate(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    candidate_id = path_param(event, "candidate_id")
    try:
        shopping = _get_repository().accept_candidate(
            ctx.fridge_id, candidate_id, datetime.now(UTC)
        )
    except ItemNotFound:
        return respond(404, {"error": "candidate_not_found", "candidate_id": candidate_id})
    except ConflictError as exc:
        return respond(409, {"error": "conflict", "detail": str(exc)})
    return respond(201, {"shopping_item": dto.shopping_to_json(shopping)})


def _dismiss_candidate(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    candidate_id = path_param(event, "candidate_id")
    try:
        _get_repository().dismiss_candidate(ctx.fridge_id, candidate_id)
    except ItemNotFound:
        return respond(404, {"error": "candidate_not_found", "candidate_id": candidate_id})
    return respond(200, {"candidate_id": candidate_id, "status": "DISMISSED"})


# --- Tarifler ---


def _get_recipes(event: dict) -> dict:
    ctx = resolve_context(event, _get_repository())
    params = _query_params(event)
    now = datetime.now(UTC)
    items = _get_repository().list_active_items(ctx.fridge_id)

    def _csv(name: str) -> set[str]:
        raw = params.get(name)
        return {v.strip() for v in raw.split(",") if v.strip()} if raw else set()

    max_prep = params.get("max_prep_minutes")
    matches = recommend(
        items,
        now,
        avoid_allergens=_csv("allergens"),
        require_diets=_csv("diets"),
        meal_type=params.get("meal_type"),
        max_prep_minutes=int(max_prep) if max_prep and max_prep.isdigit() else None,
    )
    return respond(
        200,
        {
            "dataset_version": dataset_version(),
            "recommendations": [dto.recipe_match_to_json(m) for m in matches],
        },
    )


# --- Dispatcher ---

_HANDLERS = {
    "GET /v1/users/me": _get_me,
    "PUT /v1/users/me": _put_me,
    "PUT /v1/users/me/notification-preferences": _put_notification_prefs,
    "POST /v1/devices": _post_device,
    "DELETE /v1/devices/{installation_id}": _delete_device,
    "POST /v1/uploads": create_upload,
    "GET /v1/uploads/{upload_id}": _get_upload_status,
    "GET /v1/items": _list_items,
    "PATCH /v1/items/{item_id}": _patch_item,
    "DELETE /v1/items/{item_id}": _delete_item,
    "POST /v1/items/{item_id}/actions": _post_action,
    "POST /v1/items/{item_id}/freshness-assessments": _post_assessment,
    "PUT /v1/items/{item_id}/reminder": _put_reminder,
    "DELETE /v1/items/{item_id}/reminder": _delete_reminder,
    "POST /v1/item-actions/{action_id}/undo": _undo_action,
    "GET /v1/review-queue": _get_review_queue,
    "GET /v1/shopping-lists/current": _get_shopping,
    "POST /v1/shopping-lists/current/items": _post_shopping,
    "PATCH /v1/shopping-lists/current/items/{shopping_item_id}": _patch_shopping,
    "DELETE /v1/shopping-lists/current/items/{shopping_item_id}": _delete_shopping,
    "GET /v1/replacement-candidates": _get_candidates,
    "POST /v1/replacement-candidates/{candidate_id}/accept": _accept_candidate,
    "POST /v1/replacement-candidates/{candidate_id}/dismiss": _dismiss_candidate,
    "GET /v1/recipes/recommendations": _get_recipes,
}


def handler(event, context):  # noqa: ANN001
    route = route_key(event)
    func = _HANDLERS.get(route)
    if func is None:
        # Bilinmeyen rota altyapı hatasıdır (API GW yanlış bağladı).
        return respond(404, {"error": "unknown_route", "route": route})
    try:
        return func(event)
    except ContextError as exc:
        return exc.response
    except RepositoryError as exc:
        logger.warning(json.dumps({"event": "repository_error", "route": route}))
        return respond(400, {"error": "repository_error", "detail": str(exc)})
