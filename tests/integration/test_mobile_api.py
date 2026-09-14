"""Mobil cloud endpoint'lerinin uçtan uca akışı — moto ile.

Swipe (idempotent) + undo, tazelik değerlendirmesi, kontrol kuyruğu, alışveriş
listesi, replacement candidate, bildirim tercihleri, cihaz kaydı ve tarif
önerileri. Kimlik `AUTH_MODE=dev` ile `x-user-id` üzerinden.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.integration

TABLE_NAME = "fridge-main-test"
BUCKET_NAME = "fridge-raw-test"
FRIDGE = "ARC-FRIDGE-001"


@pytest.fixture
def api(aws_stack, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("BUCKET_NAME", BUCKET_NAME)
    monkeypatch.setenv("VISION_PROVIDER", "stub")
    monkeypatch.setenv("AUTH_MODE", "dev")

    import handlers._http as http
    import handlers.context as context
    import handlers.extractor as extractor
    import handlers.inventory_api as inventory_api
    import handlers.presign as presign

    for mod in (http, context, presign, extractor, inventory_api):
        importlib.reload(mod)

    from core.models import FridgeRegistryEntry, FridgeStatus

    repo = inventory_api._get_repository()
    repo.put_fridge(
        FridgeRegistryEntry(
            fridge_id=FRIDGE, label="Test", status=FridgeStatus.ACTIVE, created_at=datetime.now(UTC)
        )
    )
    inventory_api.handler(
        {
            "routeKey": "PUT /v1/users/me",
            "headers": {"x-user-id": "u_demo"},
            "body": json.dumps({"display_name": "Test", "fridge_id": FRIDGE}),
        },
        None,
    )
    return inventory_api, extractor


def _event(route, *, path=None, body=None, query=None, user="u_demo"):
    e = {"routeKey": route, "headers": {"x-user-id": user}}
    if path:
        e["pathParameters"] = path
    if body is not None:
        e["body"] = json.dumps(body)
    if query is not None:
        e["queryStringParameters"] = query
    return e


def _call(inventory_api, route, **kw):
    return inventory_api.handler(_event(route, **kw), None)


def _seed_item(api, s3_client, days=2):
    """Upload + extractor akışıyla bir envanter kalemi oluşturur, id döner."""
    from adapters.vision import StubVisionProvider
    from core.models import ExtractedFood, FieldConfidence, Quantity
    from core.taxonomy import FoodCategory, PackageState

    inventory_api, extractor = api
    # Kısa raf ömürlü (3 gün) bir ürün: 5 günlük kontrol penceresine girsin ki
    # review-queue testi kalemi kuyrukta görebilsin.
    extractor._vision_provider = StubVisionProvider(
        foods=[
            ExtractedFood(
                name="çorba",
                category=FoodCategory.PREPARED_LEFTOVER,
                subcategory="soup",
                package_state=PackageState.OPENED,
                quantity=Quantity(value=1),
                confidence=FieldConfidence(name=0.9, category=0.95),
            )
        ]
    )
    body = json.loads(_call(inventory_api, "POST /v1/uploads").get("body"))
    s3_client.put_object(
        Bucket=BUCKET_NAME, Key=body["object_key"], Body=b"jpeg", ContentType="image/jpeg"
    )
    etag = s3_client.head_object(Bucket=BUCKET_NAME, Key=body["object_key"])["ETag"]
    extractor.handler(
        {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": BUCKET_NAME},
                        "object": {"key": body["object_key"], "eTag": etag},
                    }
                }
            ]
        },
        None,
    )
    items = json.loads(_call(inventory_api, "GET /v1/items").get("body"))["items"]
    return items[0]["item_id"]


class TestSwipeActions:
    def test_consume_marks_item_and_creates_candidate(self, api, s3_client):
        inventory_api, _ = api
        item_id = _seed_item(api, s3_client)
        resp = _call(
            inventory_api,
            "POST /v1/items/{item_id}/actions",
            path={"item_id": item_id},
            body={"client_action_id": "c1", "type": "CONSUMED"},
        )
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["item"]["state"] == "CONSUMED"
        assert body["candidate"]["reason"] == "CONSUMED"
        # Envanterden düşer.
        assert json.loads(_call(inventory_api, "GET /v1/items")["body"])["items"] == []

    def test_swipe_is_idempotent_by_client_action_id(self, api, s3_client):
        inventory_api, _ = api
        item_id = _seed_item(api, s3_client)
        first = json.loads(
            _call(
                inventory_api,
                "POST /v1/items/{item_id}/actions",
                path={"item_id": item_id},
                body={"client_action_id": "dup", "type": "CONSUMED"},
            )["body"]
        )
        second = json.loads(
            _call(
                inventory_api,
                "POST /v1/items/{item_id}/actions",
                path={"item_id": item_id},
                body={"client_action_id": "dup", "type": "CONSUMED"},
            )["body"]
        )
        # Aynı action_id ve aynı candidate — ikinci kez yeni kayıt üretilmez.
        assert first["action"]["action_id"] == second["action"]["action_id"]
        assert first["candidate"]["candidate_id"] == second["candidate"]["candidate_id"]
        pending = json.loads(_call(inventory_api, "GET /v1/replacement-candidates")["body"])
        assert len(pending["candidates"]) == 1

    def test_undo_restores_previous_state_and_reverts_candidate(self, api, s3_client):
        inventory_api, _ = api
        item_id = _seed_item(api, s3_client)
        action = json.loads(
            _call(
                inventory_api,
                "POST /v1/items/{item_id}/actions",
                path={"item_id": item_id},
                body={"client_action_id": "c1", "type": "DISCARDED", "discard_reason": "OTHER"},
            )["body"]
        )["action"]

        undo = _call(
            inventory_api,
            "POST /v1/item-actions/{action_id}/undo",
            path={"action_id": action["action_id"]},
        )
        assert undo["statusCode"] == 200
        # Ürün geri geldi (ACTIVE) ve tekrar envanterde.
        items = json.loads(_call(inventory_api, "GET /v1/items")["body"])["items"]
        assert len(items) == 1
        # Öneri REVERTED oldu (PENDING listesinde yok).
        pending = json.loads(_call(inventory_api, "GET /v1/replacement-candidates")["body"])
        assert pending["candidates"] == []


class TestAssessment:
    def test_assessment_sets_user_date_without_overwriting_system(self, api, s3_client):
        inventory_api, _ = api
        item_id = _seed_item(api, s3_client)
        before = json.loads(_call(inventory_api, "GET /v1/items")["body"])["items"][0]
        system_date = before["predicted_fresh_until"]

        resp = _call(
            inventory_api,
            "POST /v1/items/{item_id}/freshness-assessments",
            path={"item_id": item_id},
            body={
                "observed_state": "BORDERLINE",
                "user_estimated_fresh_until": "2026-09-20",
                "reason": "TEXTURE_CHANGED",
            },
        )
        assert resp["statusCode"] == 201
        item = json.loads(resp["body"])["item"]
        # Sistem tahmini korunur (BR-009), kullanıcı düzeltmesi ayrı.
        assert item["predicted_fresh_until"] == system_date
        assert item["user_adjusted_fresh_until"] == "2026-09-20"
        assert item["effective_fresh_until"] == "2026-09-20"


class TestReviewQueue:
    def test_returns_eligible_items_in_priority_order(self, api, s3_client):
        inventory_api, _ = api
        _seed_item(api, s3_client)  # süt, 2 gün → kritik
        resp = _call(inventory_api, "GET /v1/review-queue")
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total_pending"] == 1
        assert body["queue"][0]["reason"] in {"CRITICAL", "APPROACHING", "OVERDUE"}
        assert "item" in body["queue"][0]


class TestShoppingAndCandidates:
    def test_accept_candidate_adds_to_shopping_list(self, api, s3_client):
        inventory_api, _ = api
        item_id = _seed_item(api, s3_client)
        candidate = json.loads(
            _call(
                inventory_api,
                "POST /v1/items/{item_id}/actions",
                path={"item_id": item_id},
                body={"client_action_id": "c1", "type": "CONSUMED"},
            )["body"]
        )["candidate"]

        accept = _call(
            inventory_api,
            "POST /v1/replacement-candidates/{candidate_id}/accept",
            path={"candidate_id": candidate["candidate_id"]},
        )
        assert accept["statusCode"] == 201
        shopping = json.loads(_call(inventory_api, "GET /v1/shopping-lists/current")["body"])
        assert len(shopping["active"]) == 1
        assert shopping["active"][0]["name"] == "çorba"

    def test_manual_shopping_add_and_complete(self, api, s3_client):
        inventory_api, _ = api
        added = json.loads(
            _call(
                inventory_api,
                "POST /v1/shopping-lists/current/items",
                body={"name": "ekmek", "category": "bakery"},
            )["body"]
        )
        sid = added["shopping_item_id"]
        _call(
            inventory_api,
            "PATCH /v1/shopping-lists/current/items/{shopping_item_id}",
            path={"shopping_item_id": sid},
            body={"state": "COMPLETED"},
        )
        shopping = json.loads(_call(inventory_api, "GET /v1/shopping-lists/current")["body"])
        assert shopping["active"] == []
        assert len(shopping["completed"]) == 1


class TestPreferencesAndDevices:
    def test_update_notification_preferences(self, api):
        inventory_api, _ = api
        resp = _call(
            inventory_api,
            "PUT /v1/users/me/notification-preferences",
            body={"mode": "CRITICAL_ONLY", "digest_time": "09:00"},
        )
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["mode"] == "CRITICAL_ONLY"

    def test_register_and_remove_device(self, api):
        inventory_api, _ = api
        reg = _call(
            inventory_api,
            "POST /v1/devices",
            body={"installation_id": "inst-1", "push_token": "tok-1"},
        )
        assert reg["statusCode"] == 201
        remove = _call(
            inventory_api,
            "DELETE /v1/devices/{installation_id}",
            path={"installation_id": "inst-1"},
        )
        assert remove["statusCode"] == 204


class TestRecipes:
    def test_recommendations_are_returned(self, api, s3_client):
        inventory_api, _ = api
        _seed_item(api, s3_client)  # süt
        resp = _call(inventory_api, "GET /v1/recipes/recommendations")
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["dataset_version"] == "recipes-2026-09-v1"
        assert len(body["recommendations"]) >= 1
        assert "match_score" in body["recommendations"][0]
