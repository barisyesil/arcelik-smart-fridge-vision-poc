"""Handler'ların uçtan uca akışı — moto ile sahte S3 + DynamoDB.

Handler modülleri (`presign`, `extractor`, `inventory_api`) `TABLE_NAME` ve
`BUCKET_NAME` gibi ortam değişkenlerini MODÜL SEVİYESİNDE (import anında)
okur — bu, Lambda'da soğuk başlatma dışında yeniden okumamak için bilinçli
bir tercih (bkz. `handlers/presign.py`). Testte bunu tazelemek için, env
değişkenlerini `mock_aws()` aktifken ayarlayıp modülleri `importlib.reload`
ile yeniden çalıştırıyoruz — Lambda'nın "her invoke modülü yeniden yükler"
davranışını taklit etmenin standart yolu budur.
"""

from __future__ import annotations

import importlib
import json

import pytest

pytestmark = pytest.mark.integration

#: `conftest.py`'deki değerlerle aynı olmalı — fixture'lar tabloyu/bucket'ı
#: bu adlarla kurar.
TABLE_NAME = "fridge-main-test"
BUCKET_NAME = "fridge-raw-test"


@pytest.fixture
def handlers(aws_stack, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("BUCKET_NAME", BUCKET_NAME)
    monkeypatch.setenv("VISION_PROVIDER", "stub")

    import handlers.extractor as extractor
    import handlers.inventory_api as inventory_api
    import handlers.presign as presign

    # Sıra önemli: presign önce, sonra onu içeriden import eden inventory_api.
    importlib.reload(presign)
    importlib.reload(extractor)
    importlib.reload(inventory_api)
    return presign, extractor, inventory_api


@pytest.fixture
def s3_client(aws_stack):
    import boto3

    return boto3.client("s3", region_name="eu-central-1")


def _upload_and_notify(handlers, s3_client, foods=None):
    """Presigned POST akışını taklit eder: upload kaydı oluştur, S3'e yaz,
    extractor'ı gerçek bir S3 ObjectCreated olayıyla tetikle.
    """
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

    upload_response = inventory_api.handler({"routeKey": "POST /v1/uploads", "headers": {}}, None)
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


class TestPresign:
    def test_returns_upload_id_and_presigned_fields(self, handlers):
        _, _, inventory_api = handlers

        response = inventory_api.handler({"routeKey": "POST /v1/uploads", "headers": {}}, None)
        body = json.loads(response["body"])

        assert response["statusCode"] == 201
        assert body["status"] == "PENDING"
        assert body["object_key"].startswith("uploads/u_demo/")
        assert "fields" in body and "url" in body

    def test_pending_upload_is_queryable_immediately(self, handlers):
        _, _, inventory_api = handlers

        create = inventory_api.handler({"routeKey": "POST /v1/uploads", "headers": {}}, None)
        upload_id = json.loads(create["body"])["upload_id"]

        status = inventory_api.handler(
            {
                "routeKey": "GET /v1/uploads/{upload_id}",
                "headers": {},
                "pathParameters": {"upload_id": upload_id},
            },
            None,
        )
        assert json.loads(status["body"])["status"] == "PENDING"

    def test_unknown_upload_id_returns_404(self, handlers):
        _, _, inventory_api = handlers

        response = inventory_api.handler(
            {
                "routeKey": "GET /v1/uploads/{upload_id}",
                "headers": {},
                "pathParameters": {"upload_id": "upl_yok"},
            },
            None,
        )
        assert response["statusCode"] == 404


class TestExtractor:
    def test_completes_the_upload_and_creates_items(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        upload_id, s3_event = _upload_and_notify(handlers, s3_client)

        result = extractor.handler(s3_event, None)
        assert result["processed"] == 1

        status = inventory_api.handler(
            {
                "routeKey": "GET /v1/uploads/{upload_id}",
                "headers": {},
                "pathParameters": {"upload_id": upload_id},
            },
            None,
        )
        body = json.loads(status["body"])
        assert body["status"] == "COMPLETED"
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "süzme yoğurt"
        assert body["items"][0]["estimated_freshness_date"]

    def test_duplicate_s3_event_is_skipped_not_reprocessed(self, handlers, s3_client):
        """Idempotency: aynı ObjectCreated olayı iki kez gelirse
        (S3'ün at-least-once garantisi) envanterde ikinci kayıt oluşmaz.
        """
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)

        first = extractor.handler(s3_event, None)
        second = extractor.handler(s3_event, None)

        assert first["processed"] == 1
        assert second["processed"] == 0

        items = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"]
        assert len(items) == 1

    def test_low_confidence_extraction_is_flagged_for_review(self, handlers, s3_client):
        from core.models import ExtractedFood, FieldConfidence, Quantity
        from core.taxonomy import FoodCategory, PackageState

        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(
            handlers,
            s3_client,
            foods=[
                ExtractedFood(
                    name="tanımsız paket",
                    category=FoodCategory.OTHER,
                    package_state=PackageState.UNKNOWN,
                    quantity=Quantity(value=1),
                    confidence=FieldConfidence(name=0.2, category=0.3),
                )
            ],
        )

        extractor.handler(s3_event, None)

        items = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"]
        assert items[0]["needs_review"] is True

    def test_unrecognized_object_key_is_skipped_without_crashing(self, handlers):
        """Yanlış prefix/formatta bir nesne kovaya düşerse (altyapı hatası)
        Lambda çökmemeli — sadece loglayıp atlamalı.
        """
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
    def test_patch_marks_item_consumed_and_removes_it_from_listing(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)

        items = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"]
        item_id = items[0]["item_id"]

        patch = inventory_api.handler(
            {
                "routeKey": "PATCH /v1/items/{item_id}",
                "headers": {},
                "pathParameters": {"item_id": item_id},
                "body": json.dumps({"state": "CONSUMED"}),
            },
            None,
        )
        assert patch["statusCode"] == 200
        assert json.loads(patch["body"])["state"] == "CONSUMED"

        remaining = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"]
        assert remaining == []

    def test_patch_can_correct_a_reserved_word_field(self, handlers, s3_client):
        """`name` DynamoDB'nin ayrılmış kelime listesindedir — bu regresyonu
        kalıcı olarak test eder (bkz. `adapters/repository.py` update_item).
        """
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)
        item_id = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"][0]["item_id"]

        patch = inventory_api.handler(
            {
                "routeKey": "PATCH /v1/items/{item_id}",
                "headers": {},
                "pathParameters": {"item_id": item_id},
                "body": json.dumps({"name": "düzeltilmiş süt"}),
            },
            None,
        )

        assert patch["statusCode"] == 200
        assert json.loads(patch["body"])["name"] == "düzeltilmiş süt"

    def test_patch_rejects_unknown_field(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)
        item_id = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"][0]["item_id"]

        patch = inventory_api.handler(
            {
                "routeKey": "PATCH /v1/items/{item_id}",
                "headers": {},
                "pathParameters": {"item_id": item_id},
                "body": json.dumps({"observation_id": "sahte"}),
            },
            None,
        )

        assert patch["statusCode"] == 400

    def test_patch_rejects_invalid_enum_value(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)
        item_id = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"][0]["item_id"]

        patch = inventory_api.handler(
            {
                "routeKey": "PATCH /v1/items/{item_id}",
                "headers": {},
                "pathParameters": {"item_id": item_id},
                "body": json.dumps({"category": "uzay_gidasi"}),
            },
            None,
        )

        assert patch["statusCode"] == 400

    def test_delete_removes_the_item(self, handlers, s3_client):
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)
        item_id = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"][0]["item_id"]

        delete_response = inventory_api.handler(
            {
                "routeKey": "DELETE /v1/items/{item_id}",
                "headers": {},
                "pathParameters": {"item_id": item_id},
            },
            None,
        )
        assert delete_response["statusCode"] == 204

        remaining = json.loads(
            inventory_api.handler({"routeKey": "GET /v1/items", "headers": {}}, None)["body"]
        )["items"]
        assert remaining == []

    def test_items_are_scoped_per_user(self, handlers, s3_client):
        """Farklı `x-user-id` header'ı ile istek yapan iki kullanıcı birbirinin
        envanterini görmemeli — kullanıcı bazlı izolasyon.
        """
        _, extractor, inventory_api = handlers
        _, s3_event = _upload_and_notify(handlers, s3_client)
        extractor.handler(s3_event, None)

        other_user_items = inventory_api.handler(
            {"routeKey": "GET /v1/items", "headers": {"x-user-id": "u_other"}}, None
        )
        assert json.loads(other_user_items["body"])["items"] == []
