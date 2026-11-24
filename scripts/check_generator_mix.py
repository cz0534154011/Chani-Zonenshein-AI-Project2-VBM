"""Check the mix of ZOPA categories the supplier generator produces (no LLM)."""

from collections import Counter

from vbm.economics import classify_zopa, compute_zopa
from vbm.scenario_generator import generate_limits, profile_for_style
from vbm.schemas import validate_buyer_terms

SEEDS = 1000

# הקונה מהבדיקה שבאפיון: יעד 320 ותקרה 420 ליחידה
BUYER = validate_buyer_terms({
    "product": "office chair", "quantity": 500,
    "max_budget_total": 210000, "target_total": 160000,
    "deadline_days": 30, "preferred_terms": "advance",
})


# הרצת המחולל על 1,000 seeds והדפסת אחוז כל קטגוריה
def main() -> None:
    counts: Counter[str] = Counter()
    for seed in range(SEEDS):
        seller = profile_for_style(generate_limits(BUYER, seed), "balanced")
        counts[classify_zopa(compute_zopa(BUYER, seller))] += 1
    print(f"seeds: {SEEDS}  (target: about 45% wide, 21% narrow, 34% no ZOPA)")
    for category in ("wide", "narrow", "no_zopa_price", "no_zopa_delivery"):
        print(f"  {category:<17} {counts[category]:>4}  {100 * counts[category] / SEEDS:5.1f}%")


if __name__ == "__main__":
    main()
