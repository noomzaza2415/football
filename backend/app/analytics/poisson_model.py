"""Poisson-based goal model for Over/Under markets.

The model follows the classic "attack / defense strength relative to league
average" approach:

1. Compute the league's average home goals and average away goals per match.
2. For every team compute four ratios (attack at home, defense at home,
   attack away, defense away) by comparing the team's own averages with the
   league averages.
3. Expected goals for a fixture are

       lambda_home = attack_home(home) * defense_away(away) * league_home_avg
       lambda_away = attack_away(away) * defense_home(home) * league_away_avg

4. Assuming both scorelines are Poisson distributed, the joint probability of
   an exact scoreline is the product of the two marginals. Summing cells of
   that matrix gives Over/Under, total-goals and 1X2 probabilities.

An optional Dixon-Coles low-score correction is supported because the plain
independent-Poisson assumption is known to underrate 0-0 and 1-1 draws.

Nothing in this module talks to the database: everything takes plain numbers
or dataclasses so it can be unit tested in isolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import poisson

from app.analytics.odds import fair_odds

MODEL_VERSION = "poisson-1.2.0"

DEFAULT_MAX_GOALS = 6
DEFAULT_LINES: tuple[float, ...] = (1.5, 2.5, 3.5)

# Clamp strengths so a single freak result (a 7-0 win inside a 6 match sample)
# cannot blow up the expected goals for the next fixture.
MIN_STRENGTH = 0.25
MAX_STRENGTH = 3.0
MIN_LAMBDA = 0.05
MAX_LAMBDA = 6.0


class InsufficientDataError(ValueError):
    """Raised when there are not enough finished matches to fit the model."""


@dataclass(frozen=True)
class MatchResult:
    """A single finished match, the only input the model needs."""

    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals


@dataclass(frozen=True)
class LeagueAverages:
    """Average goals per match in a league, split by venue."""

    home_goals: float
    away_goals: float
    matches: int

    @property
    def total_goals(self) -> float:
        return self.home_goals + self.away_goals


@dataclass(frozen=True)
class TeamStrength:
    """Attack and defense multipliers relative to the league average."""

    team_id: int
    attack_home: float
    defense_home: float
    attack_away: float
    defense_away: float
    matches_home: int = 0
    matches_away: int = 0

    @property
    def matches(self) -> int:
        return self.matches_home + self.matches_away


@dataclass(frozen=True)
class LineProbabilities:
    """Model probabilities for one Over/Under line."""

    line: float
    prob_over: float
    prob_under: float
    prob_push: float = 0.0

    @property
    def fair_odds_over(self) -> float | None:
        return fair_odds(self.prob_over)

    @property
    def fair_odds_under(self) -> float | None:
        return fair_odds(self.prob_under)


@dataclass(frozen=True)
class MatchPrediction:
    """Everything the API needs to describe one fixture."""

    expected_home_goals: float
    expected_away_goals: float
    score_matrix: np.ndarray
    total_goals_distribution: dict[int, float]
    lines: dict[float, LineProbabilities]
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    most_likely_score: tuple[int, int]
    model_version: str = MODEL_VERSION

    @property
    def expected_total_goals(self) -> float:
        return self.expected_home_goals + self.expected_away_goals


# --------------------------------------------------------------------------- #
# Step 1 - league averages
# --------------------------------------------------------------------------- #
def compute_league_averages(matches: Sequence[MatchResult]) -> LeagueAverages:
    """Average goals scored by the home side and by the away side."""
    if not matches:
        raise InsufficientDataError("cannot compute league averages from zero matches")

    home = np.fromiter((m.home_goals for m in matches), dtype=float, count=len(matches))
    away = np.fromiter((m.away_goals for m in matches), dtype=float, count=len(matches))
    return LeagueAverages(
        home_goals=float(home.mean()),
        away_goals=float(away.mean()),
        matches=len(matches),
    )


def _clamp(value: float, low: float, high: float) -> float:
    return float(min(max(value, low), high))


def _safe_ratio(numerator: float, denominator: float, fallback: float = 1.0) -> float:
    if denominator <= 0:
        return fallback
    return numerator / denominator


# --------------------------------------------------------------------------- #
# Step 2a - shrinkage
# --------------------------------------------------------------------------- #
# A raw strength ratio is a mean of a handful of Poisson draws divided by a
# league average, so it carries a lot of estimation noise. Walk-forward testing
# showed that noise costing about as much as the signal earns: the model with
# raw ratios scored worse than the same model with every team forced to average
# strength.
#
# The fix is to pull each ratio back toward 1.0 by an amount that depends on how
# much evidence stands behind it:
#
#     strength = 1 + k * (raw_ratio - 1)        k = n / (n + c)
#
# With k = 1 nothing is shrunk and the old behaviour returns. With k = 0 every
# team is average and the model collapses to the league-average baseline. So the
# tuned model is bounded below by whichever of those two currently scores
# better, which is what makes this change safe rather than speculative.
#
# ``c`` is derived, not tuned. For a role whose league average is L, a mean over
# n Poisson draws has variance L/n, so the ratio's noise variance is 1/(nL). The
# spread actually observed across teams is signal plus noise, so
#
#     signal = variance_observed - mean(1 / (n_i * L))
#     k_i    = signal / (signal + 1 / (n_i * L))   =>   c = 1 / (L * signal)
#
# That is the standard empirical-Bayes result. Deriving ``c`` this way avoids
# picking it from the same backtest used to judge the model, which would be
# exactly the overfitting the walk-forward test exists to prevent.

SHRINKAGE_OFF = 0.0
MIN_TEAMS_FOR_AUTO_SHRINKAGE = 3

#: What ``shrinkage`` accepts: None or 0.0 for off, "auto" to derive it, or an
#: explicit constant in matches.
Shrinkage = float | str | None


def _shrinkage_constant(
    entries: dict[int, tuple[float, int]], denominator: float, mode: Shrinkage
) -> float:
    """The constant ``c`` for one role, in units of matches.

    Returns 0.0 for no shrinkage and ``inf`` when the observed spread is all
    noise, which shrinks every team to exactly average.
    """
    if mode is None:
        return SHRINKAGE_OFF
    if not isinstance(mode, str):
        if mode < 0:
            raise ValueError("shrinkage constant cannot be negative")
        return float(mode)
    if mode != "auto":
        raise ValueError(f"unknown shrinkage mode {mode!r}; use 'auto', a number, or None")

    if len(entries) < MIN_TEAMS_FOR_AUTO_SHRINKAGE or denominator <= 0:
        # Too few teams to estimate a spread; trust nothing.
        return math.inf

    ratios = np.fromiter((ratio for ratio, _ in entries.values()), dtype=float)
    counts = np.fromiter((count for _, count in entries.values()), dtype=float)

    observed_variance = float(ratios.var(ddof=1))
    noise_variance = float(np.mean(1.0 / (counts * denominator)))

    # The observed variance is itself estimated from only ``k`` teams, and a
    # sample variance has a relative standard error of about sqrt(2 / (k - 1)):
    # roughly 82% at four teams, 32% at twenty. Taking the point estimate at
    # face value in a small league therefore invents signal that is not there.
    #
    # The two errors are not symmetric. Overstating the signal under-shrinks and
    # brings back the noisy model this step exists to fix; understating it
    # over-shrinks toward the league average, which is the baseline the model
    # has to beat anyway. So discount the observed variance by one standard
    # error and accept the conservative side.
    teams = len(entries)
    confidence = max(1.0 - math.sqrt(2.0 / (teams - 1)), 0.0)
    signal_variance = observed_variance * confidence - noise_variance

    if signal_variance <= 1e-9:
        # The teams look different only because of small samples.
        return math.inf
    return 1.0 / (denominator * signal_variance)


def _shrink(raw_ratio: float, count: int, constant: float) -> float:
    """Pull one ratio toward 1.0 and clamp the result."""
    if constant <= 0:
        factor = 1.0
    elif math.isinf(constant):
        factor = 0.0
    else:
        factor = count / (count + constant)
    return _clamp(1.0 + factor * (raw_ratio - 1.0), MIN_STRENGTH, MAX_STRENGTH)


# --------------------------------------------------------------------------- #
# Step 2 - team strengths
# --------------------------------------------------------------------------- #
def compute_team_strengths(
    matches: Sequence[MatchResult],
    league: LeagueAverages | None = None,
    *,
    last_n: int | None = 20,
    min_matches: int = 3,
    shrinkage: Shrinkage = None,
) -> dict[int, TeamStrength]:
    """Attack and defense strength for every team appearing in ``matches``.

    ``matches`` must be ordered oldest first. ``last_n`` keeps only the most
    recent N appearances per team so the strengths track current form rather
    than the whole history. A team with fewer than ``min_matches`` games at a
    venue falls back to a neutral 1.0 multiplier for that venue, which makes
    the expected goals collapse to the league average instead of to noise.

    ``shrinkage`` pulls every ratio toward 1.0 in proportion to how thin the
    evidence behind it is. Pass ``"auto"`` to derive the constant from the data,
    a number to set it directly, or ``None`` to use the raw ratios.
    """
    if not matches:
        raise InsufficientDataError("cannot compute team strengths from zero matches")

    league = league or compute_league_averages(matches)

    home_scored: dict[int, list[float]] = {}
    home_conceded: dict[int, list[float]] = {}
    away_scored: dict[int, list[float]] = {}
    away_conceded: dict[int, list[float]] = {}

    for match in matches:
        home_scored.setdefault(match.home_team_id, []).append(float(match.home_goals))
        home_conceded.setdefault(match.home_team_id, []).append(float(match.away_goals))
        away_scored.setdefault(match.away_team_id, []).append(float(match.away_goals))
        away_conceded.setdefault(match.away_team_id, []).append(float(match.home_goals))

    def recent(values: list[float]) -> list[float]:
        return values[-last_n:] if last_n else values

    # Each role is compared with the league average of what it faces: goals
    # scored at home against the average home score, goals conceded at home
    # against the average away score, and so on.
    roles: dict[str, tuple[dict[int, list[float]], float]] = {
        "attack_home": (home_scored, league.home_goals),
        "defense_home": (home_conceded, league.away_goals),
        "attack_away": (away_scored, league.away_goals),
        "defense_away": (away_conceded, league.home_goals),
    }

    # First pass: raw ratios and their sample sizes.
    raw: dict[str, dict[int, tuple[float, int]]] = {}
    for role, (values_by_team, denominator) in roles.items():
        entries: dict[int, tuple[float, int]] = {}
        for team_id, values in values_by_team.items():
            window = recent(values)
            if len(window) < min_matches:
                continue
            entries[team_id] = (
                _safe_ratio(float(np.mean(window)), denominator),
                len(window),
            )
        raw[role] = entries

    # Second pass: one shrinkage constant per role, then apply it.
    constants = {
        role: _shrinkage_constant(raw[role], roles[role][1], shrinkage) for role in roles
    }

    def strength_for(role: str, team_id: int) -> float:
        entry = raw[role].get(team_id)
        if entry is None:
            return 1.0
        ratio, count = entry
        return _shrink(ratio, count, constants[role])

    strengths: dict[int, TeamStrength] = {}
    team_ids = set(home_scored) | set(away_scored)

    for team_id in sorted(team_ids):
        hs = recent(home_scored.get(team_id, []))
        aws = recent(away_scored.get(team_id, []))

        attack_home = strength_for("attack_home", team_id)
        defense_home = strength_for("defense_home", team_id)
        attack_away = strength_for("attack_away", team_id)
        defense_away = strength_for("defense_away", team_id)

        strengths[team_id] = TeamStrength(
            team_id=team_id,
            attack_home=attack_home,
            defense_home=defense_home,
            attack_away=attack_away,
            defense_away=defense_away,
            matches_home=len(hs),
            matches_away=len(aws),
        )

    return strengths


NEUTRAL_STRENGTH = TeamStrength(
    team_id=-1, attack_home=1.0, defense_home=1.0, attack_away=1.0, defense_away=1.0
)


# --------------------------------------------------------------------------- #
# Step 3 - expected goals
# --------------------------------------------------------------------------- #
def expected_goals(
    home: TeamStrength | None,
    away: TeamStrength | None,
    league: LeagueAverages,
) -> tuple[float, float]:
    """Expected goals (lambda) for the home and away side of one fixture."""
    home = home or NEUTRAL_STRENGTH
    away = away or NEUTRAL_STRENGTH

    lambda_home = home.attack_home * away.defense_away * league.home_goals
    lambda_away = away.attack_away * home.defense_home * league.away_goals

    return (
        _clamp(lambda_home, MIN_LAMBDA, MAX_LAMBDA),
        _clamp(lambda_away, MIN_LAMBDA, MAX_LAMBDA),
    )


# --------------------------------------------------------------------------- #
# Step 4 - scoreline probability matrix
# --------------------------------------------------------------------------- #
def dixon_coles_tau(
    home_goals: int, away_goals: int, lambda_home: float, lambda_away: float, rho: float
) -> float:
    """Dixon-Coles correction factor for the four low-scoring scorelines."""
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lambda_home * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lambda_away * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = DEFAULT_MAX_GOALS,
    *,
    rho: float = 0.0,
) -> np.ndarray:
    """Joint probability of every scoreline from 0-0 up to ``max_goals``.

    Element ``[h][a]`` is P(home scores h AND away scores a). The matrix is
    renormalised so it sums to 1, which folds the small amount of probability
    beyond ``max_goals`` back into the grid.
    """
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("expected goals must be positive")
    if max_goals < 1:
        raise ValueError("max_goals must be at least 1")

    goals = np.arange(max_goals + 1)
    home_probs = poisson.pmf(goals, lambda_home)
    away_probs = poisson.pmf(goals, lambda_away)
    matrix = np.outer(home_probs, away_probs)

    if rho:
        correction = np.ones_like(matrix)
        for h in range(min(2, max_goals + 1)):
            for a in range(min(2, max_goals + 1)):
                correction[h][a] = dixon_coles_tau(h, a, lambda_home, lambda_away, rho)
        matrix = np.clip(matrix * correction, 0.0, None)

    total = matrix.sum()
    if total <= 0:
        raise ValueError("degenerate score matrix")
    return matrix / total


def total_goals_distribution(matrix: np.ndarray) -> dict[int, float]:
    """P(total goals == n) for every n representable in the matrix."""
    max_total = matrix.shape[0] + matrix.shape[1] - 2
    distribution = {n: 0.0 for n in range(max_total + 1)}
    for home_goals in range(matrix.shape[0]):
        for away_goals in range(matrix.shape[1]):
            distribution[home_goals + away_goals] += float(matrix[home_goals][away_goals])
    return distribution


# --------------------------------------------------------------------------- #
# Step 5 - Over / Under and 1X2
# --------------------------------------------------------------------------- #
def over_under_probability(matrix: np.ndarray, line: float) -> LineProbabilities:
    """Probability the total goals finish over or under a given line.

    Whole-number lines (2.0, 3.0 and so on) produce a push leg, which is
    exactly P(total == line). Half lines never push.
    """
    if line <= 0:
        raise ValueError("line must be positive")

    distribution = total_goals_distribution(matrix)
    over = sum(p for total, p in distribution.items() if total > line)
    under = sum(p for total, p in distribution.items() if total < line)
    push = sum(p for total, p in distribution.items() if float(total) == float(line))

    return LineProbabilities(
        line=float(line),
        prob_over=float(over),
        prob_under=float(under),
        prob_push=float(push),
    )


def over_under_table(
    matrix: np.ndarray, lines: Iterable[float] = DEFAULT_LINES
) -> dict[float, LineProbabilities]:
    """Over/Under probabilities for several lines at once."""
    return {float(line): over_under_probability(matrix, line) for line in lines}


def match_outcome_probabilities(matrix: np.ndarray) -> tuple[float, float, float]:
    """(home win, draw, away win) probabilities from the score matrix."""
    home_win = float(np.tril(matrix, -1).sum())
    draw = float(np.trace(matrix))
    away_win = float(np.triu(matrix, 1).sum())
    return home_win, draw, away_win


def most_likely_scoreline(matrix: np.ndarray) -> tuple[int, int]:
    """The single most probable scoreline in the matrix."""
    index = int(np.argmax(matrix))
    return divmod(index, matrix.shape[1])


# --------------------------------------------------------------------------- #
# Convenience: from raw history to a full prediction
# --------------------------------------------------------------------------- #
def predict_match(
    home_team_id: int,
    away_team_id: int,
    strengths: Mapping[int, TeamStrength],
    league: LeagueAverages,
    *,
    lines: Iterable[float] = DEFAULT_LINES,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = 0.0,
) -> MatchPrediction:
    """Build a complete prediction for one fixture."""
    lambda_home, lambda_away = expected_goals(
        strengths.get(home_team_id), strengths.get(away_team_id), league
    )
    matrix = score_matrix(lambda_home, lambda_away, max_goals, rho=rho)
    home_win, draw, away_win = match_outcome_probabilities(matrix)

    return MatchPrediction(
        expected_home_goals=lambda_home,
        expected_away_goals=lambda_away,
        score_matrix=matrix,
        total_goals_distribution=total_goals_distribution(matrix),
        lines=over_under_table(matrix, lines),
        prob_home_win=home_win,
        prob_draw=draw,
        prob_away_win=away_win,
        most_likely_score=most_likely_scoreline(matrix),
    )


def predict_from_history(
    home_team_id: int,
    away_team_id: int,
    history: Sequence[MatchResult],
    *,
    last_n: int | None = 20,
    lines: Iterable[float] = DEFAULT_LINES,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = 0.0,
    shrinkage: Shrinkage = None,
) -> MatchPrediction:
    """Fit the model on ``history`` and predict one fixture in a single call."""
    league = compute_league_averages(history)
    strengths = compute_team_strengths(history, league, last_n=last_n, shrinkage=shrinkage)
    return predict_match(
        home_team_id,
        away_team_id,
        strengths,
        league,
        lines=lines,
        max_goals=max_goals,
        rho=rho,
    )
