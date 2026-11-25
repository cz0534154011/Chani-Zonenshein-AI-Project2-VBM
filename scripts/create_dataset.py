"""Build the 18-scenario dataset, freeze it in data/dataset.json and upload it to LangSmith (idempotent)."""

import json
from pathlib import Path

from dotenv import load_dotenv

from vbm.infrastructure.evaluation.dataset import build_dataset
from vbm.infrastructure.settings import DATASET_NAME

DATA_FILE = Path("data/dataset.json")
DESCRIPTION = "VBM: 18 purchase scenarios (6 wide, 5 narrow, 4 no ZOPA price, 3 no ZOPA delivery); answers computed in code."


# הקובץ המקומי: נכתב בפעם הראשונה; אם קיים ושונה - עוצרים, כי הדאטהסט קפוא
def freeze_locally(examples: list[dict]) -> None:
    """Write data/dataset.json, or check that the existing file has exactly these examples."""
    text = json.dumps(examples, ensure_ascii=False, indent=2)
    if DATA_FILE.exists():
        if json.loads(DATA_FILE.read_text(encoding="utf-8")) != examples:
            raise SystemExit(f"{DATA_FILE} differs from the generated dataset; the dataset is frozen, nothing written.")
        print(f"{DATA_FILE}: unchanged.")
        return
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(text + "\n", encoding="utf-8")
    print(f"{DATA_FILE}: written.")


# העלאה ל-LangSmith: יוצרים פעם אחת; אם קיים - בודקים שהתוכן זהה ולא דורסים
def upload(examples: list[dict]) -> None:
    """Create the LangSmith dataset once; if it exists, verify it holds the same examples."""
    from langsmith import Client
    client = Client()
    if client.has_dataset(dataset_name=DATASET_NAME):
        remote = [{"inputs": e.inputs, "outputs": e.outputs} for e in client.list_examples(dataset_name=DATASET_NAME)]
        key = lambda e: json.dumps(e, sort_keys=True)
        if sorted(map(key, remote)) != sorted(map(key, examples)):
            raise SystemExit(f"LangSmith dataset '{DATASET_NAME}' exists with different examples; nothing changed.")
        print(f"LangSmith dataset '{DATASET_NAME}': already exists, unchanged.")
        return
    dataset = client.create_dataset(DATASET_NAME, description=DESCRIPTION)
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"LangSmith dataset '{DATASET_NAME}': created with {len(examples)} examples.")


# טבלה לבדיקה הידנית
def print_table(examples: list[dict]) -> None:
    """One line per scenario: seed, product, buyer limits, supplier limits and the computed answers."""
    for i, e in enumerate(examples, 1):
        b, s, o = e["inputs"]["buyer"], e["inputs"]["seller_profiles"], e["outputs"]
        print(f"{i:>2}. seed {e['inputs']['seed']:>3} | {b['product']:<17} x{b['quantity']:<5}"
              f" budget/unit {o['zopa_high']:<8} days {b['preferred_days']}/{b['deadline_days']} {b['preferred_terms']:<7}"
              f" | min {s['min_price']:<8} min_days {s['min_days']:<3}"
              f" | {o['category']:<16} low {o['zopa_low']} concession {o['decisive_concession']}")


# נקודת הכניסה: בנייה, הקפאה מקומית, הדפסה והעלאה
def main() -> None:
    load_dotenv()
    examples = build_dataset()
    freeze_locally(examples)
    print_table(examples)
    upload(examples)


if __name__ == "__main__":
    main()
