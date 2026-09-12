"""Derive the team_stats table from the raw match history.

The stats table is a materialised view: everything in it can be recomputed
from ``matches`` alone. It exists so the API can serve a team page without
scanning the whole history on every request, and so the frontend has a stable
shape to render.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.analytics.poisson_model import (
    LeagueAverages,
    MatchResult,
    TeamStrength,
    compute_league_averages,
    compute_team_strengths,
)

FORM_WINDOW = 5


@dataclass(frozen=True)
class TeamMatch:
    """One finished match seen from a single team's point of view."""

    team_id: int
    opponent_id: int
    is_home: bool
    goals_for: int
    goals_against: int

    @property
    def result(self) -> str:
        if self.goals_for > self.goals_against:
            return "W"
        if self.goals_for < self.goals_against:
            return "L"
        return "D"

    @property
    def points(self) -> int:
        return {"W": 3, "D": 1, "L": 0}[self.result]


@dataclass
class TeamStatsRow:
    """One row of the team_stats table."""

    team_id: int
    matches_played: int = 0
    matches_played_home: int = 0
    matches_played_away: int = 0
    avg_goals_scored_home: float = 0.0
    avg_goals_scored_away: float = 0.0
    avg_goals_conceded_home: float = 0.0
    avg_goals_conceded_away: float = 0.0
    avg_total_goals: float = 0.0
    over_2_5_rate: float = 0.0
    btts_rate: float = 0.0
    form_last_5: str = ""
    form_points_last_5: int = 0
    attack_strength_home: float = 1.0
    attack_strength_away: float = 1.0
    defense_strength_home: float = 1.0
    defense_strength_away: float = 1.0
    sample_matches: int = 0


def _mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def team_match_view(
    matches: Sequence[MatchResult], team_id: int
) -> list[TeamMatch]:
    """Every match involving ``team_id``, oriented so goals_for is theirs."""
    view: list[TeamMatch] = []
    for match in matches:
        if match.home_team_id == team_id:
            view.append(
                TeamMatch(
                    team_id=team_id,
                    opponent_id=match.away_team_id,
                    is_home=True,
                    goals_for=match.home_goals,
                    goals_against=match.away_goals,
                )
            )
        elif match.away_team_id == team_id:
            view.append(
                TeamMatch(
                    team_id=team_id,
                    opponent_id=match.home_team_id,
                    is_home=False,
                    goals_for=match.away_goals,
                    goals_against=match.home_goals,
                )
            )
    return view


def form_string(matches: Sequence[MatchResult], team_id: int, window: int = FORM_WINDOW) -> str:
    """Recent results as a W/D/L string, most recent last.

    ``matches`` must be ordered oldest first, the same ordering the model
    itself expects.
    """
    view = team_match_view(matches, team_id)
    return "".join(m.result for m in view[-window:])


def build_team_stats(
    matches: Sequence[MatchResult],
    team_id: int,
    *,
    league: LeagueAverages | None = None,
    strength: TeamStrength | None = None,
    last_n: int | None = 20,
) -> TeamStatsRow:
    """Aggregate one team's row from the match history."""
    view = team_match_view(matches, team_id)
    if not view:
        return TeamStatsRow(team_id=team_id)

    recent = view[-last_n:] if last_n else view
    home = [m for m in recent if m.is_home]
    away = [m for m in recent if not m.is_home]

    totals = [m.goals_for + m.goals_against for m in recent]
    form = form_string(matches, team_id)

    row = TeamStatsRow(
        team_id=team_id,
        matches_played=len(recent),
        matches_played_home=len(home),
        matches_played_away=len(away),
        avg_goals_scored_home=_mean([m.goals_for for m in home]),
        avg_goals_scored_away=_mean([m.goals_for for m in away]),
        avg_goals_conceded_home=_mean([m.goals_against for m in home]),
        avg_goals_conceded_away=_mean([m.goals_against for m in away]),
        avg_total_goals=_mean(totals),
        over_2_5_rate=_mean([1.0 if t > 2.5 else 0.0 for t in totals]),
        btts_rate=_mean(
            [1.0 if m.goals_for > 0 and m.goals_against > 0 else 0.0 for m in recent]
        ),
        form_last_5=form,
        form_points_last_5=sum(m.points for m in view[-FORM_WINDOW:]),
        sample_matches=len(recent),
    )

    if strength is not None:
        row.attack_strength_home = strength.attack_home
        row.attack_strength_away = strength.attack_away
        row.defense_strength_home = strength.defense_home
        row.defense_strength_away = strength.defense_away

    return row


def build_all_team_stats(
    matches: Sequence[MatchResult], *, last_n: int | None = 20
) -> dict[int, TeamStatsRow]:
    """Build stats rows for every team present in the history."""
    if not matches:
        return {}

    league = compute_league_averages(matches)
    strengths = compute_team_strengths(matches, league, last_n=last_n)

    team_ids = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
    return {
        team_id: build_team_stats(
            matches,
            team_id,
            league=league,
            strength=strengths.get(team_id),
            last_n=last_n,
        )
        for team_id in sorted(team_ids)
    }
