"""Full runs of the main graph with fake parser, buyer and report writer (no model calls)."""

from dataclasses import replace

import pytest
from langgraph.types import Command

from vbm.adapters.llm_gateways import LLMBuyerDecider, LLMReportWriter, LLMRequestParser
from vbm.application.dto import BuyerDecision, ParsedRequest
from vbm.application.ports import Ports
from vbm.domain.schemas import Offer
from vbm.infrastructure.workflow.graph import build_graph, memory_checkpointer

PARSED = ParsedRequest(product="office chair", quantity=500, max_budget_total=210000, target_total=160000,
                       deadline_days=30, preferred_days=None, preferred_terms="net60",
                       known_list_price=None, known_standard_days=None, notes=["הנחתי שהמועד הוא 30 ימים."])
LIMITS = {"list_price": 480, "min_price": 330, "standard_days": 21, "min_days": 14}
BUYER = {"product": "office chair", "quantity": 500, "max_budget_total": 210000,
         "target_total": 160000, "deadline_days": 30, "preferred_terms": "net60"}


class Fixed:
    """Stands in for a model: always returns the same value."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.value


class SteadyBuyer:
    """Counters at 400 every round and walks away on the final turn (stateless, safe in parallel)."""

    def invoke(self, messages):
        if "final offer" in messages[-1].content.splitlines()[-1]:
            return BuyerDecision(action="walk_away", offer=None, message="No deal.", rationale="scripted")
        offer = Offer(unit_price=400, delivery_days=30, payment_terms="net60")
        return BuyerDecision(action="counter", offer=offer, message="I can offer 400 per unit, delivery in 30 days, net 60.",
                             rationale="scripted")


@pytest.fixture
def fakes():
    parser, writer = Fixed(PARSED), Fixed("## דוח\nאלה סימולציות בלבד.")
    ports = Ports(parser=LLMRequestParser(lambda: parser), buyer_decider=LLMBuyerDecider(lambda: SteadyBuyer()),
                  report_writer=LLMReportWriter(lambda: writer))
    return parser, writer, ports


def pending(graph, config):
    return graph.get_state(config).interrupts[0].value


def test_interactive_run_with_both_stops_and_one_what_if(fakes):
    parser, writer, ports = fakes
    graph = build_graph(memory_checkpointer(), ports)
    config = {"configurable": {"thread_id": "t1"}}
    graph.invoke({"raw_request": "500 כיסאות משרדיים", "seed": 7, "max_rounds": 8}, config)
    assert pending(graph, config)["type"] == "confirm_terms"

    graph.invoke(Command(resume={"action": "fix", "text": "התקציב 210 אלף"}), config)
    assert parser.calls == 2 and pending(graph, config)["type"] == "confirm_terms"

    graph.invoke(Command(resume={"action": "confirm"}), config)
    first = pending(graph, config)
    assert first["type"] == "findings" and len(graph.get_state(config).values["sim_results"]) == 9

    graph.invoke(Command(resume={"action": "change_terms", "changes": {"max_budget_total": 220000}}), config)
    state = graph.get_state(config).values
    assert state["batch_id"] == 2 and len(state["sim_results"]) == 18
    assert state["buyer"]["max_budget_total"] == 220000

    final = graph.invoke(Command(resume={"action": "report"}), config)
    assert final["report_ok"] and not final["report_is_fallback"] and writer.calls == 1
    assert set(final["debrief"]["limits"]) == {"list_price", "min_price", "standard_days", "min_days"}


def test_invalid_what_if_answer_stops_again(fakes):
    graph = build_graph(memory_checkpointer(), fakes[2])
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"buyer": BUYER, "seller_profiles": LIMITS, "max_rounds": 8}, config)
    graph.invoke(Command(resume={"action": "change_terms", "changes": {"target_total": 999999}}), config)
    again = pending(graph, config)
    assert again["type"] == "findings" and "target_total" in again["error"]


def test_structured_input_skips_parsing_and_runs_nine_simulations(fakes):
    parser, _, ports = fakes
    graph = build_graph(memory_checkpointer(), ports)
    config = {"configurable": {"thread_id": "t3"}}
    graph.invoke({"buyer": BUYER, "seller_profiles": LIMITS, "max_rounds": 8}, config)
    state = graph.get_state(config).values
    assert parser.calls == 0 and len(state["sim_results"]) == 9
    assert state["report_data"]["feasibility"] == {"tough": True, "balanced": True, "flexible": True}


def test_unverified_report_falls_back_after_three_attempts(fakes):
    writer = Fixed("המחיר הצפוי הוא 123.45 ליחידה.")
    graph = build_graph(memory_checkpointer(), replace(fakes[2], report_writer=LLMReportWriter(lambda: writer)))
    config = {"configurable": {"thread_id": "t4"}}
    graph.invoke({"buyer": BUYER, "seller_profiles": LIMITS, "max_rounds": 8}, config)
    final = graph.invoke(Command(resume={"action": "report"}), config)
    assert writer.calls == 3 and final["report_is_fallback"] and not final["report_ok"]
    assert final["report_text"].startswith("> דוח חלופי")


def test_seller_styles_limits_the_simulations(fakes):
    graph = build_graph(memory_checkpointer(), fakes[2])
    config = {"configurable": {"thread_id": "t5"}}
    graph.invoke({"buyer": BUYER, "seller_profiles": LIMITS, "seller_styles": ["tough"], "max_rounds": 8}, config)
    results = graph.get_state(config).values["sim_results"]
    assert len(results) == 3 and {r["style"] for r in results} == {"tough"}


def test_what_if_keeps_the_drawn_supplier(fakes):
    graph = build_graph(memory_checkpointer(), fakes[2])
    config = {"configurable": {"thread_id": "t6"}}
    graph.invoke({"buyer": BUYER, "seed": 1, "max_rounds": 8}, config)
    before = graph.get_state(config).values["sim_specs"][0]["seller"]
    graph.invoke(Command(resume={"action": "change_terms", "changes": {"target_total": 120000}}), config)
    state = graph.get_state(config).values
    assert state["batch_id"] == 2 and state["sim_specs"][0]["seller"] == before

    graph.invoke(Command(resume={"action": "change_seller", "known": {"min_days": 10}}), config)
    after = graph.get_state(config).values["sim_specs"][0]["seller"]
    assert after == {**before, "min_days": 10}
