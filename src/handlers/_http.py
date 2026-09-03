"""HTTP API v2 yanıt yardımcıları. Handler'ların tek ortak parçası.

Burada iş mantığı yok — sadece "dict'i HTTP yanıtına çevir". `core/`'a
koymadık çünkü HTTP bir taşıma detayı; `core/` protokol tanımaz.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "u_demo")

_CORS_HEADERS = {
    # Asıl CORS API Gateway'de tanımlı. Bunlar Lambda doğrudan çağrıldığında
    # (konsol testi) yanıtı okunabilir tutmak için.
    "content-type": "application/json; charset=utf-8",
}


def respond(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def respond_empty(status: int) -> dict[str, Any]:
    """204 gibi gövdesiz yanıtlar için — `respond(204, {})` "{}" gövdesi
    döndürür, bu da bazı istemcilerde JSON parse denemesine yol açar.
    """
    return {"statusCode": status, "headers": {}, "body": ""}


def json_body(event: dict[str, Any]) -> dict[str, Any]:
    """PATCH gövdesini ayrıştırır. Bozuk/boş gövde -> boş dict (hata değil;
    çağıran taraf beklenen alanların eksikliğini kendi doğrular).
    """
    raw = event.get("body")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def path_param(event: dict[str, Any], name: str) -> str | None:
    return (event.get("pathParameters") or {}).get(name)


def not_implemented(route: str) -> dict[str, Any]:
    """Henüz yazılmamış rota.

    501 döndürülür (exception değil): 501, API Gateway -> Lambda -> IAM
    zincirinin çalıştığını kanıtlar; exception 502 döndürür ve altyapı hatasıyla
    eksik uygulamayı ayırt edilemez hale getirir.
    """
    logger.info(json.dumps({"event": "route_not_implemented", "route": route}))
    return respond(501, {"error": "not_implemented", "route": route})


def user_id_from(event: dict[str, Any]) -> str:
    """Kimlik header'dan okunur. Faz 1'de kimlik doğrulama yoktur."""
    headers = event.get("headers") or {}
    return headers.get("x-user-id") or DEFAULT_USER_ID


def route_key(event: dict[str, Any]) -> str:
    return event.get("routeKey") or "UNKNOWN"
