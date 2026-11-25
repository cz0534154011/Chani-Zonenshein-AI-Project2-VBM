"""VBM ports: what the use cases need from a language model, without knowing which model or library."""

from dataclasses import dataclass
from typing import Protocol

from vbm.application.dto import BuyerDecision, ParsedRequest
from vbm.domain.schemas import BuyerTerms, TranscriptEntry


# מפענח הבקשה החופשית
class RequestParser(Protocol):
    def parse(self, raw_request: str) -> ParsedRequest | None:
        """Structured reading of the free-text request, or None if it could not be parsed."""
        ...


# מקבל ההחלטות של הקונה; מקבל רק נתוני קונה, תמליל ומשוב - אף פעם לא את הספק
class BuyerDecider(Protocol):
    def decide(self, buyer: BuyerTerms, transcript: list[TranscriptEntry], guardrail_feedback: str | None,
               round_no: int, max_rounds: int, prompt_version: str) -> BuyerDecision | None:
        """The buyer's decision for this turn, or None if the output was invalid."""
        ...


# כותב הדוח מתוך ReportData בלבד
class ReportWriter(Protocol):
    def write(self, report_data: dict, unverified: list[str]) -> str:
        """Markdown report phrased from report_data; unverified = numbers rejected in the previous attempt."""
        ...


# מתרגם לעברית, לתצוגה בלבד
class Translator(Protocol):
    def translate(self, texts: list[str]) -> list[str]:
        """Hebrew translation of each line; a line that was not translated stays as it is."""
        ...


# כל ה-ports שהגרף הראשי צריך
@dataclass(frozen=True)
class Ports:
    parser: RequestParser
    buyer_decider: BuyerDecider
    report_writer: ReportWriter
