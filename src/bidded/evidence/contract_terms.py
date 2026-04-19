from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

NumberValue = int | float

_NUMBER_PATTERN = r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[,.]\d+)?"
_MONEY_RE = re.compile(
    rf"\b(?P<number>{_NUMBER_PATTERN})\s*"
    r"(?P<unit>MSEK|Mkr|mnkr|SEK|kr|kronor|miljoner\s+kronor)\b",
    re.IGNORECASE,
)
_RECURRENCE_OR_CAP_RE = re.compile(
    r"\bper\s+"
    r"(?P<unit>week|month|year|claim|vecka|månad|manad|år|ar|anspråk|ansprak|krav)\b",
    re.IGNORECASE,
)
_PAREN_DAY_DEADLINE_RE = re.compile(
    r"\b(?P<word>[A-Za-zÅÄÖåäö]+)\s*\(\s*(?P<days>\d{1,4})\s*\)\s*"
    r"(?P<unit>days?|dagar|dag)\b",
    re.IGNORECASE,
)
_DIGIT_DAY_DEADLINE_RE = re.compile(
    r"\b(?P<days>\d{1,4})\s*(?P<unit>days?|dagar|dag)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MoneyAmountTerm:
    raw_text: str
    amount: NumberValue
    currency: str
    unit: str
    normalized_amount_sek: NumberValue
    context: str

    def as_metadata(self) -> dict[str, str | NumberValue]:
        return {
            "raw_text": self.raw_text,
            "amount": self.amount,
            "currency": self.currency,
            "unit": self.unit,
            "normalized_amount_sek": self.normalized_amount_sek,
            "context": self.context,
        }


@dataclass(frozen=True)
class RecurrenceOrCapTerm:
    raw_text: str
    normalized_unit: str
    scope_type: str

    def as_metadata(self) -> dict[str, str]:
        return {
            "raw_text": self.raw_text,
            "normalized_unit": self.normalized_unit,
            "scope_type": self.scope_type,
        }


@dataclass(frozen=True)
class DayDeadlineTerm:
    raw_text: str
    days: int
    unit: str
    context: str

    def as_metadata(self) -> dict[str, str | int]:
        return {
            "raw_text": self.raw_text,
            "days": self.days,
            "unit": self.unit,
            "context": self.context,
        }


@dataclass(frozen=True)
class ExtractedContractTerms:
    money_amounts: tuple[MoneyAmountTerm, ...] = ()
    recurrence_or_cap_phrases: tuple[RecurrenceOrCapTerm, ...] = ()
    day_deadlines: tuple[DayDeadlineTerm, ...] = ()

    @property
    def has_terms(self) -> bool:
        return bool(
            self.money_amounts
            or self.recurrence_or_cap_phrases
            or self.day_deadlines
        )

    def as_metadata(self) -> dict[str, list[dict[str, object]]]:
        return {
            "money_amounts": [
                term.as_metadata() for term in self.money_amounts
            ],
            "recurrence_or_cap_phrases": [
                term.as_metadata() for term in self.recurrence_or_cap_phrases
            ],
            "day_deadlines": [
                term.as_metadata() for term in self.day_deadlines
            ],
        }


def extract_contract_terms(text: str) -> ExtractedContractTerms:
    """Extract deterministic numeric/timing facts from a tender clause excerpt."""

    return ExtractedContractTerms(
        money_amounts=_extract_money_amounts(text),
        recurrence_or_cap_phrases=_extract_recurrence_or_cap_phrases(text),
        day_deadlines=_extract_day_deadlines(text),
    )


def _extract_money_amounts(text: str) -> tuple[MoneyAmountTerm, ...]:
    terms: list[MoneyAmountTerm] = []
    context = _money_context(text)
    for match in _MONEY_RE.finditer(text):
        amount = _parse_decimal(match.group("number"))
        unit = _canonical_money_unit(match.group("unit"))
        normalized_amount = amount * _money_unit_multiplier(unit)
        terms.append(
            MoneyAmountTerm(
                raw_text=match.group(0),
                amount=_metadata_number(amount),
                currency="SEK",
                unit=unit,
                normalized_amount_sek=_metadata_number(normalized_amount),
                context=context,
            )
        )
    return tuple(terms)


def _extract_recurrence_or_cap_phrases(
    text: str,
) -> tuple[RecurrenceOrCapTerm, ...]:
    terms: list[RecurrenceOrCapTerm] = []
    for match in _RECURRENCE_OR_CAP_RE.finditer(text):
        normalized_unit = _normalized_recurrence_unit(match.group("unit"))
        scope_type = "claim" if normalized_unit == "claim" else "period"
        terms.append(
            RecurrenceOrCapTerm(
                raw_text=match.group(0),
                normalized_unit=normalized_unit,
                scope_type=scope_type,
            )
        )
    return tuple(terms)


def _extract_day_deadlines(text: str) -> tuple[DayDeadlineTerm, ...]:
    terms: list[DayDeadlineTerm] = []
    context = _day_deadline_context(text)
    consumed_spans: set[tuple[int, int]] = set()
    for match in _PAREN_DAY_DEADLINE_RE.finditer(text):
        consumed_spans.add(match.span())
        terms.append(
            DayDeadlineTerm(
                raw_text=match.group(0),
                days=int(match.group("days")),
                unit="days",
                context=context,
            )
        )

    for match in _DIGIT_DAY_DEADLINE_RE.finditer(text):
        if any(
            consumed_start <= match.start() and match.end() <= consumed_end
            for consumed_start, consumed_end in consumed_spans
        ):
            continue
        terms.append(
            DayDeadlineTerm(
                raw_text=match.group(0),
                days=int(match.group("days")),
                unit="days",
                context=context,
            )
        )
    return tuple(terms)


def _parse_decimal(raw_number: str) -> Decimal:
    normalized = (
        raw_number.replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(",", ".")
    )
    return Decimal(normalized)


def _metadata_number(value: Decimal) -> NumberValue:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _canonical_money_unit(raw_unit: str) -> str:
    normalized_unit = _normalize_for_matching(raw_unit)
    if normalized_unit in {"msek", "mkr", "mnkr", "miljoner kronor"}:
        return "Mkr"
    return "SEK"


def _money_unit_multiplier(unit: str) -> Decimal:
    if unit == "Mkr":
        return Decimal("1000000")
    return Decimal("1")


def _normalized_recurrence_unit(raw_unit: str) -> str:
    normalized_unit = _normalize_for_matching(raw_unit)
    if normalized_unit in {"vecka", "week"}:
        return "week"
    if normalized_unit in {"manad", "month"}:
        return "month"
    if normalized_unit in {"ar", "year"}:
        return "year"
    return "claim"


def _money_context(text: str) -> str:
    normalized_text = _normalize_for_matching(text)
    if any(
        marker in normalized_text
        for marker in (
            "penalty",
            "penalties",
            "liquidated damages",
            "vite",
            "avtalsvite",
            "forseningsvite",
        )
    ):
        return "penalty_amount"
    if any(
        marker in normalized_text
        for marker in (
            "liability",
            "liability cap",
            "capped",
            "ansvar",
            "begrans",
        )
    ):
        return "liability_cap"
    if any(
        marker in normalized_text
        for marker in ("payment", "invoice", "betalning", "faktura")
    ):
        return "payment_amount"
    return "contract_amount"


def _day_deadline_context(text: str) -> str:
    normalized_text = _normalize_for_matching(text)
    if any(
        marker in normalized_text
        for marker in ("payment", "invoice", "betalning", "faktura")
    ):
        return "payment_deadline"
    if any(
        marker in normalized_text
        for marker in ("submission", "deadline", "anbud", "sista dag")
    ):
        return "submission_deadline"
    return "deadline"


def _normalize_for_matching(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_diacritics).strip()


__all__ = [
    "DayDeadlineTerm",
    "ExtractedContractTerms",
    "MoneyAmountTerm",
    "RecurrenceOrCapTerm",
    "extract_contract_terms",
]
