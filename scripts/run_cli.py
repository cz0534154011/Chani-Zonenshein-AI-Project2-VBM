"""VBM command line: free-text request, both stops, live progress, results table and the report."""

import argparse
import random
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from vbm.analysis import CONCESSION_HE, REASON_HE, STYLE_HE, VARIANT_HE
from vbm.economics import variant_of
from vbm.seller_sim import TERMS_HE

BUYER_LABELS = {
    "product": "מוצר", "quantity": "כמות", "max_budget_total": "תקציב מקסימלי (סך הכל)",
    "target_total": "יעד (סך הכל)", "deadline_days": "מועד אחרון (ימים)",
    "preferred_days": "מועד מועדף (ימים)", "preferred_terms": "תנאי תשלום מועדפים",
}
SELLER_LABELS = {"list_price": "מחירון", "min_price": "מחיר מינימום", "standard_days": "זמן אספקה רגיל (ימים)",
                 "min_days": "זמן אספקה מינימלי (ימים)"}


# קריאת הפרמטרים של שורת הפקודה
def parse_args() -> argparse.Namespace:
    """--seed (printed; random if missing), --seller (one style only), --out (report folder)."""
    parser = argparse.ArgumentParser(description="VBM - purchasing meeting preparation")
    parser.add_argument("--seed", type=int, default=None, help="seed for the simulated supplier")
    parser.add_argument("--seller", choices=list(STYLE_HE), default=None, help="simulate one supplier style only")
    parser.add_argument("--out", default="reports", help="folder for the saved report")
    return parser.parse_args()


# קריאת בקשה בכמה שורות, עד שורה ריקה
def read_request() -> str:
    """Read the free-text request; an empty line ends it."""
    print("כתוב מה אתה רוצה לקנות ומה הגבולות שלך. שורה ריקה מסיימת:")
    lines = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines)


# הצעה בעברית
def offer_he(offer) -> str:
    """One offer as Hebrew text."""
    return f"{offer.unit_price} ליחידה, {offer.delivery_days} ימים, {TERMS_HE[offer.payment_terms]}"


# הדפסת שורת תמליל חדשה: שורת התקדמות בעברית, ומתחתיה ההודעה המקורית של הקונה
def print_entry(label: str, entry: dict) -> None:
    """Live progress line (option C1)."""
    if entry["speaker"] == "seller":
        print(f"{label} סבב {entry['round']} - הספק: {entry['message_he']}")
        return
    action = " או ".join(offer_he(o) for o in entry["offers"]) if entry["offers"] else "פרישה"
    print(f"{label} סבב {entry['round']} - הקונה: {action}")
    print(f"      {entry['message']}")


# הרצת הגרף עד העצירה הבאה או הסוף, עם תצוגה חיה של הסימולציות
def run_until_pause(graph, payload, config, labels: dict) -> object:
    """Stream finished tasks (including subgraph nodes), print new transcript entries, return the state snapshot."""
    for namespace, task in graph.stream(payload, config, stream_mode="tasks", subgraphs=True):
        values = task.get("result")
        if not namespace or not isinstance(values, dict):
            continue
        if task["name"] == "seller_open":
            labels[namespace] = f"[{STYLE_HE[values['seller']['style']]} | {VARIANT_HE[variant_of(values['buyer'])]}]"
        for entry in values.get("transcript", []):
            print_entry(labels.get(namespace, ""), entry)
    return graph.get_state(config)


# עצירה 1: הצגת הפענוח ובקשת אישור או תיקון
def ask_confirm(value: dict) -> dict:
    """Show the parsed terms and assumptions; Enter confirms, any text is a correction."""
    print("\n=== הפענוח של הבקשה ===")
    for key, label in BUYER_LABELS.items():
        if key in value["buyer"]:
            shown = value["buyer"][key]
            print(f"{label}: {TERMS_HE.get(shown, shown) if key == 'preferred_terms' else shown}")
    for key, known in value["seller_known"].items():
        print(f"ידוע על הספק - {SELLER_LABELS[key]}: {known}")
    if value.get("notes"):
        print("הנחות שהונחו:\n" + value["notes"])
    text = input("\nEnter לאישור, או כתוב תיקון: ").strip()
    return {"action": "confirm"} if not text else {"action": "fix", "text": text}


# פענוח "שדה=ערך, שדה=ערך" למילון עם מספרים
def parse_pairs(text: str) -> dict:
    """Parse 'key=value' pairs; numbers become int or float."""
    pairs = {}
    for part in text.split(","):
        if "=" not in part:
            continue
        key, raw = (s.strip() for s in part.split("=", 1))
        try:
            pairs[key] = int(raw) if raw.lstrip("-").isdigit() else float(raw)
        except ValueError:
            pairs[key] = raw
    return pairs


# טבלת התוצאות של ה-batch האחרון
def print_results_table(results: list[dict]) -> None:
    """One numbered line per simulation."""
    print("\n=== תוצאות הסימולציות ===")
    for i, r in enumerate(results, 1):
        outcome = offer_he(r["final"]) if r["final"] else f"אין עסקה ({REASON_HE[r['no_deal_reason']]})"
        print(f"{i}. ספק {STYLE_HE[r['style']]} | {VARIANT_HE[r['variant']]} | {r['rounds']} סבבים | {outcome}")


