"""Print the negotiations behind the lowest price scores of an experiment in LangSmith (no model calls)."""

import argparse

from dotenv import load_dotenv

from vbm.config import DATASET_NAME
from vbm.evaluators import price_score


# ערך של שדה בהצעה, גם כשההצעה נשמרה כמילון וגם כאובייקט
def offer_text(offer) -> str:
    """'price / days / terms' for an offer saved as a dict or as an object."""
    get = offer.get if isinstance(offer, dict) else lambda k: getattr(offer, k, None)
    return f"{get('unit_price')} / {get('delivery_days')}d / {get('payment_terms')}"


# הריצות של הניסוי עם price_score, מהנמוך לגבוה, תרחיש אחד לכל seed
def lowest_runs(client, name: str, count: int) -> list[tuple[float, object, dict]]:
    """The 'count' root runs with the lowest price_score, at most one per scenario."""
    references = {e.id: e.outputs for e in client.list_examples(dataset_name=DATASET_NAME)}
    scored = []
    for run in client.list_runs(project_name=name, is_root=True):
        if not run.reference_example_id or not run.outputs:
            continue
        score = price_score(run.outputs, references[run.reference_example_id])["score"]
        if score is not None:
            scored.append((score, run, references[run.reference_example_id]))
    picked, seeds = [], set()
    for score, run, ref in sorted(scored, key=lambda item: item[0]):
        if run.inputs["seed"] not in seeds and len(picked) < count:
            picked.append((score, run, ref))
            seeds.add(run.inputs["seed"])
    return picked


# התמליל של סימולציית הבסיס עם המחיר הגבוה ביותר בריצה אחת
def print_negotiation(client, name: str, run) -> None:
    """Find the 'negotiate' child runs of one trace and print the worst base deal round by round."""
    children = list(client.list_runs(project_name=name, trace_id=run.trace_id, filter='eq(name, "negotiate")'))
    results = [r for child in children for r in (child.outputs or {}).get("sim_results", [])]
    base = [r for r in results if r.get("variant") == "base" and r.get("outcome") == "deal"]
    if not base:
        print("   (no base deal found in child runs)")
        return
    worst = max(base, key=lambda r: (r["final"]["unit_price"] if isinstance(r["final"], dict) else r["final"].unit_price))
    print(f"   style {worst['style']}, rounds {worst['rounds']}, final {offer_text(worst['final'])}")
    for entry in worst["transcript"]:
        offers = " | ".join(offer_text(o) for o in entry["offers"]) or "-"
        print(f"   R{entry['round']} {entry['speaker']:<6} {offers}")
        if entry["speaker"] == "buyer":
            print(f"      message:   {entry['message']}")
            print(f"      rationale: {entry['rationale']}")


# נקודת הכניסה: שם הניסוי ומספר התרחישים להצגה
def main() -> None:
    load_dotenv()
    from langsmith import Client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", help="experiment name, as shown in LangSmith")
    parser.add_argument("--count", type=int, default=3, help="number of scenarios to show")
    args = parser.parse_args()
    client = Client()
    for score, run, ref in lowest_runs(client, args.experiment, args.count):
        buyer = run.inputs["buyer"]
        print(f"\nseed {run.inputs['seed']} | {ref['category']} | price_score {score:.3f} | "
              f"zopa {ref['zopa_low']}..{ref['zopa_high']} | target/unit {round(buyer['target_total'] / buyer['quantity'], 2)}")
        for s in run.outputs["sims"]:
            if s["variant"] == "base":
                print(f"   base {s['style']:<8} {s['outcome']:<7} price {s['unit_price']}  first offer {s['first_offer_price']}")
        print_negotiation(client, args.experiment, run)


if __name__ == "__main__":
    main()
