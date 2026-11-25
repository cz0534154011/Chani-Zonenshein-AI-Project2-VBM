"""Tests for the dataset builder: the category mix, answers computed in code, determinism (no LangSmith)."""

from collections import Counter

from vbm.config import DATASET_QUOTAS
from vbm.dataset import analytic_concession, build_dataset, build_example
from vbm.economics import classify_zopa, compute_zopa
from vbm.scenario_generator import profile_for_style


def test_mix_matches_the_quotas():
    examples = build_dataset()
    assert len(examples) == 18
    assert Counter(e["outputs"]["category"] for e in examples) == Counter(DATASET_QUOTAS)


def test_outputs_recompute_from_the_inputs():
    for e in build_dataset():
        buyer, limits = e["inputs"]["buyer"], e["inputs"]["seller_profiles"]
        for style in ("tough", "balanced", "flexible"):
            zopa = compute_zopa(buyer, profile_for_style(limits, style))
            assert {k: e["outputs"][k] for k in zopa} == zopa
        assert e["outputs"]["category"] == classify_zopa(zopa)
        assert e["outputs"]["decisive_concession"] == analytic_concession(buyer, limits)


def test_build_is_deterministic():
    assert build_dataset() == build_dataset() and build_example(7) == build_example(7)


def test_analytic_concession_cases():
    buyer = {"product": "x", "quantity": 100, "max_budget_total": 40000, "target_total": 30000,
             "deadline_days": 30, "preferred_days": 15, "preferred_terms": "net60", "flexible_on": []}
    limits = {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14}
    assert analytic_concession(buyer, limits) == "delivery"  # standard delivery removes the 4% fast factor
    assert analytic_concession({**buyer, "preferred_days": 30}, limits) == "payment"  # advance saves 2%
    assert analytic_concession({**buyer, "preferred_days": 30, "preferred_terms": "advance"}, limits) == "none"
    assert analytic_concession({**buyer, "preferred_days": 10}, limits) == "delivery"  # opens a ZOPA
