"""Compare the summary metrics of experiments already in LangSmith (no model calls)."""

import argparse

from dotenv import load_dotenv

from vbm.config import DATASET_NAME
from vbm.evaluators import summary_metrics


# המדדים המסכמים של ניסוי אחד, מחושבים מחדש מהריצות השמורות ב-LangSmith
def experiment_metrics(client, name: str, references: dict) -> tuple[dict, int]:
    """Summary metrics of one experiment and its number of root runs."""
    runs = [r for r in client.list_runs(project_name=name, is_root=True) if r.reference_example_id]
    outputs = [r.outputs for r in runs]
    refs = [references[r.reference_example_id] for r in runs]
    return summary_metrics(outputs, refs), len(runs)


# טבלה: מדד, ערך בכל ניסוי, וההפרש של כל ניסוי מהראשון
def print_table(names: list[str], results: list[tuple[dict, int]]) -> None:
    """Print one row per metric, one column per experiment, and the difference from the first experiment."""
    print(f"{'metric':<22}" + "".join(f"{n[-30:]:>32}" for n in names) + "".join(f"{'diff ' + str(i + 1):>10}" for i in range(1, len(names))))
    print(f"{'runs':<22}" + "".join(f"{count:>32}" for _, count in results))
    for key in results[0][0]:
        values = [metrics[key] for metrics, _ in results]
        cells = "".join(f"{str(v):>32}" for v in values)
        diffs = "".join(f"{(round(v - values[0], 4) if v is not None and values[0] is not None else '-'):>10}" for v in values[1:])
        print(f"{key:<22}{cells}{diffs}")


# נקודת הכניסה: שמות הניסויים משורת הפקודה
def main() -> None:
    load_dotenv()
    from langsmith import Client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiments", nargs="+", help="two or more experiment names, as shown in LangSmith")
    names = parser.parse_args().experiments
    client = Client()
    references = {e.id: e.outputs for e in client.list_examples(dataset_name=DATASET_NAME)}
    print_table(names, [experiment_metrics(client, name, references) for name in names])


if __name__ == "__main__":
    main()
