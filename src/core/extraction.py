"""LLM sözleşmesi: istem şeması + yanıt ayrıştırma. Saf Python, SDK yok.

Gemini SDK'sı `adapters/vision.py` içinde; burada sadece "modelden ne isteriz"
ve "gelen JSON'u nasıl güvene alırız" var. Bu ayrım sayesinde başka bir
sağlayıcıya geçiş bu dosyayı hiç açmadan yapılabilir.

Şemada tarih alanı yoktur ve olmayacaktır — tarih `freshness.py`'de hesaplanır.
"""

from __future__ import annotations

from core.models import ExtractedFood, FieldConfidence, Quantity
from core.taxonomy import (
    QUANTITY_UNITS,
    FoodCategory,
    PackageState,
    category_values,
    is_valid_subcategory,
    package_state_values,
    subcategory_values,
)

#: Prompt versiyonu her Observation kaydına yazılır. Bu metni değiştirdiğinizde
#: burayı da artırın — yoksa doğruluk ölçümü iki farklı prompt'u karıştırır.
PROMPT_VERSION = "v1"

#: Türkçe/İngilizce karışık ürün adları beklendiği için çıktı dili açıkça
#: sabitleniyor — aksi halde aynı ürün iki farklı isimle envantere iki kez girer.
SYSTEM_PROMPT = """Sen bir buzdolabı envanter asistanısın.
Verilen fotoğraftaki YENİLEBİLİR gıda ürünlerini listele.

Kurallar:
- `name` alanını Türkçe, tekil ve sade yaz (örn. "süt", "kaşar peyniri", "domates").
  Marka adını `name` içine KOYMA; ayrı `brand` alanı var.
- `raw_label` alanına ambalajda gördüğün etiketi aynen yaz. Etiket yoksa boş bırak.
- Kategori, alt kategori ve ambalaj durumunu yalnızca verilen listelerden seç.
- Alt kategori kategoriye ait olmalı. Uygun alt kategori yoksa boş bırak.
- Ambalaj durumundan emin değilsen "unknown" yaz.
- Fotoğraftaki hiçbir tarihi OKUMA ve tarih ÜRETME. Raf ömrü tahmini yapma.
- Gıda olmayan nesneleri (tabak, bıçak, buzdolabı rafı) listeleme.
- Emin olmadığın ürünü düşük güven skoruyla yine de listele, atlama.
- Her alan için 0.0-1.0 arası güven skoru ver. Emin değilsen düşük ver;
  düşük skor bir hata değil, sistemin işine yarayan bir bilgi.
"""


def build_response_schema() -> dict:
    """Gemini `response_schema` (OpenAPI alt kümesi).

    Kategori ve alt kategori enum olarak gömülür; model serbest metin üretemez.
    Bu, çıktıyı ayrıştırmadan önce doğrulamanın en ucuz yolu — doğrulamayı
    modelin kendisine yaptırıyoruz.
    """
    return {
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "raw_label": {"type": "string"},
                        "brand": {"type": "string"},
                        "category": {"type": "string", "enum": category_values()},
                        "subcategory": {"type": "string", "enum": subcategory_values()},
                        "package_state": {"type": "string", "enum": package_state_values()},
                        "quantity": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "integer"},
                                "unit": {"type": "string", "enum": list(QUANTITY_UNITS)},
                            },
                            "required": ["value", "unit"],
                        },
                        "confidence": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "number"},
                                "category": {"type": "number"},
                            },
                            "required": ["name", "category"],
                        },
                    },
                    "required": ["name", "category", "quantity", "confidence"],
                },
            }
        },
        "required": ["products"],
    }


def _clamp_confidence(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse_quantity(raw: object) -> Quantity:
    if not isinstance(raw, dict):
        return Quantity(value=1)
    try:
        value = max(1, int(raw.get("value", 1)))
    except (TypeError, ValueError):
        value = 1
    unit = raw.get("unit")
    return Quantity(value=value, unit=unit if unit in QUANTITY_UNITS else "piece")


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def parse_extraction(payload: dict) -> list[ExtractedFood]:
    """Model çıktısını `ExtractedFood` listesine çevir.

    Şema enum'ları modeli zorlasa da yanıtın geçerli olduğu varsayılmaz; bozuk
    bir kayıt tüm fotoğrafı düşürmesin diye kayıt bazında eleme yapılır. Uyumsuz
    alt kategori atılır ama kategori korunur — kategori tazelik hesabı için
    yeterlidir, alt kategori sadece hassasiyet katar.
    """
    foods: list[ExtractedFood] = []

    for raw in payload.get("products") or []:
        if not isinstance(raw, dict):
            continue

        name = _clean_str(raw.get("name"))
        if not name:
            continue

        try:
            category = FoodCategory(raw.get("category"))
        except ValueError:
            category = FoodCategory.OTHER

        subcategory = _clean_str(raw.get("subcategory"))
        if not is_valid_subcategory(category, subcategory):
            subcategory = None

        try:
            package_state = PackageState(raw.get("package_state"))
        except ValueError:
            package_state = PackageState.UNKNOWN

        confidence_raw = raw.get("confidence")
        confidence_raw = confidence_raw if isinstance(confidence_raw, dict) else {}

        foods.append(
            ExtractedFood(
                name=name,
                raw_label=_clean_str(raw.get("raw_label")),
                brand=_clean_str(raw.get("brand")),
                category=category,
                subcategory=subcategory,
                package_state=package_state,
                quantity=_parse_quantity(raw.get("quantity")),
                confidence=FieldConfidence(
                    name=_clamp_confidence(confidence_raw.get("name")),
                    category=_clamp_confidence(confidence_raw.get("category")),
                ),
            )
        )

    return foods
