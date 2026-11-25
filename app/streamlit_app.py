"""VBM Streamlit app: the same graph as the CLI, with a clearer screen (bonus)."""

import random
import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.types import Command

from vbm.adapters.display import BUYER_LABELS, SELLER_LABELS, outcome_he, result_line, transcript_he
from vbm.adapters.texts import STYLE_HE, TERMS_HE, VARIANT_HE
from vbm.infrastructure.reports import save_report

RTL_CSS = """
<style>
.stApp, .stMarkdown, .stTextArea textarea, .stTextInput input, [data-testid="stSidebar"] { direction: rtl; text-align: right; }
.stDataFrame, code { direction: ltr; }
</style>
"""
STYLE_OPTIONS = {"כל הסגנונות": None, "קשוח": "tough", "מאוזן": "balanced", "גמיש": "flexible"}
TERMS_OPTIONS = {TERMS_HE[k]: k for k in ("advance", "net30", "net60")}


# יצירת הגרף ומזהה שיחה חדש בתחילת כל ריצה
def new_session() -> None:
    """Reset the session: a fresh graph with its own checkpointer and thread id."""
    from vbm.infrastructure.workflow.graph import build_graph, memory_checkpointer
    st.session_state.graph = build_graph(memory_checkpointer())
    st.session_state.config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    st.session_state.stage = "input"
    st.session_state.translations = {}
    st.session_state.saved_path = None


# הרצת הגרף עד העצירה הבאה, עם פס התקדמות ושורה לכל סימולציה שהסתיימה
def run_graph(payload) -> None:
    """Stream the graph, show progress, then set the stage from the pending interrupt (or 'done')."""
    graph, config = st.session_state.graph, st.session_state.config
    progress, lines = None, None
    total, done = 0, 0
    for namespace, task in graph.stream(payload, config, stream_mode="tasks", subgraphs=True):
        values = task.get("result")
        if not isinstance(values, dict):
            continue
        if not namespace and task["name"] == "plan_simulations":
            total, done = len(values["sim_specs"]), 0
            progress = st.progress(0.0, text=f"מריץ {total} סימולציות...")
            lines = st.container()
        elif namespace and task["name"] == "finalize" and progress is not None:
            done += 1
            progress.progress(done / total, text=f"הסתיימו {done}/{total}")
            lines.write(result_line(values["sim_results"][0]))
    snapshot = graph.get_state(config)
    if snapshot.interrupts:
        st.session_state.pending = snapshot.interrupts[0].value
        st.session_state.stage = st.session_state.pending["type"]
    else:
        st.session_state.stage = "done"


# הערכים הנוכחיים ב-State של הגרף
def current_values() -> dict:
    """The main-graph state as it is now."""
    return st.session_state.graph.get_state(st.session_state.config).values


# שלב 1: הקלדת הבקשה החופשית
def show_input() -> None:
    """Free-text request and the start button."""
    text = st.text_area("מה אתה רוצה לקנות ומה הגבולות שלך?", height=140,
                        placeholder="אני רוצה לקנות 500 כיסאות משרדיים. התקציב המקסימלי 210 אלף ש\"ח...")
    if st.button("פענח בקשה", type="primary", disabled=not text.strip()):
        payload = {"raw_request": text.strip(), "seed": st.session_state.seed}
        style = STYLE_OPTIONS[st.session_state.style_choice]
        if style:
            payload["seller_styles"] = [style]
        with st.spinner("מפענח את הבקשה..."):
            run_graph(payload)
        st.rerun()


# עצירה 1: הצגת הפענוח, אישור או תיקון
def show_confirm() -> None:
    """Parsed terms and assumptions; confirm runs the simulations, a correction re-parses."""
    value = st.session_state.pending
    st.subheader("עצירה 1: האם הבנתי נכון?")
    rows = []
    for key, label in BUYER_LABELS.items():
        if key in value["buyer"]:
            shown = value["buyer"][key]
            rows.append({"שדה": label, "ערך": TERMS_HE.get(shown, shown) if key == "preferred_terms" else shown})
    for key, known in value["seller_known"].items():
        rows.append({"שדה": f"ידוע על הספק - {SELLER_LABELS[key]}", "ערך": known})
    st.table(rows)
    if value.get("notes"):
        st.info("הנחות שהונחו:\n\n" + value["notes"])
    if st.button("מאשר, הרץ סימולציות", type="primary", disabled=not value["buyer"]):
        run_graph(Command(resume={"action": "confirm"}))
        st.rerun()
    correction = st.text_input("או כתוב תיקון:")
    if st.button("שלח תיקון", disabled=not correction.strip()):
        with st.spinner("מפענח מחדש..."):
            run_graph(Command(resume={"action": "fix", "text": correction.strip()}))
        st.rerun()


