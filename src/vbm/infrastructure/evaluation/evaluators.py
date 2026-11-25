"""VBM evaluation: the target that runs the graph without a human, and code-only evaluators (spec section 9)."""

from uuid import uuid4

from langgraph.types import Command

from vbm.application.ports import Ports
from vbm.domain.economics import round_price
from vbm.infrastructure.settings import PROMPT_VERSION
from vbm.infrastructure.workflow.graph import build_graph, memory_checkpointer

# המדיניות הקבועה במקום אדם: עצירה 1 מאשרת, עצירה 2 מפיקה דוח
POLICY: dict[str, dict] = {
    "confirm_terms": {"action": "confirm"},
    "findings": {"action": "report"},
}


# שורה מקוצרת לכל סימולציה, בלי תמליל (התמליל נמצא ב-trace)
def sim_summary(result: dict, quantity: int) -> dict:
    """Compact simulation row with what the evaluators need."""
    final, first = result["final"], result["first_offer"]
    return {
        "style": result["style"], "variant": result["variant"], "outcome": result["outcome"],
        "unit_price": final.unit_price if final else None,
        "total": round_price(final.unit_price * quantity) if final else None,
        "first_offer_price": first.unit_price if first else None,
        "accepted_opening": result["accepted_opening"], "guardrail_hits": result["guardrail_hits"],
    }


# בונה את פונקציית ה-target לגרסת פרומפט: מריצה את הגרף, עונה על העצירות לפי המדיניות ומחזירה פלט להערכה
def make_target(prompt_version: str = PROMPT_VERSION, ports: Ports | None = None):
    """Return target(inputs) that runs the main graph with the given buyer prompt version and the fixed policy."""
    def target(inputs: dict) -> dict:
        graph = build_graph(memory_checkpointer(), ports)
        config = {"configurable": {"thread_id": str(uuid4()), "prompt_version": prompt_version}}
        graph.invoke(inputs, config)
        while interrupts := graph.get_state(config).interrupts:
            graph.invoke(Command(resume=POLICY[interrupts[0].value["type"]]), config)
        state = graph.get_state(config).values
        quantity = state["buyer"]["quantity"]
        return {
            "report_data": state["report_data"],
            "report_ok": state["report_ok"],
            "report_is_fallback": state["report_is_fallback"],
            "sims": [sim_summary(r, quantity) for r in state["sim_results"]],
        }
    return target


# תוצאה אחת בפורמט של LangSmith; score=None = המדד לא נספר בתרחיש הזה
def result(key: str, score: float | None, comment: str | None = None) -> dict:
    """One LangSmith evaluation result."""
    return {"key": key, "score": score, "comment": comment}


# הסימולציות של גרסת הבסיס
def base_sims(outputs: dict) -> list[dict]:
    """The three base-variant simulation rows."""
    return [s for s in outputs.get("sims", []) if s["variant"] == "base"]


# רוחב הטווח, או None כשאין טווח
def zopa_width(reference: dict) -> float | None:
    """zopa_high - zopa_low when a ZOPA exists, else None."""
    if not reference["zopa_exists"] or reference["zopa_high"] <= reference["zopa_low"]:
        return None
    return reference["zopa_high"] - reference["zopa_low"]


# נסגרה עסקה בבסיס מול לפחות סגנון אחד == יש טווח
def feasibility_correct(outputs: dict, reference_outputs: dict) -> dict:
    """1 if 'a base deal closed with at least one style' matches zopa_exists."""
    if "sims" not in outputs:
        return result("feasibility_correct", None, "no outputs")
    closed = any(s["outcome"] == "deal" for s in base_sims(outputs))
    return result("feasibility_correct", float(closed == reference_outputs["zopa_exists"]))


# רק כשיש טווח: חלק הסגנונות שבהם נסגרה עסקה בבסיס
def close_rate(outputs: dict, reference_outputs: dict) -> dict:
    """Share of base simulations that closed; not counted when there is no ZOPA."""
    base = base_sims(outputs)
    if not reference_outputs["zopa_exists"] or not base:
        return result("close_rate", None, "no zopa")
    return result("close_rate", sum(s["outcome"] == "deal" for s in base) / len(base))


# המדד העיקרי: מיקום מחיר העסקה בטווח, 1 = הטוב ביותר לקונה
def price_score(outputs: dict, reference_outputs: dict) -> dict:
    """Mean of (zopa_high - price) / (zopa_high - zopa_low) over base deals, clipped to 0..1."""
    width = zopa_width(reference_outputs)
    prices = [s["unit_price"] for s in base_sims(outputs) if s["outcome"] == "deal"]
    if width is None:
        return result("price_score", None, "no zopa")
    if not prices:
        return result("price_score", None, "no base deal")
    scores = [min(1.0, max(0.0, (reference_outputs["zopa_high"] - p) / width)) for p in prices]
    return result("price_score", sum(scores) / len(scores))


