"""VBM wiring: connects the application ports to the OpenAI gateways (the composition root)."""

from vbm.adapters.llm_gateways import LLMBuyerDecider, LLMReportWriter, LLMRequestParser, LLMTranslator
from vbm.application.ports import BuyerDecider, Ports, Translator
from vbm.infrastructure.llm import buyer_model, parser_model, report_model, translate_model


# הקונה האמיתי: פרומפט לפי גרסה + מודל OpenAI
def default_buyer_decider() -> BuyerDecider:
    """BuyerDecider backed by the OpenAI buyer model."""
    return LLMBuyerDecider(buyer_model)


# כל ה-ports של הגרף הראשי, מחוברים למודלים של OpenAI
def default_ports() -> Ports:
    """Parser, buyer and report writer backed by OpenAI (models are created on first use)."""
    return Ports(parser=LLMRequestParser(parser_model), buyer_decider=default_buyer_decider(),
                 report_writer=LLMReportWriter(report_model))


# המתרגם האמיתי, לתצוגה ב-CLI וב-Streamlit
def default_translator() -> Translator:
    """Translator backed by the OpenAI translation model."""
    return LLMTranslator(translate_model)
