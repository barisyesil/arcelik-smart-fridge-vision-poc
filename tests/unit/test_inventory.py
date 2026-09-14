from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.inventory import (
    build_item,
    gsi1_keys,
    idempotency_key,
    items_from_observation,
    object_key,
    observation_sk,
    parse_object_key,
)
from core.models import (
    BoundingBox,
    ExtractedFood,
    FieldConfidence,
    ItemState,
    Observation,
    Quantity,
)
from core.taxonomy import FoodCategory, PackageState

NOW = datetime(2026, 3, 10, 14, 30, tzinfo=UTC)


def _food(name="süzme yoğurt", category=FoodCategory.DAIRY, subcategory="yogurt", confidence=0.9):
    return ExtractedFood(
        name=name,
        brand="Sütaş",
        category=category,
        subcategory=subcategory,
        package_state=PackageState.UNOPENED,
        quantity=Quantity(value=1),
        confidence=FieldConfidence(name=confidence, category=0.95),
    )


FRIDGE = "ARC-FRIDGE-001"


def _observation(foods):
    return Observation(
        observation_id="obs_1",
        user_id="u_demo",
        fridge_id=FRIDGE,
        upload_id="upl_1",
        captured_at=NOW,
        source_bucket="fridge-raw-000",
        source_key=f"uploads/{FRIDGE}/2026-03-10/abc.jpg",
        foods=tuple(foods),
        model_id="stub-vision-0",
        prompt_version="v1",
    )


def test_observation_sk_sorts_chronologically():
    early = observation_sk(datetime(2026, 3, 10, 9, 0, tzinfo=UTC), "obs_b")
    late = observation_sk(datetime(2026, 3, 10, 21, 0, tzinfo=UTC), "obs_a")
    assert early < late


def test_idempotency_key_changes_with_etag():
    """Aynı anahtara yeni nesne yazılması meşru bir yeni gözlemdir."""
    first = idempotency_key("b", "uploads/x.jpg", "etag-1")
    second = idempotency_key("b", "uploads/x.jpg", "etag-2")
    assert first != second
    assert first == idempotency_key("b", "uploads/x.jpg", "etag-1")
    assert first["SK"] == "LOCK"


def test_build_item_produces_draft_not_active():
    """Extraction ürünleri DRAFT'tır — kullanıcı onaylayana kadar envantere girmez."""
    item, _ = build_item(
        _food(),
        fridge_id=FRIDGE,
        user_id="u_demo",
        observation_id="obs_1",
        captured_at=NOW,
        now=NOW,
    )
    assert item.state is ItemState.DRAFT
    # DRAFT kalem GSI1'e girmez (sparse index), yani list_active onu döndürmez.
    assert gsi1_keys(FRIDGE, item) == {}


def test_active_item_gets_gsi1_keys_sorted_by_freshness_date():
    item, _ = build_item(
        _food(),
        fridge_id=FRIDGE,
        user_id="u_demo",
        observation_id="obs_1",
        captured_at=NOW,
        now=NOW,
    )
    # Onaylanınca (ACTIVE) GSI1'e girer ve etkin tazelik tarihine göre sıralanır.
    item = replace(item, state=ItemState.ACTIVE)
    keys = gsi1_keys(FRIDGE, item)
    assert keys["GSI1PK"] == f"FRIDGE#{FRIDGE}#ACTIVE"
    assert keys["GSI1SK"].startswith("FRESH#2026-03-31#")


def test_bounding_box_survives_into_the_inventory_item():
    """Kutu, ham çıkarımdan (ExtractedFood) envanter kalemine taşınmalı; kırpma
    yapan arayüz bu kutuyu item DTO'sunda bulur."""
    box = BoundingBox(ymin=100, xmin=200, ymax=400, xmax=500)
    food = ExtractedFood(
        name="süt",
        category=FoodCategory.DAIRY,
        quantity=Quantity(value=1),
        confidence=FieldConfidence(name=0.9, category=0.9),
        bounding_box=box,
    )
    item, _ = build_item(
        food, fridge_id=FRIDGE, user_id="u_demo", observation_id="obs_1", captured_at=NOW, now=NOW
    )
    assert item.bounding_box == box


def test_food_without_box_yields_item_without_box():
    item, _ = build_item(
        _food(),
        fridge_id=FRIDGE,
        user_id="u_demo",
        observation_id="obs_1",
        captured_at=NOW,
        now=NOW,
    )
    assert item.bounding_box is None


def test_consumed_item_yields_no_gsi1_keys():
    """Sparse index: anahtarlar boş string değil, hiç yazılmamalı."""
    item, _ = build_item(
        _food(),
        fridge_id=FRIDGE,
        user_id="u_demo",
        observation_id="obs_1",
        captured_at=NOW,
        now=NOW,
    )
    item.state = ItemState.CONSUMED
    assert gsi1_keys(FRIDGE, item) == {}


def test_every_food_becomes_an_item_no_deduplication():
    """Uzlaştırma yok: aynı ürün iki kez görülürse iki kalem oluşur."""
    items, warnings = items_from_observation(
        _observation([_food(), _food(), _food("domates")]), NOW
    )

    assert len(items) == 3
    assert len({item.item_id for item in items}) == 3
    assert all(item.observation_id == "obs_1" for item in items)
    assert warnings == []


def test_item_carries_field_level_confidence_and_review_flag():
    """Güven skoru tek sayı değil, alan bazında."""
    items, _ = items_from_observation(_observation([_food(confidence=0.4)]), NOW)
    (item,) = items
    assert item.confidence.name == 0.4
    assert item.needs_review is True


def test_brand_survives_into_the_inventory_item():
    items, _ = items_from_observation(_observation([_food()]), NOW)
    assert items[0].brand == "Sütaş"


def test_object_key_round_trips_through_parse():
    """presign bu anahtarı üretir, extractor S3 olayından geri okur — S3
    olayı bucket/key/etag dışında hiçbir şey taşımadığı için tek bağlantı bu.
    """
    key = object_key("u_demo", "upl_abc123", NOW)
    assert key == "uploads/u_demo/2026-03-10/upl_abc123.jpg"
    assert parse_object_key(key) == "upl_abc123"


def test_parse_object_key_rejects_unexpected_shapes():
    assert parse_object_key("uploads/u_demo/upl_abc123.jpg") is None  # eksik tarih segmenti
    assert parse_object_key("other/u_demo/2026-03-10/upl_abc123.jpg") is None  # yanlis prefix
    assert parse_object_key("uploads/u_demo/2026-03-10/upl_abc123.png") is None  # yanlis uzanti
