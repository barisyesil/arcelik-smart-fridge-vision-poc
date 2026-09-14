"""Prompt sürüm kayıt defteri (Prompt Lab).

İki kaynak birleşir:
1. YERLEŞİK sürümler — kodda tanımlı. İlki her zaman ÜRETİM promptudur
   (`core.extraction.SYSTEM_PROMPT`); mobil ve gerçek Lambda bunu kullanır, bu
   yüzden Lab'da "referans" olarak görünür ama düzenlenemez (kopyalayıp yeni
   sürüm oluşturabilirsin). Kalanlar deney için başlangıç varyantlarıdır.
2. KAYITLI sürümler — `prompt_versions.json` içinde. Lab UI'dan kaydettiğin
   promptlar buraya yazılır; yeniden başlatınca kaybolmaz. Dosya .gitignore'da,
   yani her mühendisin kendi deney seti kendine özeldir.

Yerleşik promptlar üretimin şemasını/parse'ını kullanır — yani yalnızca sistem
promptu metni değişir, çıktı sözleşmesi (ürün grubu + sayım/aralık + kutu) sabit
kalır. Böylece farklı promptların ölçümü elmayla elma karşılaştırması olur.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.extraction import PROMPT_VERSION, SYSTEM_PROMPT

_STORE_PATH = Path(__file__).resolve().parent / "prompt_versions.json"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class PromptVersion:
    id: str
    label: str
    description: str
    system_prompt: str
    #: "builtin" (kodda, düzenlenemez) ya da "saved" (JSON'da, düzenlenebilir).
    source: str
    #: Yerleşik üretim promptu mu? UI bunu "referans / mobil bunu kullanır"
    #: rozetiyle işaretleyebilir.
    is_production: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "source": self.source,
            "is_production": self.is_production,
            "editable": self.source == "saved",
        }


# --- Deneysel yerleşik varyantlar (başlangıç noktaları) ---------------------

_STRICT_COUNT = """Sen bir buzdolabı envanter asistanısın. Fotoğraftaki her farklı
gıda ürününü ürün grubu bazında listele. Aynı üründen kaç adet varsa TEK satırda
say (10 domates = tek "domates" satırı, value=10; 10 ayrı satır DEĞİL).

ÖNCELİK: Mümkün olan her yerde KESİN sayı ver. Yalnızca fiziksel olarak
sayılması imkânsızsa (tamamen üst üste yığılı, arkadakiler hiç görünmüyor)
`value_max` ile dar bir aralık ver. Belirsizsen bile en olası tek sayıyı tercih
et; gereksiz aralık verme.

Birimi en doğal haliyle seç (tane, paket, koli, şişe, demet, torba, karton).
Marka `brand` alanına, ürün adı sade ve Türkçe `name` alanına yazılır. Kategori,
alt kategori, ambalaj durumu yalnızca verilen listelerden. Her ürün grubu için
grubun tamamını çevreleyen tek bir `box_2d` kutusu ver.

Tarih okuma/üretme. Gıda olmayan nesneleri listeleme. Emin olmadığın ürünü
düşük güven skoruyla yine de listele."""

_RANGE_FRIENDLY = """Sen bir buzdolabı envanter asistanısın. Fotoğraftaki gıdaları
ürün grubu bazında listele; aynı üründen çok adet varsa TEK satırda topla.

Sayım felsefesi: Gerçekçi ol. Net sayabildiğini kesin ver, ama emin olmadığın
hiçbir sayıyı KESİNMİŞ gibi verme — bunun yerine `value` (alt sınır) ve
`value_max` (üst sınır) ile dürüst bir aralık ver. Aralık gerçek belirsizliği
yansıtsın (ör. yaklaşık 8-10 -> value=8, value_max=10). Kullanıcı için "yaklaşık
ne kadar" bilgisi, yanlış bir kesin sayıdan daha değerlidir.

Birimi en doğal haliyle seç (tane, paket, koli, şişe, demet, torba, karton).
`name` sade ve Türkçe, marka `brand`'e. Kategori/alt kategori/ambalaj yalnızca
verilen listelerden. Her grup için grubu çevreleyen tek `box_2d` ver.

