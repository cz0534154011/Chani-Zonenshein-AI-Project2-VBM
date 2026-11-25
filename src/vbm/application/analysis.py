"""VBM analysis: ReportData computed in code from the current batch of simulations (spec section 7); numbers only, no text."""

from statistics import mean
from typing import NotRequired, TypedDict

from vbm.domain.economics import allowed_payment_terms, max_allowed_days, round_price, with_variant
from vbm.domain.rules import DECISIVE_MIN_IMPROVEMENT, MAX_ROUNDS, PATIENCE_RATIO
from vbm.domain.schemas import BuyerTerms, Offer, SimResult


class ReportData(TypedDict):
    buyer: dict
    simulations: list[dict]
    feasibility: dict[str, bool]
    price_range: dict | None
    variant_means: dict[str, float | None]
    decisive_concession: str
    dealbreakers: dict[str, int]
    patience: int | None
    patience_threshold_percent: int
    simulations_count: int
    max_rounds: int
    price_gap: dict
    preview: NotRequired[str]  # Hebrew summary, added by the workflow from adapters.texts


# רק התוצאות של ה-batch הנוכחי (אחרי לולאת "מה אם" נשארות גם הישנות)
def current_batch(results: list[SimResult], batch_id: int) -> list[SimResult]:
    """Results that belong to the given batch."""
    return [r for r in results if r["batch_id"] == batch_id]


# ההצעה הזולה ביותר של הספק שהקונה היה רשאי לקבל בגרסה של הסימולציה (מנתוני הקונה בלבד)
def lowest_allowed_offer(result: SimResult, buyer: BuyerTerms) -> Offer | None:
    """Cheapest supplier offer in the transcript whose terms and delivery the buyer's variant allows."""
    variant_buyer = with_variant(buyer, result["variant"])
    terms, days = allowed_payment_terms(variant_buyer), max_allowed_days(variant_buyer)
    offers = [o for e in result["transcript"] if e["speaker"] == "seller" for o in e["offers"]
              if o.payment_terms in terms and o.delivery_days <= days]
    return min(offers, key=lambda o: o.unit_price) if offers else None


# שורת סיכום קצרה לכל סימולציה, בלי התמליל
def simulation_rows(results: list[SimResult], buyer: BuyerTerms) -> list[dict]:
    """One summary row per simulation: style, variant, outcome, final offer, rounds, reason, lowest offer seen."""
    rows = []
    for r in results:
        final = r["final"]
        lowest = lowest_allowed_offer(r, buyer)
        rows.append({
            "style": r["style"], "variant": r["variant"], "outcome": r["outcome"],
            "unit_price": final.unit_price if final else None,
            "delivery_days": final.delivery_days if final else None,
            "payment_terms": final.payment_terms if final else None,
            "rounds": r["rounds"], "no_deal_reason": r["no_deal_reason"],
            "lowest_offer": lowest.unit_price if lowest else None,
        })
    return rows


# הפער בין ההצעה הנמוכה שנצפתה לתקציב, לכל גרסה של הקונה
def price_gap(results: list[SimResult], buyer: BuyerTerms) -> dict:
    """Per variant: lowest allowed offer seen, gap per unit vs the budget, required total; base_has_gap."""
    budget = round_price(buyer["max_budget_total"] / buyer["quantity"])
    gaps = {}
    for variant in ("base", "payment", "delivery"):
        offers = [lowest_allowed_offer(r, buyer) for r in results if r["variant"] == variant]
        offers = [o for o in offers if o is not None]
        if not offers:
            gaps[variant] = None
            continue
        best = min(offers, key=lambda o: o.unit_price)
        gap = round_price(best.unit_price - budget)
        gaps[variant] = {"unit_price": best.unit_price, "delivery_days": best.delivery_days,
                         "payment_terms": best.payment_terms, "gap_per_unit": gap,
                         "required_total": round_price(best.unit_price * buyer["quantity"]), "closes": gap <= 0}
    base = gaps.get("base")
    return {"budget_per_unit": budget, "base_has_gap": bool(base) and base["gap_per_unit"] > 0, "variants": gaps}


