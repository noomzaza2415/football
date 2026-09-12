"""Odds helpers: decimal odds <-> probability, vig removal and edge/value.

Bookmaker prices are quoted as decimal odds (also called European odds). A
price of 1.80 means a winning 1 unit stake returns 1.80 units in total. The
implied probability of that price is simply 1 / 1.80 = 55.6%.

The implied probabilities of the two sides of a market always add up to more
than 100%. That surplus is the bookmaker margin, usually called the vig or
overround. Comparing a model against the raw implied probabilities therefore
flatters the model, so the functions below can strip the margin before the
comparison is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MIN_DECIMAL_ODDS = 1.01


class InvalidOddsError(ValueError):
    """Raised for odds that cannot represent a real price."""


def implied_probability(decimal_odds: float) -> float:
    """Convert decimal odds into the probability they imply.

    ``implied_probability(2.0) == 0.5``. Includes the bookmaker margin.
    """
    if decimal_odds is None or decimal_odds < MIN_DECIMAL_ODDS:
        raise InvalidOddsError(f"decimal odds must be >= {MIN_DECIMAL_ODDS}, got {decimal_odds!r}")
    return 1.0 / float(decimal_odds)


def fair_odds(probability: float) -> float | None:
    """The break-even decimal price for a probability, or None if impossible."""
    if probability is None or probability <= 0.0 or probability > 1.0:
        return None
    return 1.0 / float(probability)


def overround(decimal_odds: Sequence[float]) -> float:
    """Total implied probability of a market. 1.05 means a 5% margin."""
    if not decimal_odds:
        raise InvalidOddsError("cannot compute overround of an empty market")
    return sum(implied_probability(price) for price in decimal_odds)


def bookmaker_margin(decimal_odds: Sequence[float]) -> float:
    """The bookmaker margin as a fraction, e.g. 0.05 for a 5% book."""
    return overround(decimal_odds) - 1.0


def remove_vig(decimal_odds: Sequence[float]) -> list[float]:
    """Strip the margin from a market, returning true probabilities.

    Uses proportional (multiplicative) normalisation: every implied
    probability is divided by the overround so the set sums to 1. This is the
    standard first approximation and is what the dashboard shows next to the
    model numbers.
    """
    probabilities = [implied_probability(price) for price in decimal_odds]
    book = sum(probabilities)
    if book <= 0:
        raise InvalidOddsError("degenerate market")
    return [p / book for p in probabilities]


@dataclass(frozen=True)
class ValueAssessment:
    """How far the model sits from the market on one selection."""

    selection: str
    decimal_odds: float
    market_probability: float
    fair_market_probability: float
    model_probability: float

    @property
    def edge(self) -> float:
        """Model probability minus the vig-free market probability."""
        return self.model_probability - self.fair_market_probability

    @property
    def expected_value(self) -> float:
        """EV per 1 unit staked at these odds, using the model probability.

        A positive number means the model rates the bet as profitable. It is
        only as trustworthy as the model that produced the probability.
        """
        return self.model_probability * (self.decimal_odds - 1.0) - (1.0 - self.model_probability)

    @property
    def is_value(self) -> bool:
        return self.expected_value > 0.0


def assess_value(
    selection: str,
    decimal_odds: float,
    model_probability: float,
    *,
    opposite_odds: float | None = None,
) -> ValueAssessment:
    """Compare one model probability with one market price.

    When ``opposite_odds`` is supplied the margin is removed across the two
    legs, which makes ``edge`` an honest comparison. Without it the fair
    probability falls back to the raw implied probability.
    """
    if not 0.0 <= model_probability <= 1.0:
        raise ValueError(f"model probability out of range: {model_probability!r}")

    market_probability = implied_probability(decimal_odds)
    if opposite_odds is not None:
        fair_probability = remove_vig([decimal_odds, opposite_odds])[0]
    else:
        fair_probability = market_probability

    return ValueAssessment(
        selection=selection,
        decimal_odds=float(decimal_odds),
        market_probability=market_probability,
        fair_market_probability=fair_probability,
        model_probability=float(model_probability),
    )


def kelly_fraction(model_probability: float, decimal_odds: float, *, cap: float = 0.05) -> float:
    """Kelly stake as a fraction of bankroll, capped and never negative.

    Included for completeness of the analysis view. Full Kelly is far too
    aggressive for a model fitted on a few hundred matches, so the result is
    capped at ``cap`` and the UI presents it as an illustration only.
    """
    if decimal_odds < MIN_DECIMAL_ODDS:
        raise InvalidOddsError(f"decimal odds must be >= {MIN_DECIMAL_ODDS}")
    b = decimal_odds - 1.0
    q = 1.0 - model_probability
    raw = (model_probability * b - q) / b
    return float(min(max(raw, 0.0), cap))
