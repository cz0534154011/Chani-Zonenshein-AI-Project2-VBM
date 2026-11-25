"""VBM dataset: 18 frozen scenarios with answers computed in code only (spec section 8)."""

import random

from vbm.config import (
    DATASET_BUDGET_FACTOR_RANGE,
    DATASET_DEADLINE_RANGE,
    DATASET_PREFERRED_GAP_RANGE,
    DATASET_PRODUCTS,
    DATASET_QUOTAS,
    DECISIVE_MIN_IMPROVEMENT,
    MAX_ROUNDS,
    MIN_DAYS_FLOOR,
)
from vbm.economics import classify_zopa, compute_zopa, with_variant
from vbm.scenario_generator import generate_limits, profile_for_style
from vbm.schemas import BuyerTerms, validate_buyer_terms


# הגרלת קונה מטבלת המוצרים, לפי seed
def draw_buyer(seed: int) -> BuyerTerms:
    """Buyer terms for one scenario: product, budget, deadline, preferred delivery and terms."""
    rng = random.Random(seed)
    product, quantity, unit_target = DATASET_PRODUCTS[rng.randrange(len(DATASET_PRODUCTS))]
    target_total = round(unit_target * quantity)
    deadline = rng.randint(*DATASET_DEADLINE_RANGE)
    return validate_buyer_terms({
        "product": product, "quantity": quantity, "target_total": target_total,
        "max_budget_total": round(target_total * rng.uniform(*DATASET_BUDGET_FACTOR_RANGE)),
        "deadline_days": deadline,
        "preferred_days": max(MIN_DAYS_FLOOR, deadline - rng.randint(*DATASET_PREFERRED_GAP_RANGE)),
        "preferred_terms": rng.choice(["advance", "net30", "net60"]),
    })


# הוויתור המכריע האנליטי: איזו גמישות פותחת טווח, או מורידה את zopa_low ביותר מ-1%
def analytic_concession(buyer: BuyerTerms, limits: dict) -> str:
    """'payment', 'delivery' or 'none', from the ZOPA of each buyer variant (same rule as the analysis)."""
    seller = profile_for_style(limits, "balanced")
    zopas = {v: compute_zopa(with_variant(buyer, v), seller) for v in ("base", "payment", "delivery")}
    if not zopas["base"]["zopa_exists"]:
        opened = [v for v in ("payment", "delivery") if zopas[v]["zopa_exists"]]
        return min(opened, key=lambda v: zopas[v]["zopa_low"]) if opened else "none"
    base_low = zopas["base"]["zopa_low"]
    gains = {v: (base_low - zopas[v]["zopa_low"]) / base_low for v in ("payment", "delivery")}
    best = max(gains, key=gains.get)
    return best if gains[best] > DECISIVE_MIN_IMPROVEMENT else "none"


# תרחיש אחד: inputs לגרף ו-outputs מחושבים בקוד
def build_example(seed: int) -> dict:
    """One dataset example for the given seed."""
    buyer = with_variant(draw_buyer(seed), "base")
    limits = generate_limits(buyer, seed)
    zopa = compute_zopa(buyer, profile_for_style(limits, "balanced"))
    return {
        "inputs": {"buyer": buyer, "seller_profiles": limits, "max_rounds": MAX_ROUNDS, "seed": seed},
        "outputs": {**zopa, "decisive_concession": analytic_concession(buyer, limits),
                    "category": classify_zopa(zopa)},
    }


# 18 תרחישים: עוברים על seeds לפי הסדר עד שכל קטגוריה מתמלאת
def build_dataset(quotas: dict[str, int] = DATASET_QUOTAS) -> list[dict]:
    """Deterministic list of examples that fills every category quota."""
    left, examples, seed = dict(quotas), [], 0
    while any(left.values()):
        seed += 1
        example = build_example(seed)
        category = example["outputs"]["category"]
        if left.get(category, 0) > 0:
            left[category] -= 1
            examples.append(example)
    return examples