# מחיר ממוצע של העסקאות בגרסה מסוימת; None אם לא נסגרה אף עסקה
def variant_mean(results: list[SimResult], variant: str) -> float | None:
    """Mean final unit price over the deals of one buyer variant."""
    prices = [r["final"].unit_price for r in results if r["variant"] == variant and r["outcome"] == "deal"]
    return round_price(mean(prices)) if prices else None


# הוויתור המכריע: הגרסה שהפכה אין עסקה לעסקה, או שהורידה את המחיר הממוצע הכי הרבה
def decisive_concession(results: list[SimResult]) -> str:
    """'payment', 'delivery' or 'none' (spec section 7, 1% threshold)."""
    base_deals = {r["style"] for r in results if r["variant"] == "base" and r["outcome"] == "deal"}
    converted = {}
    for variant in ("payment", "delivery"):
        deals = {r["style"] for r in results if r["variant"] == variant and r["outcome"] == "deal"}
        converted[variant] = len(deals - base_deals)
    if max(converted.values()) > 0:
        best = max(converted.values())
        tied = [v for v in ("payment", "delivery") if converted[v] == best]
        if len(tied) == 1:
            return tied[0]
        return min(tied, key=lambda v: variant_mean(results, v))
    base_mean = variant_mean(results, "base")
    if base_mean is None:
        return "none"
    gains = {}
    for variant in ("payment", "delivery"):
        m = variant_mean(results, variant)
        gains[variant] = (base_mean - m) / base_mean if m is not None else 0.0
    best = max(gains, key=gains.get)
    return best if gains[best] > DECISIVE_MIN_IMPROVEMENT else "none"


# הסבב הראשון שבו הספק הקשוח (גרסת בסיס) ירד מתחת ל-90% מהמחירון
def patience_round(results: list[SimResult]) -> int | None:
    """First round where the tough supplier's own-terms ask fell below PATIENCE_RATIO of its opening."""
    for r in results:
        if r["style"] != "tough" or r["variant"] != "base":
            continue
        seller_entries = [e for e in r["transcript"] if e["speaker"] == "seller" and e["offers"]]
        if not seller_entries:
            return None
        opening = seller_entries[0]["offers"][0].unit_price
        for entry in seller_entries[1:]:
            if entry["offers"][0].unit_price < PATIENCE_RATIO * opening:
                return entry["round"]
        return None
    return None


# חישוב ReportData מתוצאות ה-batch הנוכחי
def analyze_results(results: list[SimResult], buyer: BuyerTerms, max_rounds: int = MAX_ROUNDS) -> ReportData:
    """Compute every number the report may use; the report model only phrases them."""
    base = [r for r in results if r["variant"] == "base"]
    feasibility = {r["style"]: r["outcome"] == "deal" for r in base}
    base_prices = [r["final"].unit_price for r in base if r["outcome"] == "deal"]
    price_range = {"min": min(base_prices), "max": max(base_prices)} if base_prices else None
    dealbreakers: dict[str, int] = {}
    for r in results:
        if r["no_deal_reason"]:
            dealbreakers[r["no_deal_reason"]] = dealbreakers.get(r["no_deal_reason"], 0) + 1
    concession = decisive_concession(results)
    gap = price_gap(results, buyer)
    return {
        "buyer": {
            "product": buyer["product"], "quantity": buyer["quantity"],
            "max_budget_total": buyer["max_budget_total"], "target_total": buyer["target_total"],
            "budget_per_unit": round_price(buyer["max_budget_total"] / buyer["quantity"]),
            "target_per_unit": round_price(buyer["target_total"] / buyer["quantity"]),
            "deadline_days": buyer["deadline_days"], "preferred_days": buyer.get("preferred_days"),
            "preferred_terms": buyer["preferred_terms"],
        },
        "simulations": simulation_rows(results, buyer),
        "feasibility": feasibility,
        "price_range": price_range,
        "variant_means": {v: variant_mean(results, v) for v in ("base", "payment", "delivery")},
        "decisive_concession": concession,
        "dealbreakers": dealbreakers,
        "patience": patience_round(results),
        "patience_threshold_percent": round(PATIENCE_RATIO * 100),
        "simulations_count": len(results),
        "max_rounds": max_rounds,
        "price_gap": gap,
    }
