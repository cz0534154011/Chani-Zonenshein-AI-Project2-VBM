"""VBM display helpers shared by the CLI and the Streamlit app (Hebrew text, translation, report file)."""

from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from vbm.analysis import REASON_HE, STYLE_HE, VARIANT_HE
from vbm.seller_sim import TERMS_HE

BUYER_LABELS = {
    "product": "מוצר", "quantity": "כמות", "max_budget_total": "תקציב מקסימלי (סך הכל)",
    "target_total": "יעד (סך הכל)", "deadline_days": "מועד אחרון (ימים)",
    "preferred_days": "מועד מועדף (ימים)", "preferred_terms": "תנאי תשלום מועדפים",
}
SELLER_LABELS = {"list_price": "מחירון", "min_price": "מחיר מינימום", "standard_days": "זמן אספקה רגיל (ימים)",
                 "min_days": "זמן אספקה מינימלי (ימים)"}


# הצעה בעברית
def offer_he(offer) -> str:
    """One offer as Hebrew text."""
    return f"{offer.unit_price} ליחידה, {offer.delivery_days} ימים, {TERMS_HE[offer.payment_terms]}"


# תווית של סימולציה: סגנון הספק וגרסת הקונה
def sim_label(result: dict) -> str:
    """'[style | variant]' in Hebrew."""
    return f"[{STYLE_HE[result['style']]} | {VARIANT_HE[result['variant']]}]"


# תיאור התוצאה של סימולציה בעברית
def outcome_he(result: dict) -> str:
    """Deal terms, or 'no deal' with the reason."""
    if result["final"]:
        return f"עסקה: {offer_he(result['final'])}"
    return f"אין עסקה: {REASON_HE[result['no_deal_reason']]}"


# שורת תוצאה אחת לסימולציה שהסתיימה
def result_line(result: dict) -> str:
    """'[style | variant] outcome (N rounds)'."""
    return f"{sim_label(result)} {outcome_he(result)} ({result['rounds']} סבבים)"


# תרגום שורות ממוספרות לעברית, לתצוגה בלבד
def translate(texts: list[str]) -> list[str]:
    """Translate English lines to Hebrew with the translation model; untranslated lines stay as they are."""
    from vbm.llm import get_translator
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    system = ("Translate each numbered line to Hebrew. Keep every number exactly. "
              "Return the same numbering, one line per item, nothing else.")
    answer = get_translator().invoke([SystemMessage(content=system), HumanMessage(content=numbered)])
    out = {}
    for line in answer.splitlines():
        head, _, rest = line.partition(".")
        if head.strip().isdigit():
            out[int(head)] = rest.strip()
    return [out.get(i, t) for i, t in enumerate(texts, 1)]


# התמליל של סימולציה בעברית: הספק מהתבנית, הקונה מתורגם, כולל הנימוק
def transcript_he(result: dict) -> list[dict]:
    """Rows of {round, speaker, text, rationale} in Hebrew for one simulation."""
    buyer_entries = [e for e in result["transcript"] if e["speaker"] == "buyer"]
    texts = []
    for e in buyer_entries:
        texts += [e["message"], e["rationale"] or "-"]
    translated = iter(translate(texts)) if texts else iter([])
    rows = []
    for e in result["transcript"]:
        if e["speaker"] == "seller":
            rows.append({"round": e["round"], "speaker": "הספק", "text": e["message_he"], "rationale": None})
        else:
            rows.append({"round": e["round"], "speaker": "הקונה", "text": next(translated),
                         "rationale": next(translated)})
    return rows


# שמירת הדוח לקובץ Markdown
def save_report(text: str, seed: int, out_dir: str = "reports") -> Path:
    """Write the report to <out_dir>/report_<time>_seed<seed>.md and return the path."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"report_{datetime.now():%Y%m%d_%H%M%S}_seed{seed}.md"
    path.write_text(text, encoding="utf-8")
    return path
