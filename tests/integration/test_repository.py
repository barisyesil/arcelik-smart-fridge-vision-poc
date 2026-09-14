"""`DynamoRepository` testleri — moto ile sahte DynamoDB üzerinde.

Bu dosya `tests/unit/`'a KONULAMAZ: gerçek (mock'lanmış olsa da) bir DynamoDB
API çağrısı yapıyor. `pytest tests/unit` (CI'nin çalıştırdığı) bunu hiç görmez;
`pytest tests/integration -m integration` ile çalıştırılır.

Veri buzdolabı bazında partition'lanır (hane modeli); tüm okuma/yazma
`fridge_id` ile yapılır.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adapters.repository import DynamoRepository, IdempotencyConflict, ItemNotFound, RepositoryError
from core.models import (
    ExtractedFood,
    FieldConfidence,
    Observation,
    Quantity,
    UploadRecord,
    UploadStatus,
)
from core.taxonomy import FoodCategory, PackageState

pytestmark = pytest.mark.integration

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
FRIDGE = "ARC-FRIDGE-001"
USER = "u_demo"


@pytest.fixture
def repo(dynamo_table) -> DynamoRepository:
    return DynamoRepository(dynamo_table)


def _food(name="süt", confidence=0.9):
    return ExtractedFood(
        name=name,
        category=FoodCategory.DAIRY,
        subcategory="milk_fresh",
        package_state=PackageState.UNOPENED,
        quantity=Quantity(value=1),
        confidence=FieldConfidence(name=confidence, category=0.9),
    )


def _observation(user_id=USER, fridge_id=FRIDGE, upload_id="upl_1", foods=None):
    return Observation(
        observation_id="obs_1",
        user_id=user_id,
        fridge_id=fridge_id,
        upload_id=upload_id,
        captured_at=NOW,
        source_bucket="fridge-raw-test",
        source_key=f"uploads/{fridge_id}/2026-03-10/{upload_id}.jpg",
        foods=tuple(foods or [_food()]),
        model_id="stub-vision-0",
        prompt_version="v2",
    )


def _upload(upload_id="upl_1"):
    return UploadRecord(
        upload_id=upload_id,
        user_id=USER,
        fridge_id=FRIDGE,
        status=UploadStatus.PENDING,
        created_at=NOW,
        object_key=f"uploads/{FRIDGE}/2026-03-10/{upload_id}.jpg",
    )


class TestIdempotencyLock:
    def test_second_acquire_with_same_etag_conflicts(self, repo):
        repo.acquire_idempotency_lock("bucket", "key", "etag-1")
        with pytest.raises(IdempotencyConflict):
            repo.acquire_idempotency_lock("bucket", "key", "etag-1")

    def test_different_etag_is_a_new_lock(self, repo):
        repo.acquire_idempotency_lock("bucket", "key", "etag-1")
        repo.acquire_idempotency_lock("bucket", "key", "etag-2")


class TestCommitExtraction:
    def test_writes_observation_items_and_completes_upload_atomically(self, repo):
        from core.inventory import items_from_observation

        repo.put_upload(_upload())
        observation = _observation()
        items, _ = items_from_observation(observation, NOW)
        repo.commit_extraction(observation, items)

        record = repo.get_upload("upl_1")
        assert record.status is UploadStatus.COMPLETED
        assert record.observation_id == "obs_1"
        assert set(record.item_ids) == {item.item_id for item in items}
        assert record.fridge_id == FRIDGE

        fetched = repo.get_items(FRIDGE, list(record.item_ids))
        assert len(fetched) == 1
        assert fetched[0].name == "süt"

    def test_low_confidence_item_is_flagged_for_review(self, repo):
        from core.inventory import items_from_observation

        repo.put_upload(_upload("upl_2"))
        observation = _observation(upload_id="upl_2", foods=[_food(confidence=0.3)])
        items, _ = items_from_observation(observation, NOW)
        repo.commit_extraction(observation, items)

        (item,) = repo.get_items(FRIDGE, [items[0].item_id])
        assert item.needs_review is True

    def test_bounding_box_round_trips_through_dynamodb(self, repo):
        from core.inventory import items_from_observation
        from core.models import BoundingBox

        repo.put_upload(_upload("upl_3"))
        boxed = ExtractedFood(
            name="domates",
            category=FoodCategory.PRODUCE_VEGETABLE,
            subcategory="tomato",
            package_state=PackageState.OPENED,
            quantity=Quantity(value=1),
            confidence=FieldConfidence(name=0.9, category=0.9),
            bounding_box=BoundingBox(ymin=120, xmin=60, ymax=640, xmax=340),
        )
        observation = _observation(upload_id="upl_3", foods=[boxed])
        items, _ = items_from_observation(observation, NOW)
        repo.commit_extraction(observation, items)

        (item,) = repo.get_items(FRIDGE, [items[0].item_id])
        assert item.bounding_box == BoundingBox(ymin=120, xmin=60, ymax=640, xmax=340)


class TestListActiveItems:
    def test_orders_by_freshness_date_ascending(self, repo):
        from dataclasses import replace

        from core.inventory import build_item
        from core.models import ItemState

        soon, _ = build_item(
            ExtractedFood(
                name="çabuk bozulan",
                category=FoodCategory.MEAT_POULTRY,
                subcategory="ground_meat",
                package_state=PackageState.UNOPENED,
                quantity=Quantity(value=1),
                confidence=FieldConfidence(name=0.9, category=0.9),
            ),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        later, _ = build_item(
            ExtractedFood(
                name="uzun ömürlü",
                category=FoodCategory.PANTRY_DRY,
                subcategory="dry_pasta_rice",
                package_state=PackageState.UNOPENED,
                quantity=Quantity(value=1),
                confidence=FieldConfidence(name=0.9, category=0.9),
            ),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        # build_item DRAFT üretir; liste sıralamasını test etmek için ACTIVE'e al.
        repo._table.put_item(Item=_row(replace(later, state=ItemState.ACTIVE)))
        repo._table.put_item(Item=_row(replace(soon, state=ItemState.ACTIVE)))

        items = repo.list_active_items(FRIDGE)
        assert [i.name for i in items] == ["çabuk bozulan", "uzun ömürlü"]

    def test_consumed_item_does_not_appear(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        repo._table.put_item(Item=_row(item))
        repo.update_item(FRIDGE, item.item_id, {"state": "CONSUMED"})
        assert repo.list_active_items(FRIDGE) == []


class TestUpdateItem:
    def test_unknown_field_is_rejected(self, repo):
        with pytest.raises(RepositoryError):
            repo.update_item(FRIDGE, "itm_x", {"sihirli_alan": "x"})

    def test_missing_item_raises_item_not_found(self, repo):
        with pytest.raises(ItemNotFound):
            repo.update_item(FRIDGE, "itm_yok", {"name": "x"})

    def test_updates_a_reserved_word_field_without_error(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        repo._table.put_item(Item=_row(item))
        updated = repo.update_item(FRIDGE, item.item_id, {"name": "düzeltilmiş ad"})
        assert updated.name == "düzeltilmiş ad"
        assert updated.version == item.version + 1

    def test_consumed_state_removes_gsi1_keys(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        repo._table.put_item(Item=_row(item))
        repo.update_item(FRIDGE, item.item_id, {"state": "CONSUMED"})

        raw = repo._table.get_item(Key={"PK": f"FRIDGE#{FRIDGE}", "SK": f"ITEM#{item.item_id}"})[
            "Item"
        ]
        assert "GSI1PK" not in raw
        assert "GSI1SK" not in raw


class TestDeleteItem:
    def test_removes_the_item(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(),
            fridge_id=FRIDGE,
            user_id=USER,
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        repo._table.put_item(Item=_row(item))
        repo.delete_item(FRIDGE, item.item_id)
        assert repo.get_items(FRIDGE, [item.item_id]) == []


def _row(item):
    from adapters.repository import _serialize_item

    return _serialize_item(item)
