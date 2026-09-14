"""Kapalı kategori taksonomisi.

Bu dosya iki işi aynı anda yapar ve bu bilinçli bir tercihtir:
1. İş mantığının kategori tanımı,
2. Gemini `response_schema` içine gömülecek enum listesinin kaynağı.

Tek kaynak olması, `core/` ile LLM sözleşmesi arasında sessizce ayrışan iki
liste olma riskini ortadan kaldırır.

Değerler küçük harf ve API kontratının parçasıdır. `GET /v1/uploads/{id}`
yanıtında `"category": "dairy"` biçiminde istemciye gider; değiştirmek istemciyi
kırar.

Alt kategori granülaritesi `docs/kaynaklar/shelf-life-rules.v1.json`
(USDA FoodKeeper / FoodSafety.gov / FDA) ile hizalıdır — o dosya gerçek atıflı
verinin kaynağıdır. O tabloda olmayan alt kategoriler (`fresh_herb`, `garlic`,
`berry`, `oil`, `pate` gibi) tahmindir ve `shelf_life.json`'da `source: "lit."`
ile işaretlenir.

Yeni kategori eklerken `shelf_life.json` da güncellenmelidir;
`tests/unit/test_shelf_life_data.py` ikisinin senkron kaldığını doğrular.
"""

from __future__ import annotations

from enum import StrEnum


class FoodCategory(StrEnum):
    """Kapalı kategori kümesi. Model bunun dışında bir değer üretemez.

    `deli` ve `preserves_pickles` başlangıç listesinde yoktu, sonradan eklendi:
    - `deli`: sucuk/pastırma/salam `other`'a düşüp 5 günlük varsayılan alıyordu;
      gerçek değeri kapalı ambalajda ~30 gün.
    - `preserves_pickles`: turşu/reçel/konserve `condiment_sauce` ve `pantry_dry`'a
      zorla dağıtılmıştı; kaynak tablo bunu kendi başına bir grup olarak ele alıyor.
    """

    DAIRY = "dairy"
    MEAT_POULTRY = "meat_poultry"
    DELI = "deli"
    FISH_SEAFOOD = "fish_seafood"
    EGG = "egg"
    PRODUCE_VEGETABLE = "produce_vegetable"
    PRODUCE_FRUIT = "produce_fruit"
    BAKERY = "bakery"
    PREPARED_LEFTOVER = "prepared_leftover"
    BEVERAGE = "beverage"
    CONDIMENT_SAUCE = "condiment_sauce"
    PRESERVES_PICKLES = "preserves_pickles"
    PANTRY_DRY = "pantry_dry"
    FROZEN = "frozen"
    OTHER = "other"


class PackageState(StrEnum):
    """Ambalaj durumu — raf ömrünü kategoriden bazen daha çok etkiler.

    İki durum yeterli: bariyer sağlam mı, değil mi. Ambalajsız ürün (domates,
    artık yemek) `opened` sayılır. `unknown` ayrı tutulur ve `freshness.py` bunu
    "en muhafazakâr değeri seç" olarak yorumlar — modele "bilmiyorum" deme hakkı
    vermek, onu tahmin uydurmaya zorlamaktan daha güvenli.
    """

    UNOPENED = "unopened"
    OPENED = "opened"
    UNKNOWN = "unknown"


