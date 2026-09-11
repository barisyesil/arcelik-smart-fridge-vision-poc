"""Handler'ların uçtan uca akışı — moto ile sahte S3 + DynamoDB.

Handler modülleri ortam değişkenlerini import anında okur; testte bunu tazelemek
için `mock_aws()` aktifken env'i ayarlayıp modülleri `importlib.reload` ile
yeniden çalıştırıyoruz (Lambda soğuk başlatma davranışının taklidi).

Kimlik: `AUTH_MODE=dev` ile `x-user-id` header'ı kabul edilir (üretimde JWT).
Veri buzdolabı bazında partition'lanır; her testte önce bir fridge registry
kaydı ve bir profil oluşturulur (aksi halde istekler 409 `profile_required` alır).
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
def handlers(aws_stack, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("BUCKET_NAME", BUCKET_NAME)
    monkeypatch.setenv("VISION_PROVIDER", "stub")
    monkeypatch.setenv("AUTH_MODE", "dev")

    import handlers._http as http
    import handlers.context as context
    import handlers.extractor as extractor
    import handlers.inventory_api as inventory_api
    import handlers.presign as presign

    importlib.reload(http)
    importlib.reload(context)
    importlib.reload(presign)
    importlib.reload(extractor)
    importlib.reload(inventory_api)

    _seed_fridge_and_profile(inventory_api, user_id="u_demo", fridge_id=FRIDGE)
    return presign, extractor, inventory_api


def _seed_fridge_and_profile(inventory_api, *, user_id, fridge_id, name="Test Kullanıcı"):
    """Fridge registry kaydını yazar ve kullanıcı profilini API üzerinden kurar."""
    from core.models import FridgeRegistryEntry, FridgeStatus

    repo = inventory_api._get_repository()
    repo.put_fridge(
        FridgeRegistryEntry(
            fridge_id=fridge_id,
            label="Test Dolabı",
            status=FridgeStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
    )
    response = inventory_api.handler(
        {
            "routeKey": "PUT /v1/users/me",
            "headers": {"x-user-id": user_id},
            "body": json.dumps({"display_name": name, "fridge_id": fridge_id}),
        },
        None,
    )
    assert response["statusCode"] in (200, 201)


def _event(route, *, user="u_demo", path=None, body=None, query=None):
    event = {"routeKey": route, "headers": {"x-user-id": user}}
    if path:
        event["pathParameters"] = path
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _upload_and_notify(handlers, s3_client, foods=None, user="u_demo"):
    from adapters.vision import StubVisionProvider
    from core.models import ExtractedFood, FieldConfidence, Quantity
    from core.taxonomy import FoodCategory, PackageState

    presign, extractor, inventory_api = handlers

    if foods is None:
        foods = [
            ExtractedFood(
                name="süzme yoğurt",
                category=FoodCategory.DAIRY,
                subcategory="yogurt",
                package_state=PackageState.UNOPENED,
                quantity=Quantity(value=1),
                confidence=FieldConfidence(name=0.9, category=0.95),
            )
        ]
    extractor._vision_provider = StubVisionProvider(foods=foods)

    upload_response = inventory_api.handler(_event("POST /v1/uploads", user=user), None)
    body = json.loads(upload_response["body"])

    s3_client.put_object(
        Bucket=BUCKET_NAME, Key=body["object_key"], Body=b"fake-jpeg", ContentType="image/jpeg"
    )
    etag = s3_client.head_object(Bucket=BUCKET_NAME, Key=body["object_key"])["ETag"]
    s3_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET_NAME},
                    "object": {"key": body["object_key"], "eTag": etag},
                }
            }
        ]
    }
    return body["upload_id"], s3_event


class TestProfile:
    def test_register_requires_valid_fridge_id(self, handlers):
        _, _, inventory_api = handlers
        response = inventory_api.handler(
            _event(
                "PUT /v1/users/me",
                user="u_new",
                body={"display_name": "Yeni", "fridge_id": "OLMAYAN-DOLAP"},
            ),
            None,
        )
        assert response["statusCode"] == 400
        assert json.loads(response["body"])["error"] == "invalid_fridge_id"

    def test_data_request_without_profile_returns_409(self, handlers):
        _, _, inventory_api = handlers
        response = inventory_api.handler(_event("GET /v1/items", user="u_profilesiz"), None)
        assert response["statusCode"] == 409
        assert json.loads(response["body"])["error"] == "profile_required"

    def test_get_me_returns_profile(self, handlers):
        _, _, inventory_api = handlers
        response = inventory_api.handler(_event("GET /v1/users/me"), None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["fridge_id"] == FRIDGE
        assert body["display_name"] == "Test Kullanıcı"


class TestPresign:
    def test_returns_upload_id_and_presigned_fields(self, handlers):
        _, _, inventory_api = handlers
        response = inventory_api.handler(_event("POST /v1/uploads"), None)
        body = json.loads(response["body"])
        assert response["statusCode"] == 201
        assert body["status"] == "PENDING"
        assert body["object_key"].startswith(f"uploads/{FRIDGE}/")
        assert "fields" in body and "url" in body

    def test_unknown_upload_id_returns_404(self, handlers):
        _, _, inventory_api = handlers
        response = inventory_api.handler(
            _event("GET /v1/uploads/{upload_id}", path={"upload_id": "upl_yok"}), None
        )
        assert response["statusCode"] == 404


class TestExtractor:
    def test_completes_the_upload_and_creates_items(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        upload_id, s3_event = _upload_and_notify(handlers, s3_client)

        result = extractor.handler(s3_event, None)
        assert result["processed"] == 1

        status = inventory_api.handler(
            _event("GET /v1/uploads/{upload_id}", path={"upload_id": upload_id}), None
        )
        body = json.loads(status["body"])
        assert body["status"] == "COMPLETED"
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "süzme yoğurt"
        assert body["items"][0]["estimated_freshness_date"]

    def test_duplicate_s3_event_is_skipped_not_reprocessed(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)

        first = extractor.handler(s3_event, None)
        second = extractor.handler(s3_event, None)
        assert first["processed"] == 1
        assert second["processed"] == 0

        items = json.loads(inventory_api.handler(_event("GET /v1/items"), None)["body"])["items"]
        assert len(items) == 1

    def test_unrecognized_object_key_is_skipped_without_crashing(self, handlers):
        _, extractor, _ = handlers
        event = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": BUCKET_NAME},
                        "object": {"key": "baska/yer/x.jpg", "eTag": "abc"},
                    }
                }
            ]
        }
        assert extractor.handler(event, None)["processed"] == 0


class TestInventoryApiCrud:
    def _seed_one_item(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)
        items = json.loads(inventory_api.handler(_event("GET /v1/items"), None)["body"])["items"]
        return inventory_api, items[0]["item_id"]

    def test_patch_marks_item_consumed_and_removes_it_from_listing(self, handlers, s3_client):
        inventory_api, item_id = self._seed_one_item(handlers, s3_client)
        patch = inventory_api.handler(
            _event(
                "PATCH /v1/items/{item_id}", path={"item_id": item_id}, body={"state": "CONSUMED"}
            ),
            None,
        )
        assert patch["statusCode"] == 200
        assert json.loads(patch["body"])["state"] == "CONSUMED"
        remaining = json.loads(inventory_api.handler(_event("GET /v1/items"), None)["body"])[
            "items"
        ]
        assert remaining == []

    def test_patch_can_correct_a_reserved_word_field(self, handlers, s3_client):
        inventory_api, item_id = self._seed_one_item(handlers, s3_client)
        patch = inventory_api.handler(
            _event(
                "PATCH /v1/items/{item_id}",
                path={"item_id": item_id},
                body={"name": "düzeltilmiş süt"},
            ),
            None,
        )
        assert patch["statusCode"] == 200
        assert json.loads(patch["body"])["name"] == "düzeltilmiş süt"

    def test_patch_rejects_unknown_field(self, handlers, s3_client):
        inventory_api, item_id = self._seed_one_item(handlers, s3_client)
        patch = inventory_api.handler(
            _event(
                "PATCH /v1/items/{item_id}",
                path={"item_id": item_id},
                body={"observation_id": "sahte"},
            ),
            None,
        )
        assert patch["statusCode"] == 400

    def test_patch_rejects_invalid_enum_value(self, handlers, s3_client):
        inventory_api, item_id = self._seed_one_item(handlers, s3_client)
        patch = inventory_api.handler(
            _event(
                "PATCH /v1/items/{item_id}",
                path={"item_id": item_id},
                body={"category": "uzay_gidasi"},
            ),
            None,
        )
        assert patch["statusCode"] == 400

    def test_delete_removes_the_item(self, handlers, s3_client):
        inventory_api, item_id = self._seed_one_item(handlers, s3_client)
        delete_response = inventory_api.handler(
            _event("DELETE /v1/items/{item_id}", path={"item_id": item_id}), None
        )
        assert delete_response["statusCode"] == 204
        remaining = json.loads(inventory_api.handler(_event("GET /v1/items"), None)["body"])[
            "items"
        ]
        assert remaining == []

    def test_items_are_scoped_per_fridge(self, handlers, s3_client):
        """Hane modeli: farklı buzdolabına kayıtlı kullanıcı ötekinin envanterini
        görmez. Aynı dolaba kayıtlı kullanıcılar ise paylaşır.
        """
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)

        # İkinci kullanıcı ikinci dolapta.
        _seed_fridge_and_profile(inventory_api, user_id="u_other", fridge_id="ARC-FRIDGE-002")
        other = inventory_api.handler(_event("GET /v1/items", user="u_other"), None)
        assert json.loads(other["body"])["items"] == []
