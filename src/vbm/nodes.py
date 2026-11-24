"""VBM main-graph nodes, both interrupts and routing (spec sections 3-4)."""

import re

from langgraph.types import Send, interrupt

from vbm.analysis import CONCESSION_HE, REASON_HE, STYLE_HE, VARIANT_HE, analyze_results, current_batch
from vbm.config import MAX_REPORT_ATTEMPTS, MAX_ROUNDS
from vbm.economics import compute_zopa, round_price, with_variant
from vbm.llm import get_parser, get_report_writer
from vbm.prompts.parser import build_parser_prompt
from vbm.prompts.report import build_report_prompt
from vbm.scenario_generator import STYLES, generate_limits, profiles_for_all_styles
from vbm.schemas import validate_buyer_terms
from vbm.state import MainState

VARIANTS = ("base", "payment", "delivery")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
SMALL_NUMBERS = set(range(0, 11))
LIMIT_KEYS = ("list_price", "min_price", "standard_days", "min_days")


# הגבולות של הספק: מהדאטהסט (בהערכה) או מהגרלה, ומה שהמשתמש יודע גובר
def seller_limits(state: MainState, known: dict) -> dict:
    """Supplier limits for the next batch: dataset limits or a seeded draw, overridden by `known`."""
    if state.get("seller_profiles"):
        return {**state["seller_profiles"], **known}
    return generate_limits(state.get("draw_buyer") or state["buyer"], state.get("seed", 0), known)


# המפענח: טקסט חופשי -> BuyerTerms ו-parse_notes
def parse_request(state: MainState) -> dict:
    """Parse the free-text request; on failure leave the buyer empty and explain in parse_notes."""
    parsed = get_parser().invoke(build_parser_prompt(state["raw_request"]))
    if parsed is None:
        return {"buyer": {}, "terms_confirmed": False,
                "parse_notes": "לא הצלחתי לפענח את הבקשה. נא לנסח מחדש או להוסיף פרטים."}
    buyer = {"product": parsed.product, "quantity": parsed.quantity,
             "max_budget_total": parsed.max_budget_total, "target_total": parsed.target_total,
             "deadline_days": parsed.deadline_days, "preferred_terms": parsed.preferred_terms}
    if parsed.preferred_days is not None:
        buyer["preferred_days"] = parsed.preferred_days
    known = dict(state.get("seller_known") or {})
    if parsed.known_list_price is not None:
        known["list_price"] = parsed.known_list_price
    if parsed.known_standard_days is not None:
        known["standard_days"] = parsed.known_standard_days
    notes = list(parsed.notes)
    try:
        checked = validate_buyer_terms(buyer)
    except ValueError as error:
        notes.append(f"הנתונים שפוענחו אינם תקינים: {error}")
        checked = {}
    return {"buyer": checked, "seller_known": known, "parse_notes": "\n".join(notes), "terms_confirmed": False}


# עצירה 1: המשתמש מאשר את הפענוח או מתקן אותו
def confirm_terms(state: MainState) -> dict:
    """Interrupt with the parsed terms; 'confirm' continues, 'fix' + text sends back to parsing."""
    answer = interrupt({"type": "confirm_terms", "buyer": state["buyer"],
                        "seller_known": state.get("seller_known") or {}, "notes": state.get("parse_notes")})
    if answer.get("action") == "confirm" and state["buyer"]:
        return {"terms_confirmed": True}
    correction = answer.get("text", "").strip()
    return {"terms_confirmed": False, "raw_request": f"{state['raw_request']}\nתיקון: {correction}"}


# תכנון הסימולציות: ספק לכל סגנון x שלוש גרסאות קונה, עם batch חדש
def plan_simulations(state: MainState) -> dict:
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


# ניתוח בקוד של ה-batch הנוכחי
def analyze(state: MainState) -> dict:
    """Compute ReportData from the current batch only."""
    results = current_batch(state["sim_results"], state["batch_id"])
    return {"report_data": analyze_results(results, state["buyer"])}


# החלת הבחירה של המשתמש בעצירה 2, עם בדיקת תקינות
def apply_changes(state: MainState, answer: dict) -> dict:
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


# עצירה 2: ממצאים ראשוניים, והמשתמש בוחר שינוי עמדה, שינוי הנחות על הספק או דוח
def findings_review(state: MainState) -> dict:
    """Interrupt with the preview; the answer decides between the what-if loop and the report."""
    previous = state.get("user_choice") or {}
    error = previous.get("error") if previous.get("action") == "invalid" else None
    answer = interrupt({"type": "findings", "preview": state["report_data"]["preview"],
                        "report_data": state["report_data"], "error": error})
    return apply_changes(state, answer)


# כל המספרים בטקסט
def numbers_in_text(text: str) -> list[str]:
    """Number tokens in a text, as written."""
    return NUMBER_RE.findall(text)


