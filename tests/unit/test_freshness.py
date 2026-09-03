from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from core.freshness import estimate_freshness, shelf_life_days, user_provided_freshness
from core.models import FreshnessBasis
from core.taxonomy import FoodCategory, PackageState


def test_subcategory_beats_category_default():
    days, source, _, _ = shelf_life_days(FoodCategory.DAIRY, "yogurt", PackageState.UNOPENED)
    assert (days, source) == (21, "subcategory")

    days, source, _, _ = shelf_life_days(FoodCategory.DAIRY, None, PackageState.UNOPENED)
    assert (days, source) == (5, "category")


def test_unknown_subcategory_falls_back_to_category():
    days, source, _, _ = shelf_life_days(
        FoodCategory.DAIRY, "boyle_bir_sey_yok", PackageState.UNOPENED
    )
    assert (days, source) == (5, "category")


def test_unknown_package_state_picks_the_conservative_value():
    """Yanlış tarafa yanılmanın maliyeti simetrik değil — kısa süre seçilir."""
    unknown, _, _, _ = shelf_life_days(FoodCategory.DAIRY, "milk_uht", PackageState.UNKNOWN)
    opened, _, _, _ = shelf_life_days(FoodCategory.DAIRY, "milk_uht", PackageState.OPENED)
    unopened, _, _, _ = shelf_life_days(FoodCategory.DAIRY, "milk_uht", PackageState.UNOPENED)

    assert unknown == opened == 3
    assert unopened == 90


def test_unopened_and_opened_can_carry_different_sources():
    """Kaynak tablo çoğu kalem için 'kapalıda ambalaj tarihi esastır' der —
    bu yüzden kapalı/açık durumun kaynağı farklı olabilir; tek bir `source`
    alanı bu ayrımı gizlerdi.
    """
    _, _, unopened_source, _ = shelf_life_days(FoodCategory.DAIRY, "yogurt", PackageState.UNOPENED)
    _, _, opened_source, rule_id = shelf_life_days(
        FoodCategory.DAIRY, "yogurt", PackageState.OPENED
    )

    assert unopened_source == "lit."
    assert opened_source == "USDA_FOODKEEPER_2025"
    assert rule_id == "SL-DAIRY-YOGURT"


def test_estimate_adds_shelf_life_to_capture_date():
    captured = datetime(2026, 3, 10, 14, 30, tzinfo=UTC)
    result = estimate_freshness(captured, FoodCategory.DAIRY, "yogurt", PackageState.UNOPENED)

    assert result.estimated_freshness_date == date(2026, 3, 31)
    assert result.basis is FreshnessBasis.CATEGORY_HEURISTIC
    assert result.resolved_from == "subcategory"
    assert result.warning is None


def test_estimate_accepts_plain_date():
    result = estimate_freshness(date(2026, 3, 10), FoodCategory.FISH_SEAFOOD, "mussel")
    assert result.estimated_freshness_date == date(2026, 3, 11)


def test_deli_prevents_sucuk_from_getting_the_other_default():
    """`deli` kategorisinin varlık sebebi bu testtir."""
    sucuk, _, _, _ = shelf_life_days(FoodCategory.DELI, "sucuk", PackageState.UNOPENED)
    fallback, _, _, _ = shelf_life_days(FoodCategory.OTHER, None, PackageState.UNOPENED)
    assert sucuk == 30
    assert fallback == 5


def test_cut_based_meat_split_gives_ground_meat_a_shorter_life_than_steak():
    """Kesim tazeliği belirler, cins değil — kıyma biftekten çok daha çabuk bozulur."""
    ground, _, _, _ = shelf_life_days(FoodCategory.MEAT_POULTRY, "ground_meat")
    steak, _, _, _ = shelf_life_days(FoodCategory.MEAT_POULTRY, "steak_chop")
    assert ground < steak


def test_apple_and_pear_no_longer_share_a_value():
    """Eski birleşik apple_pear armut için ~35 gün gibi yanlış bir tahmin veriyordu."""
    apple, _, _, _ = shelf_life_days(FoodCategory.PRODUCE_FRUIT, "apple")
    pear, _, _, _ = shelf_life_days(FoodCategory.PRODUCE_FRUIT, "pear")
    assert apple == 35
    assert pear == 5


def test_preserves_pickles_is_its_own_category():
    days, _, source, rule_id = shelf_life_days(
        FoodCategory.PRESERVES_PICKLES, "pickle", PackageState.OPENED
    )
    assert days == 60
    assert source == "USDA_FOODKEEPER_2025"
    assert rule_id == "SL-PRESERVE-PICKLE"


def test_user_provided_overrides_heuristic():
    result = user_provided_freshness(date(2026, 12, 31))
    assert result.basis is FreshnessBasis.USER_PROVIDED
    assert result.shelf_life_days == -1


@pytest.mark.parametrize("category", list(FoodCategory))
def test_every_category_produces_a_future_date(category):
    result = estimate_freshness(date(2026, 1, 1), category)
    assert result.estimated_freshness_date > date(2026, 1, 1)
    assert result.warning is None, "her kategori tabloda olmalı, global_default'a düşmemeli"
