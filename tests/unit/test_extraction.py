from __future__ import annotations

from core.extraction import build_response_schema, parse_extraction
from core.taxonomy import FoodCategory, PackageState


def _product(**overrides):
    base = {
        "name": "süzme yoğurt",
        "raw_label": "Sütaş Süzme Yoğurt 750g",
        "brand": "Sütaş",
        "category": "dairy",
        "subcategory": "yogurt",
        "package_state": "unopened",
        "quantity": {"value": 1, "unit": "piece"},
        "confidence": {"name": 0.91, "category": 0.97},
    }
    return {**base, **overrides}


def test_schema_has_no_date_field_anywhere():
    """LLM'e asla tarih sordurulmaz. Şema bunu yapısal olarak imkânsız kılar."""
    props = build_response_schema()["properties"]["products"]["items"]["properties"]
    assert not any("date" in key or "expir" in key or "shelf" in key for key in props)


def test_schema_locks_category_to_the_closed_enum():
    props = build_response_schema()["properties"]["products"]["items"]["properties"]
    assert set(props["category"]["enum"]) == {c.value for c in FoodCategory}


def test_parses_a_well_formed_response():
    (food,) = parse_extraction({"products": [_product()]})
    assert food.name == "süzme yoğurt"
    assert food.brand == "Sütaş"
    assert food.raw_label == "Sütaş Süzme Yoğurt 750g"
    assert food.category is FoodCategory.DAIRY
    assert food.package_state is PackageState.UNOPENED
    assert food.quantity.value == 1
    assert food.quantity.unit == "piece"
    assert food.confidence.name == 0.91


def test_unknown_category_degrades_to_other_instead_of_crashing():
    (food,) = parse_extraction({"products": [_product(category="uzay_yemegi", subcategory=None)]})
    assert food.category is FoodCategory.OTHER


def test_mismatched_subcategory_is_dropped_but_category_survives():
    (food,) = parse_extraction(
        {"products": [_product(category="produce_fruit", subcategory="yogurt")]}
    )
    assert food.category is FoodCategory.PRODUCE_FRUIT
    assert food.subcategory is None


def test_confidence_is_clamped_and_bad_values_become_zero():
    (food,) = parse_extraction(
        {"products": [_product(confidence={"name": 3.7, "category": "cok eminim"})]}
    )
    assert food.confidence.name == 1.0
    assert food.confidence.category == 0.0


def test_low_confidence_flags_needs_review():
    (low,) = parse_extraction({"products": [_product(confidence={"name": 0.4, "category": 0.99})]})
    (high,) = parse_extraction({"products": [_product()]})
    assert low.confidence.needs_review is True
    assert high.confidence.needs_review is False


def test_bad_quantity_degrades_to_one_piece():
    (food,) = parse_extraction({"products": [_product(quantity={"value": -3, "unit": "parsek"})]})
    assert food.quantity.value == 1
    assert food.quantity.unit == "piece"


def test_missing_optional_fields_are_none_not_empty_string():
    (food,) = parse_extraction({"products": [_product(brand="  ", raw_label=None)]})
    assert food.brand is None
    assert food.raw_label is None


def test_empty_and_malformed_records_are_skipped():
    payload = {"products": [_product(name="   "), "bu bir dict degil", _product()]}
    assert len(parse_extraction(payload)) == 1


def test_missing_products_key_returns_empty_list():
    assert parse_extraction({}) == []
