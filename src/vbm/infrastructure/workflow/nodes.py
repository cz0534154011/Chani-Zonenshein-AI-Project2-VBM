"""VBM main-graph nodes, both interrupts and routing (spec sections 3-4): thin wrappers over the application layer."""

from langgraph.types import Send, interrupt

from vbm.adapters.texts import PARSE_FAILED_NOTE, build_preview, corrected_request, fallback_report, invalid_terms_note
from vbm.application.analysis import analyze_results, current_batch
from vbm.application.meeting_prep import (apply_changes, correction_of, debrief_data, is_confirmed, plan_batch,
                                          read_parsed_request, report_status)
from vbm.application.numbers import unverified_numbers
from vbm.application.ports import ReportWriter, RequestParser
from vbm.domain.rules import MAX_ROUNDS
from vbm.infrastructure.workflow.state import MainState


# המפענח: טקסט חופשי -> BuyerTerms ו-parse_notes
def make_parse_request(parser: RequestParser):
    """Return the parse_request node bound to the given parser port."""
    def parse_request(state: MainState) -> dict:
        """Parse the free-text request; on failure leave the buyer empty and explain in parse_notes."""
        parsed = parser.parse(state["raw_request"])
        if parsed is None:
            return {"buyer": {}, "terms_confirmed": False, "parse_notes": PARSE_FAILED_NOTE}
        reading = read_parsed_request(parsed, state.get("seller_known"))
        notes = reading["notes"] + ([invalid_terms_note(reading["error"])] if reading["error"] else [])
        return {"buyer": reading["buyer"], "seller_known": reading["seller_known"], "parse_notes": "\n".join(notes),
                "terms_confirmed": False}
    return parse_request


# עצירה 1: המשתמש מאשר את הפענוח או מתקן אותו
def confirm_terms(state: MainState) -> dict:
    """Interrupt with the parsed terms; 'confirm' continues, 'fix' + text sends back to parsing."""
    answer = interrupt({"type": "confirm_terms", "buyer": state["buyer"],
                        "seller_known": state.get("seller_known") or {}, "notes": state.get("parse_notes")})
    if is_confirmed(answer, state["buyer"]):
        return {"terms_confirmed": True}
    return {"terms_confirmed": False, "raw_request": corrected_request(state["raw_request"], correction_of(answer))}


# תכנון הסימולציות: ספק לכל סגנון x שלוש גרסאות קונה, עם batch חדש
def plan_simulations(state: MainState) -> dict:
    """Build the simulation specs (3 styles x 3 variants by default) and start a new batch."""
    return plan_batch(state)


# ניתוח בקוד של ה-batch הנוכחי, ותקציר לעצירה 2
def analyze(state: MainState) -> dict:
    """Compute ReportData from the current batch only and add the Hebrew preview."""
    results = current_batch(state["sim_results"], state["batch_id"])
    data = analyze_results(results, state["buyer"], state.get("max_rounds", MAX_ROUNDS))
    data["preview"] = build_preview(data)
    return {"report_data": data}


# עצירה 2: ממצאים ראשוניים, והמשתמש בוחר שינוי עמדה, שינוי הנחות על הספק או דוח
def findings_review(state: MainState) -> dict:
    """Interrupt with the preview; the answer decides between the what-if loop and the report."""
    previous = state.get("user_choice") or {}
    error = previous.get("error") if previous.get("action") == "invalid" else None
    answer = interrupt({"type": "findings", "preview": state["report_data"]["preview"],
                        "report_data": state["report_data"], "error": error})
    return apply_changes(state, answer)


# הדוח מנוסח במודל, רק מתוך ReportData
def make_write_report(writer: ReportWriter):
    """Return the write_report node bound to the given report-writer port."""
    def write_report(state: MainState) -> dict:
        """Ask the report model for the report; on a retry, tell it which numbers failed."""
        previous = state.get("report_text")
        unverified = unverified_numbers(previous, state["report_data"]) if previous else []
        text = writer.write(state["report_data"], unverified)
        return {"report_text": text, "report_attempts": state.get("report_attempts", 0) + 1}
    return write_report


# אימות הדוח: כל מספר בטקסט חייב להופיע ב-ReportData; אחרי 3 כישלונות - דוח חלופי
def verify_report(state: MainState) -> dict:
    """Check the report numbers; after MAX_REPORT_ATTEMPTS failures replace it with the fallback report."""
    status = report_status(state["report_text"], state["report_data"], state["report_attempts"])
    if status == "ok":
        return {"report_ok": True, "report_is_fallback": False}
    if status == "fallback":
        return {"report_ok": False, "report_is_fallback": True, "report_text": fallback_report(state["report_data"])}
    return {"report_ok": False, "report_is_fallback": False}


# החשיפה בסוף: הגבולות הסודיים, טווח ההסכמה וציון המחיר של כל עסקת בסיס
def debrief(state: MainState) -> dict:
    """Reveal the supplier's secret limits and how close the base deals got to the best possible price."""
    return {"debrief": debrief_data(state["buyer"], state["sim_specs"][0]["seller"], state["report_data"])}


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
