"""Uygulama (handler'lar) ile altyapı (CDK) arasındaki sözleşme yüzeyini kilitler.

Handler adları, ortam değişkeni adları ve API rotaları iki tarafta ayrı ayrı
yazılır; bu yüzeyde sessiz bir ayrışma (birinin `BUCKET_NAME`, diğerinin
`RAW_BUCKET` yazması gibi) ancak `cdk deploy` sonrası çalışma zamanında fark
edilir. Bu test o ayrışmayı deploy'dan önce yakalar.
"""

from __future__ import annotations

import importlib
import json

import pytest

#: CDK bunları `handler=` olarak yazar. Sadece iki Lambda var (fridge-api,
#: fridge-extractor) — `handlers.presign` bilerek burada yok, kendi başına bir
#: Lambda değil.
HANDLER_ENTRYPOINTS = {
    "handlers.inventory_api": "handler",  # fridge-api
    "handlers.extractor": "handler",  # fridge-extractor
}

#: CDK bunları `environment={...}` olarak verir.
EXPECTED_ENV_VARS = {
    "handlers.presign": {"BUCKET_NAME"},
    "handlers.extractor": {"TABLE_NAME", "GEMINI_PARAM_NAME"},
    "handlers.inventory_api": {"TABLE_NAME"},
}

#: API Gateway'de rota olarak tanımlanan, dondurulmuş kontrat (mobil kapsam).
FROZEN_ROUTES = {
    # Profil & kimlik
    "GET /v1/users/me",
    "PUT /v1/users/me",
    "PUT /v1/users/me/notification-preferences",
    "POST /v1/devices",
    "DELETE /v1/devices/{installation_id}",
    # Yükleme
    "POST /v1/uploads",
    "GET /v1/uploads/{upload_id}",
    # Envanter
    "GET /v1/items",
    "PATCH /v1/items/{item_id}",
    "DELETE /v1/items/{item_id}",
    "POST /v1/items/{item_id}/actions",
    "POST /v1/items/{item_id}/freshness-assessments",
    "PUT /v1/items/{item_id}/reminder",
    "DELETE /v1/items/{item_id}/reminder",
    # Aksiyon geri alma
    "POST /v1/item-actions/{action_id}/undo",
    # Kontrol kuyruğu
    "GET /v1/review-queue",
    # Alışveriş
    "GET /v1/shopping-lists/current",
    "POST /v1/shopping-lists/current/items",
    "PATCH /v1/shopping-lists/current/items/{shopping_item_id}",
    "DELETE /v1/shopping-lists/current/items/{shopping_item_id}",
    # Öneriler
    "GET /v1/replacement-candidates",
    "POST /v1/replacement-candidates/{candidate_id}/accept",
    "POST /v1/replacement-candidates/{candidate_id}/dismiss",
    # Tarifler
    "GET /v1/recipes/recommendations",
}


@pytest.mark.parametrize(("module_name", "func_name"), HANDLER_ENTRYPOINTS.items())
def test_handler_entrypoint_exists_and_is_callable(module_name, func_name):
    module = importlib.import_module(module_name)
    assert callable(getattr(module, func_name, None)), (
        f"{module_name}.{func_name} yok — CDK'daki handler referansı kırılır"
    )


def test_presign_is_not_a_second_lambda_handler_on_the_same_function():
    """Bir Lambda'nın tek `handler=` değeri olabilir.

    `presign` ve `inventory_api` aynı `fridge-api` Lambda'sına gidiyor;
    presign kendi `handler` adında bir fonksiyon EXPORT ETMEMELİ, yoksa CDK
    tarafında "hangisini yazacağım" diye aynı çelişki geri gelir.
    """
    from handlers import presign

    assert not hasattr(presign, "handler")
    assert callable(presign.create_upload)


@pytest.mark.parametrize(("module_name", "expected"), EXPECTED_ENV_VARS.items())
def test_module_reads_the_agreed_env_var_names(module_name, expected):
    module = importlib.import_module(module_name)
    declared = {name for name in dir(module) if name.isupper()}
    missing = expected - declared
    assert not missing, f"{module_name} şu ortam değişkenlerini okumuyor: {missing}"


def test_route_list_matches_the_frozen_api_contract():
    from handlers.inventory_api import ROUTES

    assert set(ROUTES) == FROZEN_ROUTES


def test_unknown_route_returns_404_without_touching_aws():
    """Bilinmeyen rota, gerçek rotaların dispatch mantığına hiç girmeden
    404 döner — bu yüzden AWS'ye dokunmadan, moto olmadan test edilebilir.
    Gerçek rotaların uçtan uca davranışı `tests/integration/`'da (moto ile).
    """
    from handlers.inventory_api import handler

    response = handler({"routeKey": "GET /v1/kediler", "headers": {}}, None)

    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"] == "unknown_route"


def test_extractor_parses_the_s3_event_shape():
    """S3 olay bildirimi bu şekli gönderir."""
    from handlers.extractor import _s3_records

    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "fridge-raw-000"},
                    "object": {"key": "uploads/u_demo/2026-03-10/abc.jpg", "eTag": "d41d8c"},
                }
            }
        ]
    }
    (record,) = _s3_records(event)

    assert record["bucket"] == "fridge-raw-000"
    assert record["key"].startswith("uploads/")
    assert record["etag"] == "d41d8c"


def test_extractor_survives_a_malformed_event():
    """Bozuk olay Lambda'yı çökertip DLQ alarmını çaldırmamalı."""
    from handlers.extractor import handler

    assert handler({"Records": [{"s3": {}}]}, None)["processed"] == 0


def test_presign_conditions_enforce_size_and_content_type():
    """Boyut ve içerik tipi şartları olmadan presigned POST'un anlamı yok."""
    from handlers.presign import PRESIGN_CONDITIONS, UPLOAD_PREFIX

    size_rule = next(c for c in PRESIGN_CONDITIONS if c[0] == "content-length-range")
    type_rule = next(c for c in PRESIGN_CONDITIONS if c[0] == "starts-with")

    assert size_rule[1:] == [1024, 5 * 1024 * 1024]
    assert type_rule[1:] == ["$Content-Type", "image/"]
    # S3 olay filtresi bu prefix'e bağlı.
    assert UPLOAD_PREFIX == "uploads/"
