"""VBM analysis: ReportData computed in code from the current batch of simulations (spec section 7)."""

from statistics import mean
from typing import TypedDict

from vbm.config import DECISIVE_MIN_IMPROVEMENT, PATIENCE_RATIO
from vbm.economics import round_price
from vbm.schemas import BuyerTerms, SimResult

STYLE_HE = {"tough": "קשוח", "balanced": "מאוזן", "flexible": "גמיש"}
VARIANT_HE = {"base": "בסיס", "payment": "גמישות בתשלום", "delivery": "גמישות במועד"}
REASON_HE = {
    "delivery_impossible": "המועד שנדרש מהיר מהמועד המינימלי של הספק",
    "seller_quit": "הספק פרש בגלל הצעות נמוכות מדי",
    "buyer_walk_away": "הקונה פרש",
    "max_rounds": "נגמרו הסבבים בלי הסכמה",
}
CONCESSION_HE = {"payment": "גמישות בתנאי התשלום", "delivery": "גמישות במועד האספקה", "none": "אין ויתור מכריע"}


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
    preview: str


# רק התוצאות של ה-batch הנוכחי (אחרי לולאת "מה אם" נשארות גם הישנות)
def current_batch(results: list[SimResult], batch_id: int) -> list[SimResult]:
    """Results that belong to the given batch."""
    return [r for r in results if r["batch_id"] == batch_id]


# שורת סיכום קצרה לכל סימולציה, בלי התמליל
def simulation_rows(results: list[SimResult]) -> list[dict]:
    """One summary row per simulation: style, variant, outcome, final offer, rounds, reason."""
    rows = []
    for r in results:
        final = r["final"]
        rows.append({
            "style": r["style"], "variant": r["variant"], "outcome": r["outcome"],
            "unit_price": final.unit_price if final else None,
            "delivery_days": final.delivery_days if final else None,
            "payment_terms": final.payment_terms if final else None,
            "rounds": r["rounds"], "no_deal_reason": r["no_deal_reason"],
        })
    return rows


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


# תקציר של 3-4 שורות לעצירה 2
def build_preview(feasibility: dict, price_range: dict | None, concession: str, dealbreakers: dict) -> str:
    """Short Hebrew summary of the findings for the second stop."""
    deals = ", ".join(f"{STYLE_HE[s]}: {'כן' if ok else 'לא'}" for s, ok in feasibility.items())
    lines = [f"עסקה בגרסת הבסיס - {deals}."]
    if price_range:
        lines.append(f"טווח המחירים בעסקאות הבסיס: {price_range['min']} עד {price_range['max']} ליחידה.")
    else:
        lines.append("לא נסגרה אף עסקה בגרסת הבסיס.")
    lines.append(f"הוויתור המכריע: {CONCESSION_HE[concession]}.")
    if dealbreakers:
        lines.append("מה מנע עסקה: " + "; ".join(f"{REASON_HE[k]} ({v})" for k, v in dealbreakers.items()) + ".")
    return "\n".join(lines)


# חישוב ReportData מתוצאות ה-batch הנוכחי
def analyze_results(results: list[SimResult], buyer: BuyerTerms) -> ReportData:
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
    return {
        "buyer": {
            "product": buyer["product"], "quantity": buyer["quantity"],
            "max_budget_total": buyer["max_budget_total"], "target_total": buyer["target_total"],
            "budget_per_unit": round_price(buyer["max_budget_total"] / buyer["quantity"]),
            "target_per_unit": round_price(buyer["target_total"] / buyer["quantity"]),
            "deadline_days": buyer["deadline_days"], "preferred_days": buyer.get("preferred_days"),
            "preferred_terms": buyer["preferred_terms"],
        },
        "simulations": simulation_rows(results),
        "feasibility": feasibility,
        "price_range": price_range,
        "variant_means": {v: variant_mean(results, v) for v in ("base", "payment", "delivery")},
        "decisive_concession": concession,
        "dealbreakers": dealbreakers,
        "patience": patience_round(results),
        "patience_threshold_percent": round(PATIENCE_RATIO * 100),
        "preview": build_preview(feasibility, price_range, concession, dealbreakers),
    }
