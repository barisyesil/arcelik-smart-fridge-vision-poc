from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.models import FieldConfidence, FoodCategory, FreshnessBasis, InventoryItem, Quantity
from core.recipes import dataset_version, recommend

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def _item(name, category, subcategory, days=10):
    return InventoryItem(
        item_id="itm_" + name,
        fridge_id="F1",
        user_id="u1",
        name=name,
        category=category,
        subcategory=subcategory,
        quantity=Quantity(value=1),
        estimated_freshness_date=TODAY + timedelta(days=days),
        freshness_basis=FreshnessBasis.CATEGORY_HEURISTIC,
        created_at=NOW,
        updated_at=NOW,
        observation_id="o1",
        confidence=FieldConfidence(name=0.9, category=0.9),
    )


def test_dataset_version_is_stable():
    assert dataset_version() == "recipes-2026-09-v1"


def test_scoring_is_deterministic():
    items = [_item("yumurta", FoodCategory.EGG, "shell_egg")]
    first = recommend(items, NOW)
    second = recommend(items, NOW)
    assert [(m.recipe_id, m.match_score) for m in first] == [
        (m.recipe_id, m.match_score) for m in second
    ]


def test_full_required_coverage_scores_higher_than_missing():
    have_all = [
        _item("yumurta", FoodCategory.EGG, "shell_egg"),
        _item("kaşar", FoodCategory.DAIRY, "cheese_hard"),
    ]
    omelet_full = next(m for m in recommend(have_all, NOW) if m.recipe_id == "rcp_peynirli_omlet")
    omelet_empty = next(m for m in recommend([], NOW) if m.recipe_id == "rcp_peynirli_omlet")
    assert omelet_full.match_score > omelet_empty.match_score
    assert omelet_full.missing_required == []


def test_missing_required_is_reported():
    only_egg = [_item("yumurta", FoodCategory.EGG, "shell_egg")]
    omelet = next(m for m in recommend(only_egg, NOW) if m.recipe_id == "rcp_peynirli_omlet")
    assert "kaşar peyniri" in omelet.missing_required


def test_allergen_filter_excludes_recipe():
    items = [_item("yumurta", FoodCategory.EGG, "shell_egg")]
    ids = {m.recipe_id for m in recommend(items, NOW, avoid_allergens={"yumurta"})}
    assert "rcp_peynirli_omlet" not in ids
    assert "rcp_menemen" not in ids


def test_expiring_ingredient_boosts_score():
    fresh = [_item("domates", FoodCategory.PRODUCE_VEGETABLE, "tomato", days=20)]
    expiring = [_item("domates", FoodCategory.PRODUCE_VEGETABLE, "tomato", days=1)]
    soup_fresh = next(m for m in recommend(fresh, NOW) if m.recipe_id == "rcp_domates_corbasi")
    soup_expiring = next(
        m for m in recommend(expiring, NOW) if m.recipe_id == "rcp_domates_corbasi"
    )
    assert soup_expiring.match_score > soup_fresh.match_score
    assert soup_expiring.expiring_used_count >= 1


def test_diet_filter_requires_tag():
    items = [_item("domates", FoodCategory.PRODUCE_VEGETABLE, "tomato")]
    vegan = {m.recipe_id for m in recommend(items, NOW, require_diets={"vegan"})}
    # Sebze sote vegan; menemen değil (yumurta/süt).
    assert "rcp_sebze_sote" in vegan
    assert "rcp_menemen" not in vegan