#: Kategori -> izinli alt kategoriler. Alt kategori de kapalıdır.
SUBCATEGORIES: dict[FoodCategory, tuple[str, ...]] = {
    FoodCategory.DAIRY: (
        "milk_uht",
        "milk_fresh",
        "yogurt",
        "cheese_hard",
        "cheese_soft",
        "ayran",
        "kefir",
        "butter",
        "cream",
        "other_dairy",
    ),
    FoodCategory.MEAT_POULTRY: (
        # Kaynak tablo kesime göre ayırıyor (cinse göre değil) — kıyma, sığır
        # kıymasından çok daha çabuk bozulur; kesim tazelik için cinsten daha
        # belirleyici.
        "ground_meat",
        "cubed_meat",
        "steak_chop",
        "chicken",
        "turkey",
        "offal",
        "cooked_meat",
        "other_meat",
    ),
    FoodCategory.DELI: (
        # Sosis işlenmiş bir şarküteri ürünü, çiğ et değil — kaynak tablo da
        # böyle sınıflıyor.
        "sucuk",
        "salami",
        "sausage",
        "pastirma",
        "ham",
        "kavurma",
        "pate",
        "other_deli",
    ),
    FoodCategory.FISH_SEAFOOD: (
        "fish",
        "shrimp",
        "mussel",
        "squid",
        "canned_fish",
        "other_seafood",
    ),
    FoodCategory.EGG: (
        "shell_egg",
        "quail_egg",
        "boiled_egg",
    ),
    FoodCategory.PRODUCE_VEGETABLE: (
        # Soğan/patates/havuç ayrı ayrı ele alınıyor; raf ömürleri gerçekten
        # farklı (soğan ~45 gün, patates/havuç ~21 gün).
        "tomato",
        "cucumber",
        "pepper",
        "eggplant",
        "zucchini",
        "leafy",
        "onion",
        "garlic",
        "potato",
        "carrot",
        "mushroom",
        "brassica",
        "bean_pea",
        "fresh_herb",
        "other_vegetable",
    ),
    FoodCategory.PRODUCE_FRUIT: (
        # Elma ve armut ayrı: kaynakta elma 35 gün, armut 5 gün — birleşik değer
        # armudu ciddi şekilde bayat gösteriyordu.
        "apple",
        "pear",
        "banana",
        "citrus",
        "lemon",
        "strawberry",
        "berry",
        "grape",
        "melon",
        "stone_fruit",
        "avocado",
        "other_fruit",
    ),
    FoodCategory.BAKERY: (
        "bread",
        "pastry",
        "cake",
    ),
    FoodCategory.PREPARED_LEFTOVER: (
        "cooked_meat_dish",
        "cooked_vegetable_dish",
        "soup",
        "rice_pasta",
        "dressed_salad",
    ),
    FoodCategory.BEVERAGE: (
        "water",
        "fresh_juice",
        "packaged_juice",
        "soda",
        "iced_tea",
        "energy_drink",
        "herbal_tea",
        "alcohol",
        "other_beverage",
    ),
    FoodCategory.CONDIMENT_SAUCE: (
        # Mayonezin gıda güvenliği riski ketçaptan farklı ve ömrü çok daha kısa;
        # bu yüzden ayrı tutuluyorlar.
        "ketchup",
        "mayo",
        "mustard",
        "tomato_paste",
        "vinegar",
        "oil",
        "dressing",
        "spice",
        "other_sauce",
    ),
    FoodCategory.PRESERVES_PICKLES: (
        "pickle",
        "olive",
        "canned_vegetable",
        "canned_fruit",
        "jam",
        "honey",
        "other_preserve",
    ),
    FoodCategory.PANTRY_DRY: (
        "flour_grain",
        "dry_pasta_rice",
        "dry_legume",
        "nuts_seeds",
    ),
    FoodCategory.FROZEN: (
        "frozen_vegetable",
        "frozen_meat",
        "frozen_potato",
        "frozen_pastry",
        "frozen_fish",
        "frozen_ready_meal",
        "ice_cream",
        "other_frozen",
    ),
    FoodCategory.OTHER: ("unknown_food",),
}

#: Adet birimi de kapalı liste — `quantity.unit` API yanıtında görünüyor.
#: Model aynı üründen çok sayıda adedi tek satırda toplarken en doğal birimi
#: seçer: tek tek sayılabilenler "piece" (tane), ambalajlılar "pack"/"box",
#: demet halindekiler "bunch", torbadakiler "bag". Ağırlık/hacim birimleri
#: (gram/milliliter) dökme ürünler için. Enum anahtarları İngilizce; Türkçe
#: karşılıkları web `labels.ts` içinde (piece->tane, box->koli, bunch->demet).
QUANTITY_UNITS: tuple[str, ...] = (
    "piece",
    "pack",
    "box",
    "bottle",
    "bunch",
    "bag",
    "carton",
    "gram",
    "milliliter",
)


def category_values() -> list[str]:
    """Gemini `response_schema` içine gömülecek kategori enum listesi."""
    return [c.value for c in FoodCategory]


def subcategory_values() -> list[str]:
    """Tüm alt kategoriler, düz liste.

    Gemini'nin JSON şeması iç içe koşullu enum (kategoriye bağlı alt kategori)
    desteklemediği için düz liste veriliyor; kategori-alt kategori uyumu
    `is_valid_subcategory` ile doğrulanır. Uyumsuz gelen alt kategori atılır,
    kategori korunur.
    """
    return sorted({s for subs in SUBCATEGORIES.values() for s in subs})


def package_state_values() -> list[str]:
    return [p.value for p in PackageState]


def is_valid_subcategory(category: FoodCategory, subcategory: str | None) -> bool:
    if subcategory is None:
        return True
    return subcategory in SUBCATEGORIES.get(category, ())
