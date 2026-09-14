from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.models import FieldConfidence, FoodCategory, FreshnessBasis, InventoryItem, Quantity
from core.review import REVIEW_WINDOW_DAYS, ReviewReason, compute_review_queue, is_eligible

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def _item(item_id, days, *, created=NOW, needs_review=False, next_review_at=None, user_adj=None):
    return InventoryItem(
        item_id=item_id,
        fridge_id="F1",
        user_id="u1",
        name=item_id,
        category=FoodCategory.DAIRY,
        quantity=Quantity(value=1),
        estimated_freshness_date=TODAY + timedelta(days=days),
        freshness_basis=FreshnessBasis.CATEGORY_HEURISTIC,
        created_at=created,
        updated_at=created,
        observation_id="o1",
        confidence=FieldConfidence(name=0.9, category=0.9),
        needs_review=needs_review,
        next_review_at=next_review_at,
        user_adjusted_freshness_date=user_adj,
    )


def test_eligible_when_within_window():
    assert is_eligible(_item("a", REVIEW_WINDOW_DAYS), NOW) is True


def test_not_eligible_when_far_in_future():
    assert is_eligible(_item("a", REVIEW_WINDOW_DAYS + 1), NOW) is False


def test_needs_review_is_eligible_even_if_far():
    assert is_eligible(_item("a", 30, needs_review=True), NOW) is True


def test_next_review_due_is_eligible():
    item = _item("a", 30, next_review_at=NOW - timedelta(hours=1))
    assert is_eligible(item, NOW) is True


def test_user_adjusted_date_drives_eligibility():
    # Sistem tahmini uzak ama kullanıcı düzeltmesi yakın → etkin tarih yakın.
    item = _item("a", 30, user_adj=TODAY + timedelta(days=1))
    assert item.effective_freshness_date == TODAY + timedelta(days=1)
    assert is_eligible(item, NOW) is True


def test_priority_order_scheduled_then_overdue_then_critical_then_approaching():
    items = [
        _item("approaching", 4),
        _item("critical", 1),
        _item("overdue", -2),
        _item("scheduled", 30, next_review_at=NOW - timedelta(hours=1)),
    ]
    queue = compute_review_queue(items, NOW)
    assert [e.item_id for e in queue] == ["scheduled", "overdue", "critical", "approaching"]
    assert queue[0].reason is ReviewReason.USER_SCHEDULED
    assert queue[1].reason is ReviewReason.OVERDUE


def test_same_priority_ties_break_by_created_at():
    older = _item("older", 1, created=NOW - timedelta(days=2))
    newer = _item("newer", 1, created=NOW)
    queue = compute_review_queue([newer, older], NOW)
    assert [e.item_id for e in queue] == ["older", "newer"]


def test_days_remaining_negative_for_overdue():
    (entry,) = compute_review_queue([_item("a", -3)], NOW)
    assert entry.days_remaining == -3