# כל המספרים שמופיעים ב-ReportData, כולל בתוך מחרוזות
def numbers_in_data(value) -> set[float]:
    """Every number found anywhere in a nested structure."""
    found: set[float] = set()
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.add(float(value))
    elif isinstance(value, str):
        found.update(float(t.replace(",", "")) for t in numbers_in_text(value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in_data(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= numbers_in_data(item)
    return found


# המספרים בדוח שלא קיימים ב-ReportData
def unverified_numbers(text: str, report_data: dict) -> list[str]:
    """Numbers in the report that do not appear in ReportData (small counts 0-10 are allowed)."""
    allowed = numbers_in_data(report_data) | {float(n) for n in SMALL_NUMBERS}
    bad = []
    for token in numbers_in_text(text):
        value = float(token.replace(",", ""))
        if not any(abs(value - a) <= 0.01 for a in allowed) and token not in bad:
            bad.append(token)
    return bad


# הדוח מנוסח במודל, רק מתוך ReportData
def write_report(state: MainState) -> dict:
    """Ask the report model for the report; on a retry, tell it which numbers failed."""
    previous = state.get("report_text")
    unverified = unverified_numbers(previous, state["report_data"]) if previous else []
    text = get_report_writer().invoke(build_report_prompt(state["report_data"], unverified))
    return {"report_text": text, "report_attempts": state.get("report_attempts", 0) + 1}


# דוח חלופי מתבנית, כשהמודל נכשל באימות 3 פעמים
def fallback_report(data: dict) -> str:
    """Hebrew Markdown report built in code from ReportData."""
    lines = ["> דוח חלופי: הדוח שנוסח במודל לא עבר את בדיקת המספרים, ולכן הדוח הזה הופק ישירות מהתוצאות.", ""]
    lines.append("## האם אפשר לסגור עסקה")
    for style, ok in data["feasibility"].items():
        lines.append(f"- ספק {STYLE_HE[style]}: {'נסגרה עסקה' if ok else 'לא נסגרה עסקה'} בגרסת הבסיס.")
    lines += ["", "## טווח מחירים סביר"]
    if data["price_range"]:
        lines.append(f"- {data['price_range']['min']} עד {data['price_range']['max']} ליחידה.")
    else:
        lines.append("- לא נסגרה אף עסקה בגרסת הבסיס.")
    lines += ["", "## על מה כדאי להתגמש", f"- {CONCESSION_HE[data['decisive_concession']]}."]
    for variant, value in data["variant_means"].items():
        shown = value if value is not None else "אין עסקאות"
        lines.append(f"- מחיר ממוצע בגרסת {VARIANT_HE[variant]}: {shown}.")
    lines += ["", "## מה מפוצץ את העסקה"]
    if data["dealbreakers"]:
        lines += [f"- {REASON_HE[reason]}: {count}." for reason, count in data["dealbreakers"].items()]
    else:
        lines.append("- בכל הסימולציות נסגרה עסקה.")
    lines += ["", "## כמה סבלנות נדרשת"]
    if data["patience"] is not None:
        lines.append(f"- ספק קשוח התחיל לוותר בסבב {data['patience']}.")
    else:
        lines.append(f"- ספק קשוח לא ירד מתחת ל-{data['patience_threshold_percent']}% מהמחירון.")
    lines += ["", "התוצאות מבוססות על סימולציות, ואינן הבטחה להתנהגות הספק האמיתי."]
    return "\n".join(lines)


# אימות הדוח: כל מספר בטקסט חייב להופיע ב-ReportData; אחרי 3 כישלונות - דוח חלופי
def verify_report(state: MainState) -> dict:
    """Check the report numbers; after MAX_REPORT_ATTEMPTS failures replace it with the fallback report."""
    if not unverified_numbers(state["report_text"], state["report_data"]):
        return {"report_ok": True, "report_is_fallback": False}
    if state["report_attempts"] >= MAX_REPORT_ATTEMPTS:
        return {"report_ok": False, "report_is_fallback": True, "report_text": fallback_report(state["report_data"])}
    return {"report_ok": False, "report_is_fallback": False}


# החשיפה בסוף: הגבולות הסודיים, טווח ההסכמה וציון המחיר של כל עסקת בסיס
def debrief(state: MainState) -> dict:
    """Reveal the supplier's secret limits and how close the base deals got to the best possible price."""
    seller = state["sim_specs"][0]["seller"]
    zopa = compute_zopa(with_variant(state["buyer"], "base"), seller)
    deals = {row["style"]: row["unit_price"] for row in state["report_data"]["simulations"]
             if row["variant"] == "base" and row["outcome"] == "deal"}
    scores = {}
    if zopa["zopa_exists"] and zopa["zopa_high"] > zopa["zopa_low"]:
        width = zopa["zopa_high"] - zopa["zopa_low"]
        scores = {style: round_price((zopa["zopa_high"] - price) / width) for style, price in deals.items()}
    return {"debrief": {"limits": {k: seller[k] for k in LIMIT_KEYS}, **zopa,
                        "base_deals": deals, "price_scores": scores}}


# פיצול ל-Send: סימולציה אחת לכל מפרט
def fan_out(state: MainState) -> list[Send]:
    """One Send to 'negotiate' per simulation spec (run in parallel)."""
    return [Send("negotiate", spec) for spec in state["sim_specs"]]


# בהתחלה: טקסט חופשי לפענוח, או נתונים מובנים (הערכה) ישר לתכנון
def route_start(state: MainState) -> str:
    """'parse_request' for free text, 'plan_simulations' for structured input."""
    return "parse_request" if state.get("raw_request") else "plan_simulations"


# אחרי עצירה 1: אישור -> תכנון, תיקון -> פענוח מחדש
def route_after_confirm(state: MainState) -> str:
    """'plan_simulations' if confirmed, otherwise 'parse_request'."""
    return "plan_simulations" if state["terms_confirmed"] else "parse_request"


# אחרי עצירה 2: דוח, לולאת "מה אם", או עצירה שוב אם התשובה לא תקינה
def route_after_review(state: MainState) -> str:
    """'write_report', 'plan_simulations' (what-if loop) or 'findings_review' (invalid answer)."""
    action = state["user_choice"]["action"]
    if action == "report":
        return "write_report"
    if action == "invalid":
        return "findings_review"
    return "plan_simulations"


# אחרי אימות הדוח: הצלחה או דוח חלופי -> חשיפה; אחרת כתיבה מחדש
def route_after_verify(state: MainState) -> str:
    """'debrief' if the report passed or the fallback was used, otherwise 'write_report'."""
    if state["report_ok"] or state["report_is_fallback"]:
        return "debrief"
    return "write_report"
