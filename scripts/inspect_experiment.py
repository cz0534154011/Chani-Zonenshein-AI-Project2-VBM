"""Print the negotiations behind an experiment's weak spots in LangSmith: lowest price scores, or base no-deals (no model calls)."""

import argparse
from collections import Counter

from dotenv import load_dotenv

from vbm.infrastructure.evaluation.evaluators import price_score
from vbm.infrastructure.settings import DATASET_NAME


# ערך של שדה בהצעה, גם כשההצעה נשמרה כמילון וגם כאובייקט
def offer_text(offer) -> str:
    """'price / days / terms' for an offer saved as a dict or as an object."""
    get = offer.get if isinstance(offer, dict) else lambda k: getattr(offer, k, None)
    return f"{get('unit_price')} / {get('delivery_days')}d / {get('payment_terms')}"


# הריצות הראשיות של הניסוי, כל אחת עם התשובה הידועה שלה
def scored_runs(client, name: str) -> list[tuple[object, dict]]:
    """(root run, reference outputs) for every finished run of the experiment."""
    references = {e.id: e.outputs for e in client.list_examples(dataset_name=DATASET_NAME)}
    return [(run, references[run.reference_example_id]) for run in client.list_runs(project_name=name, is_root=True)
            if run.reference_example_id and run.outputs]


# הריצות עם price_score הנמוך ביותר, תרחיש אחד לכל seed
def lowest_runs(runs: list[tuple[object, dict]], count: int) -> list[tuple[float, object, dict]]:
    """The 'count' runs with the lowest price_score, at most one per scenario."""
    scored = [(price_score(run.outputs, ref)["score"], run, ref) for run, ref in runs]
    picked, seeds = [], set()
    for score, run, ref in sorted([s for s in scored if s[0] is not None], key=lambda item: item[0]):
        if run.inputs["seed"] not in seeds and len(picked) < count:
            picked.append((score, run, ref))
            seeds.add(run.inputs["seed"])
    return picked


# 9 הסימולציות המלאות (עם תמליל) של ריצה אחת, מצמתי negotiate ב-trace
def simulations(client, name: str, run) -> list[dict]:
    """Full SimResults of one run, read from its 'negotiate' child runs."""
    children = client.list_runs(project_name=name, trace_id=run.trace_id, filter='eq(name, "negotiate")')
    return [r for child in children for r in (child.outputs or {}).get("sim_results", [])]


# הדפסת משא ומתן אחד סבב אחר סבב
def print_transcript(sim: dict) -> None:
    """Supplier and buyer offers per round, with the buyer's message and rationale."""
    final = offer_text(sim["final"]) if sim.get("final") else "-"
    print(f"   style {sim['style']}, {sim['outcome']}, reason {sim.get('no_deal_reason')}, rounds {sim['rounds']}, final {final}")
    for entry in sim["transcript"]:
        offers = " | ".join(offer_text(o) for o in entry["offers"]) or "-"
        print(f"   R{entry['round']} {entry['speaker']:<6} {offers}")
        if entry["speaker"] == "buyer":
            print(f"      message:   {entry['message']}")
            print(f"      rationale: {entry['rationale']}")


# כותרת לתרחיש: seed, קטגוריה, טווח ויעד, ושורה לכל סימולציית בסיס
def print_header(run, ref: dict, extra: str = "") -> None:
    """One header line for the scenario and one line per base simulation."""
    buyer = run.inputs["buyer"]
    print(f"\nseed {run.inputs['seed']} | {ref['category']}{extra} | zopa {ref['zopa_low']}..{ref['zopa_high']} | "
          f"target/unit {round(buyer['target_total'] / buyer['quantity'], 2)}")
    for s in run.outputs["sims"]:
        if s["variant"] == "base":
            print(f"   base {s['style']:<8} {s['outcome']:<7} price {s['unit_price']}  first offer {s['first_offer_price']}")


# מצב 1: התרחישים עם הציון הנמוך, ועסקת הבסיס היקרה בכל אחד
def show_lowest(client, name: str, runs: list, count: int) -> None:
    """Print the worst base deal of each of the lowest-scoring scenarios."""
    for score, run, ref in lowest_runs(runs, count):
        print_header(run, ref, f" | price_score {score:.3f}")
        deals = [s for s in simulations(client, name, run) if s["variant"] == "base" and s["outcome"] == "deal"]
        price = lambda s: s["final"]["unit_price"] if isinstance(s["final"], dict) else s["final"].unit_price
        if deals:
            print_transcript(max(deals, key=price))


# מצב 2: סימולציות בסיס שלא נסגרו בתרחישים שיש בהם טווח: ספירה לפי סיבה, ותמליל לדוגמה
def show_no_deals(client, name: str, runs: list, count: int) -> None:
    """Count base no-deals where a ZOPA exists, by reason and style, and print 'count' of them (one per scenario)."""
    by_style, examples, seeds = Counter(), [], set()
    for run, ref in runs:
        if not ref["zopa_exists"]:
            continue
        for s in run.outputs["sims"]:
            if s["variant"] == "base" and s["outcome"] == "no_deal":
                by_style[s["style"]] += 1
        if run.inputs["seed"] not in seeds and any(s["variant"] == "base" and s["outcome"] == "no_deal"
                                                   for s in run.outputs["sims"]) and len(examples) < count:
            examples.append((run, ref))
            seeds.add(run.inputs["seed"])
    reasons = Counter()
    for run, ref in examples:
        print_header(run, ref)
        for sim in simulations(client, name, run):
            if sim["variant"] == "base" and sim["outcome"] == "no_deal":
                reasons[sim.get("no_deal_reason")] += 1
                print_transcript(sim)
    print(f"\nbase no-deals with a ZOPA, by style (all runs): {dict(by_style)}")
    print(f"reasons in the examples above: {dict(reasons)}")


# נקודת הכניסה: שם הניסוי, מצב ומספר התרחישים להצגה
def main() -> None:
    load_dotenv()
    from langsmith import Client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", help="experiment name, as shown in LangSmith")
    parser.add_argument("--count", type=int, default=3, help="number of scenarios to show")
    parser.add_argument("--no-deals", action="store_true", help="show base no-deals where a ZOPA exists")
    args = parser.parse_args()
    client = Client()
    runs = scored_runs(client, args.experiment)
    if args.no_deals:
        show_no_deals(client, args.experiment, runs, args.count)
    else:
        show_lowest(client, args.experiment, runs, args.count)


if __name__ == "__main__":
    main()
