"""Run one LangSmith experiment on the frozen dataset: the graph with the fixed policy, scored by code evaluators."""

import argparse

from dotenv import load_dotenv

from vbm.config import (DATASET_CATEGORY_ORDER, DATASET_NAME, EXPERIMENT_MAX_CONCURRENCY, EXPERIMENT_REPETITIONS,
                        MODELS, PROMPT_VERSION, PROMPT_VERSIONS, TEMPERATURES)
from vbm.evaluators import EVALUATORS, summary_evaluator, make_target, summary_metrics


# ריצת פיתוח: N תרחישים, לפי סבב על הקטגוריות (5 = אחד מכל קטגוריה ועוד "רחב")
def pick_examples(examples: list, limit: int) -> list:
    """Take scenarios category by category in turn until there are 'limit' of them."""
    queues = {c: [e for e in examples if e.outputs["category"] == c] for c in DATASET_CATEGORY_ORDER}
    picked = []
    while len(picked) < limit and any(queues.values()):
        for category in DATASET_CATEGORY_ORDER:
            if queues[category] and len(picked) < limit:
                picked.append(queues[category].pop(0))
    return picked


# קריאת הפרמטרים משורת הפקודה
def parse_args() -> argparse.Namespace:
    """--prefix, --prompt-version, --reps and --limit (for a short development run)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default=None, help="experiment name prefix in LangSmith (default: exp-<prompt version>)")
    parser.add_argument("--prompt-version", choices=PROMPT_VERSIONS, default=PROMPT_VERSION, help="buyer prompt version")
    parser.add_argument("--reps", type=int, default=EXPERIMENT_REPETITIONS, help="repetitions per scenario")
    parser.add_argument("--limit", type=int, default=None, help="number of scenarios (default: all 18)")
    return parser.parse_args()


# נקודת הכניסה: בוחרים תרחישים, מריצים evaluate ומדפיסים את המדדים המסכמים
def main() -> None:
    load_dotenv()
    from langsmith import Client
    args = parse_args()
    client = Client()
    examples = sorted(client.list_examples(dataset_name=DATASET_NAME), key=lambda e: e.inputs["seed"])
    if args.limit:
        examples = pick_examples(examples, args.limit)
    print(f"prompt {args.prompt_version}: {len(examples)} scenarios x {args.reps} repetitions = {len(examples) * args.reps} runs "
          f"({len(examples) * args.reps * 9} simulations).")
    results = client.evaluate(
        make_target(args.prompt_version), data=examples, evaluators=EVALUATORS, summary_evaluators=[summary_evaluator],
        experiment_prefix=args.prefix or f"exp-{args.prompt_version}", num_repetitions=args.reps, max_concurrency=EXPERIMENT_MAX_CONCURRENCY,
        metadata={"prompt_version": args.prompt_version, "buyer_model": MODELS["buyer"], "buyer_temperature": TEMPERATURES["buyer"],
                  "report_model": MODELS["report"], "dataset": DATASET_NAME},
    )
    rows = list(results)
    metrics = summary_metrics([r["run"].outputs for r in rows], [r["example"].outputs for r in rows])
    print(f"\nExperiment: {results.experiment_name}")
    for key, value in metrics.items():
        print(f"  {key:<22} {value}")


if __name__ == "__main__":
    main()