# תרגום ההודעות והנימוקים של הקונה לעברית, לתצוגה בלבד
def translate(texts: list[str]) -> list[str]:
    """Translate numbered English lines to Hebrew with the translation model."""
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


# הצגת תמליל מלא אחד בעברית, כולל הנימוקים של הקונה
def show_transcript(result: dict) -> None:
    """Print one full transcript: seller lines from the Hebrew template, buyer lines translated."""
    buyer_entries = [e for e in result["transcript"] if e["speaker"] == "buyer"]
    texts = []
    for e in buyer_entries:
        texts += [e["message"], e["rationale"] or ""]
    translated = iter(translate(texts)) if texts else iter([])
    print(f"\n=== תמליל: ספק {STYLE_HE[result['style']]}, {VARIANT_HE[result['variant']]} ===")
    for e in result["transcript"]:
        if e["speaker"] == "seller":
            print(f"סבב {e['round']} - הספק: {e['message_he']}")
        else:
            print(f"סבב {e['round']} - הקונה: {next(translated)}")
            print(f"      (נימוק: {next(translated)})")


# בחירת תמלילים לצפייה, עד Enter
def browse_transcripts(results: list[dict]) -> None:
    """Let the user open transcripts by number; Enter continues."""
    while True:
        choice = input("\nמספר סימולציה לצפייה בתמליל המלא, או Enter להמשך: ").strip()
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            show_transcript(results[int(choice) - 1])


# עצירה 2: ממצאים ראשוניים ובחירה: דוח, שינוי עמדה או שינוי הנחות על הספק
def ask_findings(value: dict, state: dict) -> dict:
    """Show the results and preview, then return the user's choice."""
    batch = [r for r in state["sim_results"] if r["batch_id"] == state["batch_id"]]
    print_results_table(batch)
    browse_transcripts(batch)
    print("\n=== ממצאים ראשוניים ===\n" + value["preview"])
    if value.get("error"):
        print(f"התשובה הקודמת לא תקינה: {value['error']}")
    print("\n1. להפיק דוח\n2. מה אם אשנה את העמדה שלי (למשל max_budget_total=220000)"
          "\n3. מה אם הספק שונה ממה שהנחתי (למשל list_price=450)")
    choice = input("בחירה: ").strip()
    if choice == "2":
        print("שדות: " + ", ".join(BUYER_LABELS))
        return {"action": "change_terms", "changes": parse_pairs(input("שינויים: "))}
    if choice == "3":
        print("שדות: " + ", ".join(SELLER_LABELS))
        return {"action": "change_seller", "known": parse_pairs(input("שינויים: "))}
    return {"action": "report"}


# החשיפה בסוף: הגבולות הסודיים וכמה קרוב הגיעו הסימולציות
def print_debrief(debrief: dict) -> None:
    """Reveal the supplier's limits, the ZOPA and the price score of each base deal."""
    print("\n=== חשיפה: הגבולות הסודיים של הספק ===")
    for key, label in SELLER_LABELS.items():
        print(f"{label}: {debrief['limits'][key]}")
    if debrief["zopa_low"] is None:
        print("הספק לא יכול לעמוד במועד שלך, ולכן לא היה טווח הסכמה.")
    else:
        print(f"הספק היה מוכן לרדת עד {debrief['zopa_low']} ליחידה; התקציב שלך היה {debrief['zopa_high']} ליחידה.")
    for style, price in debrief["base_deals"].items():
        score = debrief["price_scores"].get(style)
        extra = f" (ציון מחיר {score}, 1 = הטוב ביותר)" if score is not None else ""
        print(f"ספק {STYLE_HE[style]}: נסגר ב-{price}{extra}")


# שמירת הדוח לקובץ Markdown
def save_report(text: str, seed: int, out_dir: str) -> Path:
    """Write the report to <out_dir>/report_<time>_seed<seed>.md and return the path."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"report_{datetime.now():%Y%m%d_%H%M%S}_seed{seed}.md"
    path.write_text(text, encoding="utf-8")
    return path


# נקודת הכניסה: מפתחות, גרף עם checkpointer, ולולאה על העצירות עד הדוח
def main() -> None:
    """Run one interactive session from the request to the saved report."""
    load_dotenv()
    from vbm.graph import build_graph, memory_checkpointer

    args = parse_args()
    seed = args.seed if args.seed is not None else random.randint(1, 999_999)
    print(f"seed: {seed}")
    graph = build_graph(memory_checkpointer())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    payload = {"raw_request": read_request(), "seed": seed}
    if args.seller:
        payload["seller_styles"] = [args.seller]
    labels: dict = {}
    while True:
        snapshot = run_until_pause(graph, payload, config, labels)
        if not snapshot.interrupts:
            break
        value = snapshot.interrupts[0].value
        answer = ask_confirm(value) if value["type"] == "confirm_terms" else ask_findings(value, snapshot.values)
        payload = Command(resume=answer)
    final = snapshot.values
    note = " (דוח חלופי)" if final["report_is_fallback"] else ""
    print(f"\n=== הדוח{note} ===\n{final['report_text']}")
    print_debrief(final["debrief"])
    print(f"\nהדוח נשמר: {save_report(final['report_text'], seed, args.out)}")


if __name__ == "__main__":
    main()
