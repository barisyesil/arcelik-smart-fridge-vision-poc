"""taxonomy.py ile shelf_life.json senkron mu?

Bu iki dosyanın ayrışması sessiz bir hata üretir: yeni kategori global default'a
düşer ve kimse fark etmez. Testin işi bunu gürültülü hale getirmek.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.taxonomy import SUBCATEGORIES, FoodCategory

DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "src" / "core" / "shelf_life.json").read_text(
        encoding="utf-8"
    )
)
DAY_KEYS = ("unopened_days", "opened_days")
#: unopened_source/opened_source ayrı tutulur çünkü kaynak tablonun çoğu
#: kalemi "kapalıda ambalaj tarihi esastır" der — iki durumun kaynağı
#: farklı olabilir (freshness.py._pick docstring'i).
SOURCE_KEYS = ("unopened_source", "opened_source")


@pytest.mark.parametrize("category", list(FoodCategory))
def test_every_category_has_an_entry(category):
    assert category.value in DATA["categories"], f"{category.value} shelf_life.json'da yok"


@pytest.mark.parametrize("category", list(FoodCategory))
def test_category_default_is_complete(category):
    default = DATA["categories"][category.value]["default"]
    assert all(isinstance(default.get(k), int) and default[k] > 0 for k in DAY_KEYS)
    assert all(default.get(k) for k in SOURCE_KEYS)


def test_no_unknown_subcategories_in_data():
    for cat_name, entry in DATA["categories"].items():
        allowed = set(SUBCATEGORIES[FoodCategory(cat_name)])
        found = set(entry.get("subcategories", {}))
        assert found <= allowed, f"{cat_name}: taksonomide olmayan alt kategori {found - allowed}"


def test_every_declared_subcategory_has_shelf_life_data():
    """Taksonomide olup tabloda olmayan alt kategori sessizce kategoriye düşer."""
    missing = {
        category.value: sorted(
            set(subs) - set(DATA["categories"][category.value].get("subcategories", {}))
        )
        for category, subs in SUBCATEGORIES.items()
        if set(subs) - set(DATA["categories"][category.value].get("subcategories", {}))
    }
    assert not missing, f"raf ömrü verisi eksik alt kategoriler: {missing}"


def test_unopened_is_never_shorter_than_opened():
    """Açılmış ambalaj kapalıdan uzun ömürlü olamaz — veri girişi hatası yakalar."""
    for cat_name, entry in DATA["categories"].items():
        rows = [("default", entry["default"])] + list(entry.get("subcategories", {}).items())
        for label, row in rows:
            assert row["unopened_days"] >= row["opened_days"], f"{cat_name}.{label} tutarsız: {row}"


def test_every_row_declares_both_sources():
    """unopened_source VE opened_source ayrı ayrı zorunlu.

    Kaynak tablonun çoğu kalemi için kapalı-durum tahmini bizim kendi
    varsayımımız ("lit."), açık-durum ise USDA/FDA atıflı — tek bir `source`
    alanı bu ikisini karıştırıp yanlış atıf yapardı.
    """
    rows = [("global_default", DATA["global_default"])]
    for cat_name, entry in DATA["categories"].items():
        rows.append((f"{cat_name}.default", entry["default"]))
        rows += [(f"{cat_name}.{k}", v) for k, v in entry.get("subcategories", {}).items()]

    missing = [f"{label}.{key}" for label, row in rows for key in SOURCE_KEYS if not row.get(key)]
    assert not missing, f"kaynak alanı eksik: {missing}"


def test_rule_id_when_present_points_into_the_archived_source_file():
    """rule_id verilmişse docs/kaynaklar/shelf-life-rules.v1.json'daki bir
    kurala işaret etmeli — izlenebilirlik kopmasın.
    """
    source_path = (
        Path(__file__).resolve().parents[2] / "docs" / "kaynaklar" / "shelf-life-rules.v1.json"
    )
    source_data = json.loads(source_path.read_text(encoding="utf-8"))
    known_rule_ids = {rule["rule_id"] for rule in source_data["rules"]}

    referenced = set()
    for entry in DATA["categories"].values():
        rows = [entry["default"], *entry.get("subcategories", {}).values()]
        referenced.update(row["rule_id"] for row in rows if row.get("rule_id"))

    assert referenced <= known_rule_ids, referenced - known_rule_ids
