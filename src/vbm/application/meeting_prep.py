"""VBM meeting-prep use cases: reading the request, planning the batch, the what-if answer, report check, debrief."""

from typing import Literal, TypedDict

from vbm.application.dto import ParsedRequest
from vbm.application.numbers import unverified_numbers
from vbm.application.policy import MAX_REPORT_ATTEMPTS
from vbm.domain.economics import compute_zopa, round_price, with_variant
from vbm.domain.rules import MAX_ROUNDS
from vbm.domain.scenario_generator import STYLES, generate_limits, profiles_for_all_styles
from vbm.domain.schemas import BuyerTerms, SellerProfile, validate_buyer_terms

VARIANTS = ("base", "payment", "delivery")
LIMIT_KEYS = ("list_price", "min_price", "standard_days", "min_days")


class RequestReading(TypedDict):
    buyer: BuyerTerms | dict  # empty dict when the parsed terms are invalid
    seller_known: dict
    notes: list[str]
    error: str | None  # validation error of the parsed terms


# הגבולות של הספק: מהדאטהסט (בהערכה) או מהגרלה, ומה שהמשתמש יודע גובר
def seller_limits(state: dict, known: dict) -> dict:
    """Supplier limits for the next batch: dataset limits or a seeded draw, overridden by `known`."""
    if state.get("seller_profiles"):
        return {**state["seller_profiles"], **known}
    return generate_limits(state.get("draw_buyer") or state["buyer"], state.get("seed", 0), known)


# מהפענוח לנתוני הקונה, למה שידוע על הספק ולהערות; בדיקת תקינות בלי לזרוק שגיאה
def read_parsed_request(parsed: ParsedRequest, seller_known: dict | None) -> RequestReading:
    """Buyer terms (checked, or {} if invalid), known supplier facts, the parser's notes and the validation error."""
    buyer = {"product": parsed.product, "quantity": parsed.quantity,
             "max_budget_total": parsed.max_budget_total, "target_total": parsed.target_total,
             "deadline_days": parsed.deadline_days, "preferred_terms": parsed.preferred_terms}
    if parsed.preferred_days is not None:
        buyer["preferred_days"] = parsed.preferred_days
    known = dict(seller_known or {})
    if parsed.known_list_price is not None:
        known["list_price"] = parsed.known_list_price
    if parsed.known_standard_days is not None:
        known["standard_days"] = parsed.known_standard_days
    try:
        return {"buyer": validate_buyer_terms(buyer), "seller_known": known, "notes": list(parsed.notes), "error": None}
    except ValueError as error:
        return {"buyer": {}, "seller_known": known, "notes": list(parsed.notes), "error": str(error)}


# עצירה 1: האם המשתמש אישר, ומה התיקון שלו
def is_confirmed(answer: dict, buyer: dict) -> bool:
    """True if the user confirmed and the parsed buyer terms are valid."""
    return answer.get("action") == "confirm" and bool(buyer)


def correction_of(answer: dict) -> str:
    """The user's correction text, trimmed."""
    return answer.get("text", "").strip()


# תכנון הסימולציות: ספק לכל סגנון x שלוש גרסאות קונה, עם batch חדש
def plan_batch(state: dict) -> dict:
    """Build the simulation specs (3 styles x 3 variants by default) and start a new batch."""
    buyer = validate_buyer_terms(state["buyer"])
    draw_buyer = state.get("draw_buyer") or buyer
    profiles = profiles_for_all_styles(seller_limits({**state, "draw_buyer": draw_buyer}, state.get("seller_known") or {}))
    styles = state.get("seller_styles") or STYLES
    batch_id = state.get("batch_id", 0) + 1
    max_rounds = state.get("max_rounds", MAX_ROUNDS)
    specs = [{"buyer": with_variant(buyer, variant), "seller": profiles[style], "variant": variant,
              "batch_id": batch_id, "max_rounds": max_rounds}
             for style in styles for variant in VARIANTS]
    return {"buyer": buyer, "draw_buyer": draw_buyer, "batch_id": batch_id, "sim_specs": specs,
            "max_rounds": max_rounds}


# החלת הבחירה של המשתמש בעצירה 2, עם בדיקת תקינות
def apply_changes(state: dict, answer: dict) -> dict:
    """Apply change_terms / change_seller, or mark the answer invalid with an error message."""
    action = answer.get("action")
    if action == "report":
        return {"user_choice": answer}
    try:
        if action == "change_terms":
            changes = dict(answer.get("changes") or {})
            old = state["buyer"]
            if "deadline_days" in changes and "preferred_days" not in changes \
                    and old.get("preferred_days") == old["deadline_days"]:
                changes["preferred_days"] = changes["deadline_days"]
            return {"user_choice": answer, "buyer": validate_buyer_terms({**old, **changes})}
        if action == "change_seller":
            known = {**(state.get("seller_known") or {}), **(answer.get("known") or {})}
            unknown = set(known) - set(LIMIT_KEYS)
            if unknown:
                raise ValueError(f"unknown supplier fields: {', '.join(sorted(unknown))}")
            profiles_for_all_styles(seller_limits(state, known))
            return {"user_choice": answer, "seller_known": known}
    except (ValueError, TypeError, KeyError) as error:
        return {"user_choice": {"action": "invalid", "error": str(error)}}
    return {"user_choice": {"action": "invalid", "error": f"unknown action: {action}"}}


# אימות הדוח: כל מספר בטקסט חייב להופיע ב-ReportData; אחרי 3 כישלונות - דוח חלופי
def report_status(report_text: str, report_data: dict, attempts: int) -> Literal["ok", "fallback", "retry"]:
    """'ok' if every number is verified, 'fallback' after MAX_REPORT_ATTEMPTS failures, otherwise 'retry'."""
    if not unverified_numbers(report_text, report_data):
        return "ok"
    if attempts >= MAX_REPORT_ATTEMPTS:
        return "fallback"
    return "retry"


# החשיפה בסוף: הגבולות הסודיים, טווח ההסכמה וציון המחיר של כל עסקת בסיס
def debrief_data(buyer: BuyerTerms, seller: SellerProfile, report_data: dict) -> dict:
    """Reveal the supplier's secret limits and how close the base deals got to the best possible price."""
    zopa = compute_zopa(with_variant(buyer, "base"), seller)
    deals = {row["style"]: row["unit_price"] for row in report_data["simulations"]
             if row["variant"] == "base" and row["outcome"] == "deal"}
    scores = {}
    if zopa["zopa_exists"] and zopa["zopa_high"] > zopa["zopa_low"]:
        width = zopa["zopa_high"] - zopa["zopa_low"]
        scores = {style: round_price((zopa["zopa_high"] - price) / width) for style, price in deals.items()}
    return {"limits": {k: seller[k] for k in LIMIT_KEYS}, **zopa, "base_deals": deals, "price_scores": scores}