Tarih okuma/üretme. Gıda olmayanı listeleme. Emin değilsen düşük güven skoru ver."""

_MINIMAL = """Fotoğraftaki yenilebilir gıdaları ürün grubu olarak listele. Aynı
üründen kaç adet varsa tek satırda say (value). Emin değilsen value_max ile
aralık ver. Birim: tane/paket/koli/şişe/demet/torba/karton. Ürün adını Türkçe ve
sade yaz, markayı ayır. Her grup için bir box_2d kutusu ver. Tarih üretme."""


def _builtin_versions() -> list[PromptVersion]:
    return [
        PromptVersion(
            id=f"production-{PROMPT_VERSION}",
            label=f"Üretim ({PROMPT_VERSION})",
            description=(
                "Gerçek sistem promptu — mobil ve Lambda bunu kullanır. "
                "Referans; düzenlemek için kopyalayıp yeni sürüm oluştur."
            ),
            system_prompt=SYSTEM_PROMPT,
            source="builtin",
            is_production=True,
        ),
        PromptVersion(
            id="exp-strict-count",
            label="Deney · Kesin sayım",
            description="Aralık yerine kesin sayıyı zorlar; sıkı gruplama.",
            system_prompt=_STRICT_COUNT,
            source="builtin",
        ),
        PromptVersion(
            id="exp-range-friendly",
            label="Deney · Aralık dostu",
            description="Belirsizlikte dürüst aralık vermeyi teşvik eder.",
            system_prompt=_RANGE_FRIENDLY,
            source="builtin",
        ),
        PromptVersion(
            id="exp-minimal",
            label="Deney · Minimal",
            description="Kısa prompt; token maliyeti/etkisini kıyaslamak için.",
            system_prompt=_MINIMAL,
            source="builtin",
        ),
    ]


# --- Kayıtlı sürümler (JSON kalıcılığı) -------------------------------------


def _load_saved() -> dict[str, dict]:
    if not _STORE_PATH.exists():
        return {}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_saved(store: dict[str, dict]) -> None:
    _STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def _saved_versions() -> list[PromptVersion]:
    out: list[PromptVersion] = []
    for vid, rec in _load_saved().items():
        out.append(
            PromptVersion(
                id=vid,
                label=rec.get("label") or vid,
                description=rec.get("description") or "",
                system_prompt=rec.get("system_prompt") or "",
                source="saved",
            )
        )
    return out


def list_versions() -> list[PromptVersion]:
    """Yerleşik + kayıtlı tüm sürümler; üretim promptu her zaman ilk sırada."""
    return _builtin_versions() + _saved_versions()


def get_version(version_id: str) -> PromptVersion | None:
    for version in list_versions():
        if version.id == version_id:
            return version
    return None


class PromptError(ValueError):
    """Geçersiz prompt kaydı (id çakışması, boş metin, yerleşik üzerine yazma)."""


def save_version(
    version_id: str, label: str, description: str, system_prompt: str
) -> PromptVersion:
    """Yeni bir sürüm oluştur ya da mevcut KAYITLI sürümü güncelle.

    Yerleşik (üretim/deney) sürümlerin id'si korunur — üzerine yazılamaz; onları
    değiştirmek istiyorsan farklı bir id ile kaydet. Böylece üretim promptu
    Lab'dan yanlışlıkla ezilmez.
    """
    version_id = (version_id or "").strip().lower()
    if not _ID_RE.match(version_id):
        raise PromptError("id 1-64 karakter olmalı; küçük harf, rakam ve . _ - içerebilir.")
    if any(b.id == version_id for b in _builtin_versions()):
        raise PromptError(f"'{version_id}' yerleşik bir sürüm; üzerine yazılamaz.")
    if not (system_prompt or "").strip():
        raise PromptError("system_prompt boş olamaz.")

    store = _load_saved()
    store[version_id] = {
        "label": (label or version_id).strip(),
        "description": (description or "").strip(),
        "system_prompt": system_prompt,
    }
    _write_saved(store)
    return PromptVersion(
        id=version_id,
        label=store[version_id]["label"],
        description=store[version_id]["description"],
        system_prompt=system_prompt,
        source="saved",
    )


def delete_version(version_id: str) -> bool:
    """Kayıtlı bir sürümü sil. Yerleşik sürüm silinemez (False döner)."""
    store = _load_saved()
    if version_id not in store:
        return False
    del store[version_id]
    _write_saved(store)
    return True
