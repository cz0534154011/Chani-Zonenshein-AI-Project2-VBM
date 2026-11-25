"""VBM command line: free-text request, both stops, live progress, results table and the report."""

import argparse
import random
import uuid

from dotenv import load_dotenv
from langgraph.types import Command

from vbm.adapters.display import BUYER_LABELS, SELLER_LABELS, offer_he, result_line, transcript_he
from vbm.adapters.texts import REASON_HE, STYLE_HE, TERMS_HE, VARIANT_HE
from vbm.infrastructure.reports import save_report


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


# הרצת הגרף עד העצירה הבאה או הסוף: מונה שמתעדכן במקום, ושורה לכל סימולציה שהסתיימה
def run_until_pause(graph, payload, config) -> object:
    """Stream finished tasks, show a progress counter and one line per finished simulation."""
    total, done = 0, 0
    for namespace, task in graph.stream(payload, config, stream_mode="tasks", subgraphs=True):
        values = task.get("result")
        if not isinstance(values, dict):
            continue
        if not namespace and task["name"] == "plan_simulations":
            total, done = len(values["sim_specs"]), 0
            print(f"\nמריץ {total} סימולציות...")
        elif namespace and task["name"] == "finalize":
            done += 1
            print("\r" + result_line(values["sim_results"][0]))
        else:
            continue
        print(f"\rהסתיימו {done}/{total}", end="" if done < total else "\n", flush=True)
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


# טבלת התוצאות של ה-batch האחרון, עם ההצעה הנמוכה שנצפתה בכל סימולציה
def print_results_table(results: list[dict], rows: list[dict]) -> None:
    """One numbered line per simulation; `rows` are the matching ReportData simulation rows."""
    print("\n=== תוצאות הסימולציות ===")
    for i, (r, row) in enumerate(zip(results, rows), 1):
        outcome = offer_he(r["final"]) if r["final"] else f"אין עסקה ({REASON_HE[r['no_deal_reason']]})"
        lowest = row["lowest_offer"] if row["lowest_offer"] is not None else "-"
        print(f"{i}. ספק {STYLE_HE[r['style']]} | {VARIANT_HE[r['variant']]} | {r['rounds']} סבבים | {outcome}"
              f" | ההצעה הנמוכה שנצפתה: {lowest}")


# הצגת תמליל מלא אחד בעברית, כולל הנימוקים של הקונה
def show_transcript(result: dict) -> None:
    """Print one full transcript in Hebrew."""
    from vbm.infrastructure.wiring import default_translator
    print(f"\n=== תמליל: ספק {STYLE_HE[result['style']]}, {VARIANT_HE[result['variant']]} ===")
    for row in transcript_he(result, default_translator()):
        print(f"סבב {row['round']} - {row['speaker']}: {row['text']}")
        if row["rationale"] is not None:
            print(f"      (נימוק: {row['rationale']})")


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
    print_results_table(batch, value["report_data"]["simulations"])
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


# נקודת הכניסה: מפתחות, גרף עם checkpointer, ולולאה על העצירות עד הדוח
def main() -> None:
    """Run one interactive session from the request to the saved report."""
    load_dotenv()
    from vbm.infrastructure.workflow.graph import build_graph, memory_checkpointer

    args = parse_args()
    seed = args.seed if args.seed is not None else random.randint(1, 999_999)
    print(f"seed: {seed}")
    graph = build_graph(memory_checkpointer())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    payload = {"raw_request": read_request(), "seed": seed}
    if args.seller:
        payload["seller_styles"] = [args.seller]
    while True:
        snapshot = run_until_pause(graph, payload, config)
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
