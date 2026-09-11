"""Kontrol kuyruğu hesaplaması. Saf Python; AWS ve "şu an" kavramı yok.

`GET /v1/review-queue` bu mantığı kullanır. Kuyruk BR-003 (uygunluk) ve BR-004
(öncelik) kurallarına göre hesaplanır. Zaman her zaman dışarıdan verilir; böylece
test edilebilir ve saat dilimi hatası sızmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from core.models import InventoryItem, ItemState, ReviewReason

#: BR-003: etkin tarihi bu kadar gün içinde olan ürünler kuyruğa girer.
REVIEW_WINDOW_DAYS = 5


@dataclass(frozen=True)
class ReviewQueueEntry:
    item_id: str
    priority: int  # küçük değer = yüksek öncelik
    reason: ReviewReason
    days_remaining: int  # negatifse tarih geçmiştir


def _days_remaining(item: InventoryItem, now: datetime) -> int:
    return (item.effective_freshness_date - now.date()).days


def is_eligible(item: InventoryItem, now: datetime) -> bool:
    """BR-003 — aktif ürün kuyruğa girmeye uygun mu?"""
    if item.state is not ItemState.ACTIVE:
        return False
    if _days_remaining(item, now) <= REVIEW_WINDOW_DAYS:
        return True
    if item.next_review_at is not None and item.next_review_at <= now:
        return True
    if item.needs_review:
        return True
    return item.user_requested_review


def _classify(item: InventoryItem, now: datetime) -> tuple[int, ReviewReason]:
    """BR-004 — (öncelik, neden). Küçük öncelik değeri önce gösterilir."""
    days = _days_remaining(item, now)
    if item.next_review_at is not None and item.next_review_at <= now:
        return 1, ReviewReason.USER_SCHEDULED
    if days < 0:
        return 2, ReviewReason.OVERDUE
    if days <= 2:
        return 3, ReviewReason.CRITICAL
    if days <= REVIEW_WINDOW_DAYS:
        return 4, ReviewReason.APPROACHING
    # Pencerenin dışında ama needs_review/user_requested_review ile uygun.
    return 5, ReviewReason.NEEDS_REVIEW


def compute_review_queue(items: list[InventoryItem], now: datetime) -> list[ReviewQueueEntry]:
    """Uygun aktif ürünleri BR-004 önceliğiyle sıralı döndürür.

    Eşitlik bozucu (BR-004/6): aynı öncelik grubunda en eski eklenen önce.
    """
    entries: list[tuple[int, datetime, ReviewQueueEntry]] = []
    for item in items:
        if not is_eligible(item, now):
            continue
        priority, reason = _classify(item, now)
        entries.append(
            (
                priority,
                item.created_at,
                ReviewQueueEntry(
                    item_id=item.item_id,
                    priority=priority,
                    reason=reason,
                    days_remaining=_days_remaining(item, now),
                ),
            )
        )
    entries.sort(key=lambda e: (e[0], e[1]))
    return [entry for _, _, entry in entries]


def next_review_from_lead_days(now: datetime, lead_days: int) -> datetime:
    """Kullanıcının 'X gün sonra tekrar göster' seçimini `next_review_at`'a çevirir."""
    return now + timedelta(days=max(0, lead_days))
