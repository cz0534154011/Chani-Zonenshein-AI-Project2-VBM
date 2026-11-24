"""VBM supplier generator: a random supplier profile from a printed seed (spec 6.2)."""

import random

from vbm.config import (
    LIST_PRICE_FACTOR_RANGE,
    MIN_DAYS_FLOOR,
    MIN_DAYS_GAP_RANGE,
    MIN_PRICE_FACTOR_RANGE,
    STANDARD_DAYS_RANGE,
)
from vbm.economics import round_price
from vbm.schemas import BuyerTerms, SellerProfile, SellerStyle, validate_seller_profile

STYLES: tuple[SellerStyle, ...] = ("tough", "balanced", "flexible")


# הגרלת הגבולות הסודיים של ספק, ביחס ליעד הקונה; מה שהמשתמש יודע גובר על ההגרלה
def generate_limits(buyer: BuyerTerms, seed: int, known: dict | None = None) -> dict:
    """Draw list/min price and standard/min days; values in `known` override the draw."""
    known = known or {}
    rng = random.Random(seed)
    # all draws happen in a fixed order, so the same seed always gives the same numbers
    list_factor = rng.uniform(*LIST_PRICE_FACTOR_RANGE)
    min_factor = rng.uniform(*MIN_PRICE_FACTOR_RANGE)
    standard_draw = rng.randint(*STANDARD_DAYS_RANGE)
    gap_draw = rng.randint(*MIN_DAYS_GAP_RANGE)

    target_unit = buyer["target_total"] / buyer["quantity"]
    list_price = known.get("list_price", round_price(target_unit * list_factor))
    min_price = known.get("min_price", round_price(list_price * min_factor))
    standard_days = known.get("standard_days", standard_draw)
    min_days = known.get("min_days", max(MIN_DAYS_FLOOR, standard_days - gap_draw))
    return {"list_price": list_price, "min_price": min_price,
            "standard_days": standard_days, "min_days": min_days}


# אותם גבולות לספק בסגנון נתון - כך ההבדל בין הסגנונות נובע רק מקצב הוויתורים
def profile_for_style(limits: dict, style: SellerStyle) -> SellerProfile:
    """Return a checked SellerProfile with the given limits and style."""
    profile: SellerProfile = {**limits, "style": style}  # type: ignore[typeddict-item]
    return validate_seller_profile(profile)


# שלושה ספקים, אחד לכל סגנון, עם אותם גבולות בדיוק
def profiles_for_all_styles(limits: dict) -> dict[str, SellerProfile]:
    """One SellerProfile per style, all sharing the same limits."""
    return {style: profile_for_style(limits, style) for style in STYLES}