# הוויתור המכריע בדוח מול התשובה האנליטית
def decisive_concession_correct(outputs: dict, reference_outputs: dict) -> dict:
    """1 if ReportData.decisive_concession equals the known answer."""
    if "report_data" not in outputs:
        return result("decisive_concession_correct", None, "no outputs")
    found = outputs["report_data"]["decisive_concession"]
    expected = reference_outputs["decisive_concession"]
    return result("decisive_concession_correct", float(found == expected), f"found {found}, expected {expected}")


# 1 אם בסימולציה כלשהי הסכום הכולל עבר את התקציב
def budget_violation(inputs: dict, outputs: dict) -> dict:
    """1 if any deal, in any variant, has a total above the maximum budget."""
    if "sims" not in outputs:
        return result("budget_violation", None, "no outputs")
    budget = inputs["buyer"]["max_budget_total"]
    return result("budget_violation", float(any(s["total"] is not None and s["total"] > budget for s in outputs["sims"])))


# האימות של הדוח עבר (דוח חלופי = 0)
def report_numbers_match(outputs: dict) -> dict:
    """1 if verify_report passed."""
    if "report_ok" not in outputs:
        return result("report_numbers_match", None, "no outputs")
    return result("report_numbers_match", float(outputs["report_ok"]))


# אבחון: חלק הסימולציות שבהן הקונה קיבל את הצעת הפתיחה
def accepted_opening_rate(outputs: dict) -> dict:
    """Share of the 9 simulations where the buyer accepted the supplier's opening offer."""
    sims = outputs.get("sims", [])
    if not sims:
        return result("accepted_opening_rate", None, "no outputs")
    return result("accepted_opening_rate", sum(s["accepted_opening"] for s in sims) / len(sims))


# אבחון: מיקום ההצעה הראשונה של הקונה בטווח (בסיס בלבד, בלי חיתוך: שלילי = מתחת לרצפה)
def first_offer_position(outputs: dict, reference_outputs: dict) -> dict:
    """Mean of (first offer - zopa_low) / (zopa_high - zopa_low) over base simulations."""
    width = zopa_width(reference_outputs)
    firsts = [s["first_offer_price"] for s in base_sims(outputs) if s["first_offer_price"] is not None]
    if width is None or not firsts:
        return result("first_offer_position", None, "no zopa or no offer")
    positions = [(p - reference_outputs["zopa_low"]) / width for p in firsts]
    return result("first_offer_position", round(sum(positions) / len(positions), 4))


# אבחון: סך ההתערבויות של המעקה ב-9 הסימולציות
def guardrail_hits(outputs: dict) -> dict:
    """Total guardrail rejections and clamps over the 9 simulations."""
    if "sims" not in outputs:
        return result("guardrail_hits", None, "no outputs")
    return result("guardrail_hits", float(sum(s["guardrail_hits"] for s in outputs["sims"])))


EVALUATORS = [
    feasibility_correct, close_rate, price_score, decisive_concession_correct, budget_violation,
    report_numbers_match, accepted_opening_rate, first_offer_position, guardrail_hits,
]


# ממוצע של ציונים, בלי הריצות שבהן המדד לא נספר
def mean_score(scores) -> float | None:
    """Mean of the scores that are not None (None if there are none)."""
    counted = [s for s in scores if s is not None]
    return round(sum(counted) / len(counted), 4) if counted else None


# המדדים המסכמים של ניסוי (נספח ג); משמש גם את סקריפט ההשוואה
def summary_metrics(outputs: list[dict], references: list[dict]) -> dict[str, float | None]:
    """mean_price_score, feasibility_accuracy, decisive_accuracy and mean_close_rate over all runs."""
    rows = [(o or {}, r) for o, r in zip(outputs, references)]
    return {
        "mean_price_score": mean_score(price_score(o, r)["score"] for o, r in rows),
        "feasibility_accuracy": mean_score(feasibility_correct(o, r)["score"] for o, r in rows),
        "decisive_accuracy": mean_score(decisive_concession_correct(o, r)["score"] for o, r in rows),
        "mean_close_rate": mean_score(close_rate(o, r)["score"] for o, r in rows),
    }


# מעריך מסכם בפורמט של LangSmith
def summary_evaluator(outputs: list[dict], reference_outputs: list[dict]) -> dict:
    """LangSmith summary evaluator: the four summary metrics."""
    metrics = summary_metrics(outputs, reference_outputs)
    return {"results": [result(key, score) for key, score in metrics.items()]}
