"""Tarif eşleştirme. Saf Python; sabit ve sürümlü veri seti (BR-012).

Generative AI KULLANILMAZ. Skor deterministiktir: aynı envanter ve aynı veri
seti her zaman aynı sonucu verir. Alerjen filtresi skorlamadan ÖNCE güvenli
biçimde uygulanır (FR-REC-005).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from core.models import InventoryItem, ItemState
from core.review import REVIEW_WINDOW_DAYS

_DATA_PATH = Path(__file__).with_name("recipes.json")

# Skor ağırlıkları (SRS 8.11).
_W_REQUIRED = 0.60
_W_EXPIRING = 0.25
_W_OPTIONAL = 0.15
_W_MISSING_PENALTY = 0.15


class RecipeDataError(RuntimeError):
    """recipes.json bozuk veya eksik."""


@dataclass(frozen=True)
class RecipeMatch:
    recipe_id: str
    title: str
    match_score: int  # 0..100
    expiring_used_count: int
    missing_required: list[str] = field(default_factory=list)
    recipe: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _load_data() -> dict:
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecipeDataError(f"recipes.json okunamadı: {exc}") from exc
    if "recipes" not in data or "dataset_version" not in data:
        raise RecipeDataError("recipes.json beklenen anahtarları taşımıyor")
    return data


def dataset_version() -> str:
    return _load_data()["dataset_version"]


def _item_matches(item: InventoryItem, ingredient: dict) -> bool:
    """Envanter kalemi bir malzemeyi karşılıyor mu?

    Kategori eşleşmesi zorunlu. Malzemede alt kategori belirtilmişse ve kalemde
    de varsa eşit olmalı; kalemde alt kategori yoksa kategori eşleşmesi yeter.
    """
    if item.category.value != ingredient.get("category"):
        return False
    ing_sub = ingredient.get("subcategory")
    return not (ing_sub and item.subcategory and item.subcategory != ing_sub)


def _score_recipe(recipe: dict, active_items: list[InventoryItem], now: datetime) -> RecipeMatch:
    required = [ing for ing in recipe["ingredients"] if ing.get("required")]
    optional = [ing for ing in recipe["ingredients"] if not ing.get("required")]

    expiring_ids: set[str] = set()
    matched_ingredient_count = 0
    present_required = 0
    missing_required: list[str] = []

    for ing in recipe["ingredients"]:
        matches = [it for it in active_items if _item_matches(it, ing)]
        if matches:
            matched_ingredient_count += 1
            for it in matches:
                if (it.effective_freshness_date - now.date()).days <= REVIEW_WINDOW_DAYS:
                    expiring_ids.add(it.item_id)
        if ing.get("required"):
            if matches:
                present_required += 1
            else:
                missing_required.append(ing.get("name", "?"))

    total_ingredients = len(recipe["ingredients"]) or 1
    required_coverage = present_required / len(required) if required else 1.0
    optional_present = sum(
        1 for ing in optional if any(_item_matches(it, ing) for it in active_items)
    )
    optional_coverage = optional_present / len(optional) if optional else 1.0
    expiring_utilization = len(expiring_ids) / total_ingredients
    missing_fraction = (len(required) - present_required) / len(required) if required else 0.0

    raw = (
        _W_REQUIRED * required_coverage
        + _W_EXPIRING * expiring_utilization
        + _W_OPTIONAL * optional_coverage
        - _W_MISSING_PENALTY * missing_fraction
    )
    score = max(0, min(100, round(raw * 100)))
    return RecipeMatch(
        recipe_id=recipe["recipe_id"],
        title=recipe["title"],
        match_score=score,
        expiring_used_count=len(expiring_ids),
        missing_required=missing_required,
        recipe=recipe,
    )


def _passes_filters(
    recipe: dict,
    *,
    avoid_allergens: set[str],
    require_diets: set[str],
    meal_type: str | None,
    max_prep_minutes: int | None,
) -> bool:
    # Alerjen: güvenlik filtresi — kaçınılan bir alerjen varsa tarif elenir.
    if avoid_allergens & set(recipe.get("allergen_tags", [])):
        return False
    # Diyet: istenen tüm diyet etiketleri tarifte bulunmalı.
    if require_diets and not require_diets.issubset(set(recipe.get("diet_tags", []))):
        return False
    if meal_type and meal_type not in recipe.get("meal_types", []):
        return False
    return not (max_prep_minutes is not None and recipe.get("prep_minutes", 0) > max_prep_minutes)


def recommend(
    active_items: list[InventoryItem],
    now: datetime,
    *,
    avoid_allergens: set[str] | None = None,
    require_diets: set[str] | None = None,
    meal_type: str | None = None,
    max_prep_minutes: int | None = None,
    limit: int = 10,
) -> list[RecipeMatch]:
    """Envantere uyan tarifleri deterministik skorla, yüksekten düşüğe döndür.

    Eşit skor bozucu: `recipe_id` alfabetik (kararlılık için).
    """
    avoid_allergens = avoid_allergens or set()
    require_diets = require_diets or set()
    items = [it for it in active_items if it.state is ItemState.ACTIVE]

    matches = [
        _score_recipe(recipe, items, now)
        for recipe in _load_data()["recipes"]
        if _passes_filters(
            recipe,
            avoid_allergens=avoid_allergens,
            require_diets=require_diets,
            meal_type=meal_type,
            max_prep_minutes=max_prep_minutes,
        )
    ]
    matches.sort(key=lambda m: (-m.match_score, m.recipe_id))
    return matches[:limit]