# טבלת התוצאות של ה-batch הנוכחי
def results_table(results: list[dict], rows: list[dict]) -> None:
    """One row per simulation; `rows` are the matching ReportData simulation rows (lowest offer seen)."""
    st.dataframe([{
        "ספק": STYLE_HE[r["style"]], "גרסה": VARIANT_HE[r["variant"]], "תוצאה": outcome_he(r),
        "ההצעה הנמוכה שנצפתה": row["lowest_offer"],
        "סבבים": r["rounds"], "התערבויות מעקה": r["guardrail_hits"],
    } for r, row in zip(results, rows)], hide_index=True, width="stretch")


# צפייה בתמליל של סימולציה אחת, מתורגם לעברית
def transcript_viewer(results: list[dict]) -> None:
    """Pick a simulation and show its full Hebrew transcript (translation is cached per simulation)."""
    labels = [f"{i}. ספק {STYLE_HE[r['style']]} | {VARIANT_HE[r['variant']]}" for i, r in enumerate(results, 1)]
    choice = st.selectbox("תמליל לצפייה", labels, index=None, placeholder="בחר סימולציה")
    if choice is None:
        return
    result = results[labels.index(choice)]
    key = (result["batch_id"], result["style"], result["variant"])
    if key not in st.session_state.translations:
        from vbm.infrastructure.wiring import default_translator
        with st.spinner("מתרגם את ההודעות של הקונה..."):
            st.session_state.translations[key] = transcript_he(result, default_translator())
    for row in st.session_state.translations[key]:
        with st.chat_message("assistant" if row["speaker"] == "הספק" else "user"):
            st.markdown(f"**סבב {row['round']} - {row['speaker']}:** {row['text']}")
            if row["rationale"] is not None:
                st.caption(f"נימוק: {row['rationale']}")


# טופס "מה אם": שינוי העמדה של המשתמש
def change_terms_form(buyer: dict) -> dict:
    """Inputs pre-filled with the current terms; returns only the changed fields."""
    c1, c2 = st.columns(2)
    new = {
        "max_budget_total": c1.number_input(BUYER_LABELS["max_budget_total"], value=float(buyer["max_budget_total"]), step=1000.0),
        "target_total": c2.number_input(BUYER_LABELS["target_total"], value=float(buyer["target_total"]), step=1000.0),
        "deadline_days": c1.number_input(BUYER_LABELS["deadline_days"], value=int(buyer["deadline_days"]), step=1),
        "preferred_days": c2.number_input(BUYER_LABELS["preferred_days"], value=int(buyer["preferred_days"]), step=1),
    }
    terms = st.selectbox(BUYER_LABELS["preferred_terms"], list(TERMS_OPTIONS),
                         index=list(TERMS_OPTIONS.values()).index(buyer["preferred_terms"]))
    new["preferred_terms"] = TERMS_OPTIONS[terms]
    return {k: v for k, v in new.items() if v != buyer.get(k)}


# טופס "מה אם": שינוי ההנחות על הספק (ריק = לא ידוע)
def change_seller_form(known: dict) -> dict:
    """Inputs for what the user assumes about the supplier; an empty field means unknown."""
    st.caption("אלה ההנחות שלך על הספק, לא הנתונים האמיתיים שלו (הם נחשפים רק בסוף). שדה ריק = לא ידוע.")
    known = {k: (int(v) if k.endswith("days") else float(v)) for k, v in known.items()}
    c1, c2 = st.columns(2)
    values = {
        "list_price": c1.number_input(SELLER_LABELS["list_price"], value=known.get("list_price"), min_value=0.0,
                                      step=1.0, placeholder="לא ידוע"),
        "min_price": c2.number_input(SELLER_LABELS["min_price"], value=known.get("min_price"), min_value=0.0,
                                     step=1.0, placeholder="לא ידוע"),
        "standard_days": c1.number_input(SELLER_LABELS["standard_days"], value=known.get("standard_days"),
                                         min_value=0, step=1, placeholder="לא ידוע"),
        "min_days": c2.number_input(SELLER_LABELS["min_days"], value=known.get("min_days"), min_value=0,
                                    step=1, placeholder="לא ידוע"),
    }
    return {k: v for k, v in values.items() if v}


