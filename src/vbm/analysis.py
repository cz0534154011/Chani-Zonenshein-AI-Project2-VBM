"""VBM analysis: ReportData computed in code from the current batch of simulations (spec section 7)."""

from statistics import mean
from typing import TypedDict

from vbm.config import DECISIVE_MIN_IMPROVEMENT, MAX_ROUNDS, PATIENCE_RATIO
from vbm.economics import allowed_payment_terms, max_allowed_days, round_price, with_variant
from vbm.schemas import BuyerTerms, Offer, SimResult

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
    simulations_count: int
    max_rounds: int
    price_gap: dict
    preview: str


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


# משפט הסבלנות בעברית, כולל המקרים שבהם אין נתון
def patience_text(data: dict) -> str:
    """Hebrew sentence on the tough supplier's patience, never leaving None to interpretation."""
    percent, max_rounds = data["patience_threshold_percent"], data["max_rounds"]
    if data["patience"] is not None:
        return (f"הספק הקשוח ירד לראשונה מתחת ל-{percent}% מהמחירון בסבב {data['patience']} "
                f"מתוך {max_rounds}. עד אז כדאי להחזיק בעמדה.")
    tough = [r for r in data["simulations"] if r["style"] == "tough" and r["variant"] == "base"]
    if not tough:
        return "לא נבדק ספק קשוח בסימולציות האלה, ולכן אין נתון על הסבלנות הנדרשת."
    if tough[0]["rounds"] < max_rounds:
        return (f"הסימולציה מול הספק הקשוח הסתיימה בסבב {tough[0]['rounds']}, לפני שהספק ירד מתחת ל-{percent}% "
                "מהמחירון, ולכן אין נתון על הסבלנות הנדרשת.")
    return (f"גם אחרי {max_rounds} סבבים הספק הקשוח לא ירד מתחת ל-{percent}% מהמחירון, "
            "כלומר מול ספק כזה נדרשת סבלנות רבה.")


# משפט טווח המחירים בעברית: מחיר אחד או טווח
def price_range_text(price_range: dict | None) -> str:
    """Hebrew sentence on the base-deal prices."""
    if not price_range:
        return "לא נסגרה אף עסקה בגרסת הבסיס."
    if price_range["min"] == price_range["max"]:
        return f"כל עסקאות הבסיס נסגרו ב-{price_range['min']} ליחידה."
    return f"עסקאות הבסיס נסגרו בין {price_range['min']} ל-{price_range['max']} ליחידה."


# משפט הוויתור המכריע בעברית, כולל הסיבה
def concession_text(data: dict) -> str:
    """Hebrew sentence saying which concession is decisive and why."""
    concession = data["decisive_concession"]
    if concession == "none":
        return "אף גמישות לא הפכה 'אין עסקה' לעסקה, ואף אחת לא הורידה את המחיר הממוצע ביותר מ-1%."
    deals = {v: {r["style"] for r in data["simulations"] if r["variant"] == v and r["outcome"] == "deal"}
             for v in ("base", concession)}
    converted = [s for s in ("tough", "balanced", "flexible") if s in deals[concession] - deals["base"]]
    if converted:
        count = "סימולציה אחת" if len(converted) == 1 else f"{len(converted)} סימולציות"
        names = ", ".join(STYLE_HE[s] for s in converted)
        return f"{CONCESSION_HE[concession]} הפכה {count} מ'אין עסקה' לעסקה (מול ספק {names})."
    means = data["variant_means"]
    return (f"{CONCESSION_HE[concession]} הורידה את המחיר הממוצע מ-{means['base']} "
            f"ל-{means[concession]} ליחידה.")


# שורות הפער בעברית: כמה חסר בבסיס ומה כל גמישות סוגרת; ריק אם אין פער
def gap_lines(gap: dict) -> list[str]:
    """Hebrew lines on the price gap (empty when the base variant has no gap)."""
    if not gap["base_has_gap"]:
        return []
    base = gap["variants"]["base"]
    lines = [f"בבסיס ההצעה הנמוכה שנצפתה היא {base['unit_price']} ליחידה, {base['gap_per_unit']} מעל התקציב "
             f"ליחידה ({gap['budget_per_unit']}). לסגירה בלי גמישות נדרש תקציב כולל של {base['required_total']}."]
    for variant in ("payment", "delivery"):
        item = gap["variants"][variant]
        if item is None:
            lines.append(f"{CONCESSION_HE[variant]}: לא נצפתה הצעה מתאימה.")
        elif item["closes"]:
            lines.append(f"{CONCESSION_HE[variant]}: סוגרת את הפער ({item['unit_price']} ליחידה).")
        else:
            lines.append(f"{CONCESSION_HE[variant]}: לא סוגרת את הפער (נשארים {item['gap_per_unit']} ליחידה).")
    return lines


# תקציר של 3-4 שורות לעצירה 2
def build_preview(feasibility: dict, price_range: dict | None, concession: str, dealbreakers: dict,
                  gap: dict) -> str:
    """Short Hebrew summary of the findings for the second stop."""
    deals = ", ".join(f"{STYLE_HE[s]}: {'כן' if ok else 'לא'}" for s, ok in feasibility.items())
    lines = [f"עסקה בגרסת הבסיס - {deals}."]
    lines.append(price_range_text(price_range))
    lines.append(f"הוויתור המכריע: {CONCESSION_HE[concession]}.")
    if dealbreakers:
        lines.append("מה מנע עסקה: " + "; ".join(f"{REASON_HE[k]} ({v})" for k, v in dealbreakers.items()) + ".")
    return "\n".join(lines + gap_lines(gap))


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
        "preview": build_preview(feasibility, price_range, concession, dealbreakers, gap),
    }
