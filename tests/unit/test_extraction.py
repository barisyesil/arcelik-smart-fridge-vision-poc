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
        "box_2d": [100, 200, 400, 500],
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


def test_bounding_box_is_parsed_from_box_2d():
    (food,) = parse_extraction({"products": [_product()]})
    assert food.bounding_box is not None
    assert (
        food.bounding_box.ymin,
        food.bounding_box.xmin,
        food.bounding_box.ymax,
        food.bounding_box.xmax,
    ) == (100, 200, 400, 500)


def test_missing_box_leaves_bounding_box_none_but_keeps_product():
    payload = {"products": [_product()]}
    del payload["products"][0]["box_2d"]
    (food,) = parse_extraction(payload)
    assert food.bounding_box is None
    assert food.name == "süzme yoğurt"


def test_schema_declares_box_2d_but_does_not_require_it():
    """Kutu ayrı bir sinyal: model üretemezse ürünün tamamı düşmesin diye
    `box_2d` şemada var ama `required` değil."""
    items = build_response_schema()["properties"]["products"]["items"]
    assert "box_2d" in items["properties"]
    assert items["properties"]["box_2d"]["maxItems"] == 4
    assert "box_2d" not in items["required"]


def test_out_of_range_box_is_dropped_not_product():
    (food,) = parse_extraction({"products": [_product(box_2d=[0, 0, 400, 1200])]})
    assert food.bounding_box is None
    assert food.name == "süzme yoğurt"


def test_wrong_length_box_is_dropped():
    (food,) = parse_extraction({"products": [_product(box_2d=[100, 200, 400])]})
    assert food.bounding_box is None


def test_zero_area_box_is_dropped():
    """Kırpılamayan (ymin>=ymax veya xmin>=xmax) kutu atılır."""
    (food,) = parse_extraction({"products": [_product(box_2d=[400, 200, 400, 500])]})
    assert food.bounding_box is None
