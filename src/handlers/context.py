"""İstek bağlamı: doğrulanmış kullanıcı + bağlı olduğu buzdolabı.

Veri buzdolabı bazında partition'landığı için (hane modeli), her veri isteğinde
kullanıcının hangi dolaba ait olduğunu profilinden çözeriz. Kimlik doğrulanmış
JWT `sub`'tan gelir; sahiplik = o dolaba kayıtlı olmak.
"""

from __future__ import annotations

from dataclasses import dataclass

from adapters.repository import DynamoRepository
from handlers._http import authenticated_user_id, respond


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    fridge_id: str


class ContextError(Exception):
    """Bağlam çözülemedi; `response` doğrudan istemciye döner."""

    def __init__(self, response: dict) -> None:
        super().__init__("context_error")
        self.response = response


def require_user(event: dict) -> str:
    """Doğrulanmış kullanıcı kimliği; yoksa 401."""
    user_id = authenticated_user_id(event)
    if not user_id:
        raise ContextError(respond(401, {"error": "unauthorized"}))
    return user_id


def resolve_context(event: dict, repo: DynamoRepository) -> RequestContext:
    """Kullanıcı + buzdolabı bağlamı. Profil yoksa 409 (önce kayıt gerekli)."""
    user_id = require_user(event)
    profile = repo.get_profile(user_id)
    if profile is None:
        raise ContextError(
            respond(409, {"error": "profile_required", "detail": "Önce profil oluşturun."})
        )
    return RequestContext(user_id=user_id, fridge_id=profile.fridge_id)
