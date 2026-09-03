"""`DynamoRepository` testleri — moto ile sahte DynamoDB üzerinde.

Bu dosya `tests/unit/`'a KONULAMAZ: gerçek (mock'lanmış olsa da) bir
DynamoDB API çağrısı yapıyor. `pytest tests/unit` (CI'nin çalıştırdığı) bunu
hiç görmez; `pytest tests/integration -m integration` ile çalıştırılır.

Not: `table.meta.client.transact_write_items()` NATIVE Python değerleri
bekler (resource katmanının tip dönüştürücüsü client'a bağlı) — elle
`{"S": ...}` sarmalamak burada YANLIŞTIR ve moto altında sessizce bozuk bir
transaction'a yol açar. `repository.py`'nin `commit_extraction`'ı bunu
`_serialize_*` fonksiyonlarının çıktısını doğrudan (dönüşümsüz) vererek
doğru yapar; bu test paketi o davranışı kilitler.
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


def _observation(user_id="u_demo", upload_id="upl_1", foods=None):
    return Observation(
        observation_id="obs_1",
        user_id=user_id,
        upload_id=upload_id,
        captured_at=NOW,
        source_bucket="fridge-raw-test",
        source_key="uploads/u_demo/2026-03-10/upl_1.jpg",
        foods=tuple(foods or [_food()]),
        model_id="stub-vision-0",
        prompt_version="v1",
    )


class TestIdempotencyLock:
    def test_second_acquire_with_same_etag_conflicts(self, repo):
        repo.acquire_idempotency_lock("bucket", "key", "etag-1")
        with pytest.raises(IdempotencyConflict):
            repo.acquire_idempotency_lock("bucket", "key", "etag-1")

    def test_different_etag_is_a_new_lock(self, repo):
        """Aynı anahtara üzerine yazma meşru bir yeni gözlemdir."""
        repo.acquire_idempotency_lock("bucket", "key", "etag-1")
        repo.acquire_idempotency_lock("bucket", "key", "etag-2")  # raise etmemeli


class TestCommitExtraction:
    def test_writes_observation_items_and_completes_upload_atomically(self, repo):
        from core.inventory import items_from_observation

        repo.put_upload(
            UploadRecord(
                upload_id="upl_1",
                user_id="u_demo",
                status=UploadStatus.PENDING,
                created_at=NOW,
                object_key="uploads/u_demo/2026-03-10/upl_1.jpg",
            )
        )

        observation = _observation()
        items, _ = items_from_observation(observation, NOW)
        repo.commit_extraction(observation, items)

        record = repo.get_upload("upl_1")
        assert record.status is UploadStatus.COMPLETED
        assert record.observation_id == "obs_1"
        assert set(record.item_ids) == {item.item_id for item in items}

        fetched = repo.get_items("u_demo", list(record.item_ids))
        assert len(fetched) == 1
        assert fetched[0].name == "süt"

    def test_low_confidence_item_is_flagged_for_review(self, repo):
        from core.inventory import items_from_observation

        repo.put_upload(
            UploadRecord(
                upload_id="upl_2",
                user_id="u_demo",
                status=UploadStatus.PENDING,
                created_at=NOW,
                object_key="uploads/u_demo/2026-03-10/upl_2.jpg",
            )
        )
        observation = _observation(upload_id="upl_2", foods=[_food(confidence=0.3)])
        items, _ = items_from_observation(observation, NOW)
        repo.commit_extraction(observation, items)

        (item,) = repo.get_items("u_demo", [items[0].item_id])
        assert item.needs_review is True


class TestListActiveItems:
    def test_orders_by_freshness_date_ascending(self, repo):
        from core.inventory import build_item

        soon, _ = build_item(
            ExtractedFood(
                name="çabuk bozulan",
                category=FoodCategory.MEAT_POULTRY,
                subcategory="ground_meat",
                package_state=PackageState.UNOPENED,
                quantity=Quantity(value=1),
                confidence=FieldConfidence(name=0.9, category=0.9),
            ),
            user_id="u_demo",
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
            user_id="u_demo",
            observation_id="obs_x",
            captured_at=NOW,
            now=NOW,
        )
        # Bilerek ters sırada yazıyoruz — sıralamanın DynamoDB'den (GSI1),
        # Python tarafından değil, geldiğini kanıtlamak için.
        repo._table.put_item(Item=_row(later))
        repo._table.put_item(Item=_row(soon))

        items = repo.list_active_items("u_demo")

        assert [i.name for i in items] == ["çabuk bozulan", "uzun ömürlü"]

    def test_consumed_item_does_not_appear(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(), user_id="u_demo", observation_id="obs_x", captured_at=NOW, now=NOW
        )
        repo._table.put_item(Item=_row(item))

        repo.update_item("u_demo", item.item_id, {"state": "CONSUMED"})

        assert repo.list_active_items("u_demo") == []


class TestUpdateItem:
    def test_unknown_field_is_rejected(self, repo):
        with pytest.raises(RepositoryError):
            repo.update_item("u_demo", "itm_x", {"sihirli_alan": "x"})

    def test_missing_item_raises_item_not_found(self, repo):
        with pytest.raises(ItemNotFound):
            repo.update_item("u_demo", "itm_yok", {"name": "x"})

    def test_updates_a_reserved_word_field_without_error(self, repo):
        """`name` ve `state` DynamoDB'nin ayrılmış kelime listesindedir —
        alias'sız bir UpdateExpression burada patlar (bkz. repository.py
        `update_item` docstring'i).
        """
        from core.inventory import build_item

        item, _ = build_item(
            _food(), user_id="u_demo", observation_id="obs_x", captured_at=NOW, now=NOW
        )
        repo._table.put_item(Item=_row(item))

        updated = repo.update_item("u_demo", item.item_id, {"name": "düzeltilmiş ad"})

        assert updated.name == "düzeltilmiş ad"

    def test_consumed_state_removes_gsi1_keys(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(), user_id="u_demo", observation_id="obs_x", captured_at=NOW, now=NOW
        )
        repo._table.put_item(Item=_row(item))

        repo.update_item("u_demo", item.item_id, {"state": "CONSUMED"})

        raw = repo._table.get_item(Key={"PK": "USER#u_demo", "SK": f"ITEM#{item.item_id}"})["Item"]
        assert "GSI1PK" not in raw
        assert "GSI1SK" not in raw


class TestDeleteItem:
    def test_removes_the_item(self, repo):
        from core.inventory import build_item

        item, _ = build_item(
            _food(), user_id="u_demo", observation_id="obs_x", captured_at=NOW, now=NOW
        )
        repo._table.put_item(Item=_row(item))

        repo.delete_item("u_demo", item.item_id)

        assert repo.get_items("u_demo", [item.item_id]) == []


def _row(item):
    """Test kurulumunda doğrudan tabloya yazmak için — `repository`'nin
    kendi private serileştiricisini tekrar kullanır, testte kopyalamayız.
    """
    from adapters.repository import _serialize_item

    return _serialize_item(item)
