"""API kontratı v1 — domain nesnelerini istemcinin gördüğü JSON'a çevirir.

Alan adları (snake_case) API sözleşmesinin parçasıdır; mobil ve web istemci bu
adlara bağlıdır. Değiştirmek istemciyi kırar (bkz. SRS Ek B alan eşlemesi).
"""

from __future__ import annotations

from dataclasses import asdict

from core.models import (
    FreshnessAssessment,
    InventoryItem,
    ItemReminder,
    NotificationPreferences,
    ReplacementCandidate,
    ShoppingListItem,
    SwipeAction,
    UserProfile,
)
from core.recipes import RecipeMatch
from core.review import ReviewQueueEntry


def _bbox(item: InventoryItem) -> dict | None:
    return asdict(item.bounding_box) if item.bounding_box else None


def item_to_json(item: InventoryItem) -> dict:
    return {
        "item_id": item.item_id,
        "fridge_id": item.fridge_id,
        "name": item.name,
        "brand": item.brand,
        "raw_label": item.raw_label,
        "category": item.category.value,
        "subcategory": item.subcategory,
        "package_state": item.package_state.value,
        "quantity": asdict(item.quantity),
        # SRS mobil adlandırması: sistem tahmini `predicted_fresh_until`,
        # kullanıcı düzeltmesi ayrı; `estimated_freshness_date` geriye dönük korunur.
        "estimated_freshness_date": item.estimated_freshness_date.isoformat(),
        "predicted_fresh_until": item.estimated_freshness_date.isoformat(),
        "user_adjusted_fresh_until": item.user_adjusted_freshness_date.isoformat()
        if item.user_adjusted_freshness_date
        else None,
        "effective_fresh_until": item.effective_freshness_date.isoformat(),
        "freshness_basis": item.freshness_basis.value,
        "confidence": asdict(item.confidence) if item.confidence else None,
        "needs_review": item.needs_review,
        "state": item.state.value,
        "bounding_box": _bbox(item),
        "last_reviewed_at": item.last_reviewed_at.isoformat() if item.last_reviewed_at else None,
        "next_review_at": item.next_review_at.isoformat() if item.next_review_at else None,
        "user_requested_review": item.user_requested_review,
        "image_ref": item.image_ref,
        "version": item.version,
    }


def action_to_json(action: SwipeAction) -> dict:
    return {
        "action_id": action.action_id,
        "client_action_id": action.client_action_id,
        "item_id": action.item_id,
        "type": action.type.value,
        "occurred_at": action.occurred_at.isoformat(),
        "previous_item_state": action.previous_item_state.value,
        "discard_reason": action.discard_reason.value if action.discard_reason else None,
        "reverted_at": action.reverted_at.isoformat() if action.reverted_at else None,
        "replacement_candidate_id": action.replacement_candidate_id,
    }


def assessment_to_json(a: FreshnessAssessment) -> dict:
    return {
        "assessment_id": a.assessment_id,
        "item_id": a.item_id,
        "assessed_at": a.assessed_at.isoformat(),
        "observed_state": a.observed_state.value,
        "user_estimated_days_remaining": a.user_estimated_days_remaining,
        "user_estimated_fresh_until": a.user_estimated_fresh_until.isoformat()
        if a.user_estimated_fresh_until
        else None,
        "system_predicted_fresh_until_before": a.system_predicted_fresh_until_before.isoformat(),
        "next_review_at": a.next_review_at.isoformat() if a.next_review_at else None,
        "reason": a.reason.value if a.reason else None,
        "rule_version": a.rule_version,
    }


def candidate_to_json(c: ReplacementCandidate) -> dict:
    return {
        "candidate_id": c.candidate_id,
        "source_item_id": c.source_item_id,
        "source_action_id": c.source_action_id,
        "name": c.name,
        "category": c.category.value,
        "reason": c.reason.value,
        "status": c.status.value,
        "suggested_quantity": asdict(c.suggested_quantity) if c.suggested_quantity else None,
        "created_at": c.created_at.isoformat(),
    }


def shopping_to_json(s: ShoppingListItem) -> dict:
    return {
        "shopping_item_id": s.shopping_item_id,
        "name": s.name,
        "state": s.state.value,
        "category": s.category.value if s.category else None,
        "quantity": asdict(s.quantity) if s.quantity else None,
        "source_candidate_id": s.source_candidate_id,
        "note": s.note,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def prefs_to_json(prefs: NotificationPreferences) -> dict:
    return {
        "mode": prefs.mode.value,
        "digest_time": prefs.digest_time,
        "quiet_hours_start": prefs.quiet_hours_start,
        "quiet_hours_end": prefs.quiet_hours_end,
        "timezone_id": prefs.timezone_id,
    }


def profile_to_json(profile: UserProfile) -> dict:
    return {
        "user_id": profile.user_id,
        "fridge_id": profile.fridge_id,
        "display_name": profile.display_name,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
        "notification_preferences": prefs_to_json(profile.notification_preferences),
    }


def review_entry_to_json(entry: ReviewQueueEntry) -> dict:
    return {
        "item_id": entry.item_id,
        "priority": entry.priority,
        "reason": entry.reason.value,
        "days_remaining": entry.days_remaining,
    }


def recipe_match_to_json(match: RecipeMatch) -> dict:
    recipe = match.recipe
    return {
        "recipe_id": match.recipe_id,
        "title": match.title,
        "match_score": match.match_score,
        "expiring_used_count": match.expiring_used_count,
        "missing_required": match.missing_required,
        "description": recipe.get("description"),
        "meal_types": recipe.get("meal_types", []),
        "servings": recipe.get("servings"),
        "prep_minutes": recipe.get("prep_minutes"),
        "cook_minutes": recipe.get("cook_minutes"),
        "allergen_tags": recipe.get("allergen_tags", []),
        "diet_tags": recipe.get("diet_tags", []),
    }


def reminder_to_json(r: ItemReminder) -> dict:
    return {
        "item_id": r.item_id,
        "scheduled_at": r.scheduled_at.isoformat(),
        "version": r.version,
        "enabled": r.enabled,
        "last_delivered_at": r.last_delivered_at.isoformat() if r.last_delivered_at else None,
    }