# עצירה 2: ממצאים ראשוניים ובחירה בין דוח ל"מה אם"
def show_findings() -> None:
    """Results, transcripts, preview and the what-if choice."""
    value, state = st.session_state.pending, current_values()
    results = [r for r in state["sim_results"] if r["batch_id"] == state["batch_id"]]
    st.subheader(f"עצירה 2: ממצאים ראשוניים (סבב בדיקה {state['batch_id']})")
    st.info(value["preview"].replace("\n", "\n\n"))
    if value.get("error"):
        st.error(f"השינוי הקודם לא תקין: {value['error']}")
    results_table(results, value["report_data"]["simulations"])
    transcript_viewer(results)
    st.divider()
    action = st.radio("מה הלאה?", ["להפיק דוח", "מה אם אשנה את העמדה שלי", "מה אם הספק שונה ממה שהנחתי"])
    if action == "להפיק דוח":
        answer = {"action": "report"}
    elif action == "מה אם אשנה את העמדה שלי":
        answer = {"action": "change_terms", "changes": change_terms_form(state["buyer"])}
    else:
        answer = {"action": "change_seller", "known": change_seller_form(state.get("seller_known") or {})}
    if st.button("המשך", type="primary"):
        with st.spinner("כותב את הדוח..." if answer["action"] == "report" else "מריץ שוב..."):
            run_graph(Command(resume=answer))
        st.rerun()


# הסוף: הדוח, החשיפה והורדת הקובץ
def show_done() -> None:
    """The report, the debrief and a download button; the report is saved once to reports/."""
    state = current_values()
    if st.session_state.saved_path is None:
        st.session_state.saved_path = save_report(state["report_text"], st.session_state.seed)
    if state["report_is_fallback"]:
        st.warning("הדוח שנוסח במודל לא עבר את בדיקת המספרים, ולכן מוצג דוח חלופי שהופק מהתוצאות.")
    st.markdown(state["report_text"])
    st.download_button("הורד את הדוח (Markdown)", state["report_text"],
                       file_name=st.session_state.saved_path.name, mime="text/markdown")
    st.caption(f"הדוח נשמר: {st.session_state.saved_path} | seed של הריצה: {st.session_state.seed}")
    debrief = state["debrief"]
    with st.expander("חשיפה: הגבולות הסודיים של הספק", expanded=True):
        cols = st.columns(4)
        for col, (key, label) in zip(cols, SELLER_LABELS.items()):
            col.metric(label, debrief["limits"][key])
        if debrief["zopa_low"] is None:
            st.write("הספק לא יכול לעמוד במועד שלך, ולכן לא היה טווח הסכמה.")
        else:
            st.write(f"הספק היה מוכן לרדת עד {debrief['zopa_low']} ליחידה; התקציב שלך היה {debrief['zopa_high']} ליחידה.")
        for style, price in debrief["base_deals"].items():
            score = debrief["price_scores"].get(style)
            extra = f" (ציון מחיר {score}, 1 = הטוב ביותר)" if score is not None else ""
            st.write(f"ספק {STYLE_HE[style]}: נסגר ב-{price}{extra}")


# נקודת הכניסה של האפליקציה
def main() -> None:
    """Page layout, sidebar settings and the stage dispatcher."""
    load_dotenv()
    st.set_page_config(page_title="VBM - Virtual Business Meeting", layout="wide")
    st.markdown(RTL_CSS, unsafe_allow_html=True)
    if "graph" not in st.session_state:
        st.session_state.seed = random.randint(1, 999_999)
        new_session()
    with st.sidebar:
        st.header("הגדרות")
        st.selectbox("סגנון ספק", list(STYLE_OPTIONS), key="style_choice")
        with st.expander("הגדרות מתקדמות"):
            st.number_input("seed (קובע את הספק המדומה)", min_value=1, step=1, key="seed")
        if st.button("התחל מחדש"):
            new_session()
            st.rerun()
    st.title("VBM - Virtual Business Meeting")
    {"input": show_input, "confirm_terms": show_confirm,
     "findings": show_findings, "done": show_done}[st.session_state.stage]()


main()
