"""Swipe olayı iş mantığı. Saf Python; kalıcılık `repository.py`'de.

Bir swipe isteği üç şeye dönüşebilir (BR-006, BR-010): ürün durumu değişimi,
değişmez bir `SwipeAction` olayı ve isteğe bağlı bir `ReplacementCandidate`.
Bunların atomik yazımı repository'nin işidir; burada yalnızca "ne üretilmeli"
kararı verilir.
"""

from __future__ import annotations

from datetime import datetime

from core.inventory import new_id
from core.models import (
    InventoryItem,
    ItemState,
    Quantity,
    ReplacementCandidate,
    ReplacementCandidateStatus,
    SwipeAction,
    SwipeActionType,
)

#: Swipe tipinden ürünün geçeceği durum (BR-006). REVIEWED durumu değiştirmez.
_STATE_BY_ACTION: dict[SwipeActionType, ItemState | None] = {
    SwipeActionType.CONSUMED: ItemState.CONSUMED,
    SwipeActionType.DISCARDED: ItemState.DISCARDED,
    SwipeActionType.REVIEWED: None,
}

#: Bu tipler alışveriş önerisi doğurur (BR-010).
_CANDIDATE_ACTIONS = frozenset({SwipeActionType.CONSUMED, SwipeActionType.DISCARDED})


def resulting_item_state(action_type: SwipeActionType, current: ItemState) -> ItemState:
    """Swipe sonrası ürün durumu. REVIEWED mevcut durumu korur."""
    return _STATE_BY_ACTION[action_type] or current


def build_swipe_action(
    *,
    client_action_id: str,
    fridge_id: str,
    item: InventoryItem,
    user_id: str,
    action_type: SwipeActionType,
    occurred_at: datetime,
    discard_reason=None,
) -> SwipeAction:
    return SwipeAction(
        action_id=new_id("act"),
        client_action_id=client_action_id,
        fridge_id=fridge_id,
        item_id=item.item_id,
        user_id=user_id,
        type=action_type,
        occurred_at=occurred_at,
        previous_item_state=item.state,
        discard_reason=discard_reason if action_type is SwipeActionType.DISCARDED else None,
    )


def build_replacement_candidate(
    *,
    fridge_id: str,
    item: InventoryItem,
    action: SwipeAction,
    now: datetime,
) -> ReplacementCandidate | None:
    """Tüketildi/atıldı için öneri üretir; REVIEWED için `None` (BR-010).

    Öneri kullanıcı onayı olmadan listeye eklenmez (bu core sadece adayı üretir).
    Miktar ve kategori kaynak üründen taşınır ki kullanıcı hızlı ekleyebilsin.
    """
    if action.type not in _CANDIDATE_ACTIONS:
        return None
    return ReplacementCandidate(
        candidate_id=new_id("cand"),
        fridge_id=fridge_id,
        source_item_id=item.item_id,
        source_action_id=action.action_id,
        name=item.name,
        category=item.category,
        reason=action.type,
        status=ReplacementCandidateStatus.PENDING,
        created_at=now,
        suggested_quantity=Quantity(value=item.quantity.value, unit=item.quantity.unit),
    )
