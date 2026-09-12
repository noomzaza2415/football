"""Pydantic schemas: the shape of every API response."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchStatus

ORM = ConfigDict(from_attributes=True)

# Shown to end users, so it is written in the interface language (Thai).
DISCLAIMER = (
    "เครื่องมือวิเคราะห์สถิติเพื่อการศึกษาเท่านั้น "
    "ผลลัพธ์จากโมเดลเป็นเพียงค่าประมาณ ไม่ได้การันตีผลใด ๆ "
    "การนำไปใช้พนันด้วยเงินจริงมีความเสี่ยงทางการเงินและอาจสูญเสียเงินได้"
)


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
class TeamOut(BaseModel):
    model_config = ORM

    id: int
    name: str
    short_name: str | None = None
    league: str
    country: str | None = None
    crest_url: str | None = None


class TeamStatsOut(BaseModel):
    model_config = ORM

    team_id: int
    matches_played: int
    matches_played_home: int
    matches_played_away: int
    avg_goals_scored_home: float
    avg_goals_scored_away: float
    avg_goals_conceded_home: float
    avg_goals_conceded_away: float
    avg_total_goals: float
    over_2_5_rate: float
    btts_rate: float
    form_last_5: str
    form_points_last_5: int
    attack_strength_home: float
    attack_strength_away: float
    defense_strength_home: float
    defense_strength_away: float
    sample_matches: int
    updated_at: datetime | None = None


class TeamWithStatsOut(BaseModel):
    team: TeamOut
    stats: TeamStatsOut | None = None


# --------------------------------------------------------------------------- #
# Matches
# --------------------------------------------------------------------------- #
class MarketOdds(BaseModel):
    line: float
    odds_over: float | None = None
    odds_under: float | None = None


class MatchOut(BaseModel):
    model_config = ORM

    id: int
    league: str
    season: str | None = None
    match_date: datetime
    status: MatchStatus
    home_team: TeamOut
    away_team: TeamOut
    home_goals: int | None = None
    away_goals: int | None = None
    market_line: float | None = None
    market_odds_over: float | None = None
    market_odds_under: float | None = None


class MatchSummaryOut(BaseModel):
    """A fixture plus the short prediction blurb shown on the home page card."""

    match: MatchOut
    expected_total_goals: float | None = None
    prob_over_2_5: float | None = None
    prob_under_2_5: float | None = None
    lean: str | None = Field(
        default=None, description="OVER, UNDER or NEUTRAL at the 2.5 line"
    )
    edge_over_2_5: float | None = Field(
        default=None, description="Model probability minus vig-free market probability"
    )
    model_version: str | None = None

    # Filled in only once a match has been played.
    actual_total_goals: int | None = None
    actual_result: str | None = Field(
        default=None, description="OVER or UNDER at 2.5, once the match is finished"
    )
    model_correct: bool | None = Field(
        default=None,
        description="Whether the lean matched the result. None when the model was neutral.",
    )
    point_in_time: bool = Field(
        default=False,
        description=(
            "True when the prediction was fitted only on matches that finished "
            "before kick-off, which is the only honest way to show a past match."
        ),
    )


class MatchDayOut(BaseModel):
    """How many matches fall on one calendar day, for the date picker."""

    date: str
    total: int
    scheduled: int
    finished: int


class DateRangeOut(BaseModel):
    """The span of dates the database actually holds."""

    earliest: datetime | None = None
    latest: datetime | None = None
    days: list[MatchDayOut] = Field(default_factory=list)


class FreshnessOut(BaseModel):
    """How current the stored data is.

    The dashboard states this openly rather than implying the numbers are live.
    The underlying sources publish on their own schedule, so a page can be
    freshly rendered from data that is a day old.
    """

    last_ingest_at: datetime | None = None
    latest_result_at: datetime | None = None
    next_kickoff_at: datetime | None = None
    server_time: datetime


class MatchDayViewOut(BaseModel):
    """One calendar day of matches, with links to the neighbouring match days."""

    day: date | None = None
    matches: list[MatchSummaryOut] = Field(default_factory=list)
    previous_day: date | None = None
    next_day: date | None = None
    freshness: FreshnessOut
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
# Predictions
# --------------------------------------------------------------------------- #
class LineProbabilityOut(BaseModel):
    line: float
    prob_over: float
    prob_under: float
    prob_push: float = 0.0
    fair_odds_over: float | None = None
    fair_odds_under: float | None = None


class TotalGoalsBucket(BaseModel):
    total_goals: int
    probability: float


class ScorelineOut(BaseModel):
    home_goals: int
    away_goals: int
    probability: float


class MarketComparisonOut(BaseModel):
    line: float
    selection: str
    decimal_odds: float
    market_probability: float
    fair_market_probability: float
    model_probability: float
    edge: float
    expected_value: float
    is_value: bool
    kelly_fraction: float


class PredictionOut(BaseModel):
    match: MatchOut
    expected_home_goals: float
    expected_away_goals: float
    expected_total_goals: float
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    most_likely_score: str
    lines: list[LineProbabilityOut]
    total_goals_distribution: list[TotalGoalsBucket]
    top_scorelines: list[ScorelineOut]
    market_comparison: list[MarketComparisonOut] = Field(default_factory=list)
    sample_matches: int
    model_version: str
    created_at: datetime | None = None
    disclaimer: str = DISCLAIMER


class RefreshPredictionRequest(BaseModel):
    last_n: int | None = Field(default=None, ge=4, le=100)
    max_goals: int | None = Field(default=None, ge=3, le=12)
    rho: float | None = Field(default=None, ge=-0.3, le=0.3)
    lines: list[float] | None = None


# --------------------------------------------------------------------------- #
# Backtest / history
# --------------------------------------------------------------------------- #
class PredictionHistoryItem(BaseModel):
    match_id: int
    match_date: datetime
    league: str
    home_team: str
    away_team: str
    predicted_total_goals: float
    prob_over_2_5: float
    model_pick: str
    actual_home_goals: int
    actual_away_goals: int
    actual_total_goals: int
    actual_result: str
    correct: bool
    model_version: str
    created_at: datetime | None = None


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_probability: float
    actual_rate: float
    samples: int


class PredictionHistoryOut(BaseModel):
    items: list[PredictionHistoryItem]
    total: int
    evaluated: int
    correct: int
    accuracy: float
    over_picks: int
    under_picks: int
    over_hit_rate: float
    under_hit_rate: float
    brier_score: float = Field(
        description="Mean squared error of the Over 2.5 probability. Lower is better."
    )
    mean_absolute_goal_error: float
    calibration: list[CalibrationBucket] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
# Walk-forward backtest
# --------------------------------------------------------------------------- #
class ScoreCardOut(BaseModel):
    """One forecaster scored over the tested matches. Lower is better."""

    name: str
    brier: float
    log_loss: float
    samples: int
    skill_vs_base_rate: float | None = Field(
        default=None,
        description="Brier skill score against the historical Over rate. "
        "Positive means better than that baseline.",
    )


class BacktestRecordOut(BaseModel):
    match_id: int
    kickoff: datetime
    league: str
    home_team: str
    away_team: str
    train_size: int
    predicted_total_goals: float
    prob_over: float
    model_pick: str
    actual_home_goals: int
    actual_away_goals: int
    actual_total_goals: int
    actual_result: str
    correct: bool | None
    profit: float | None = None


class BacktestOut(BaseModel):
    """The result of one walk-forward run."""

    model_version: str
    line: float
    window: str
    train_window: int | None
    min_train_matches: int
    last_n: int
    rho: float

    tested: int
    scored: int
    accuracy: float
    actual_over_rate: float
    mean_absolute_goal_error: float
    rmse_goals: float

    scorecards: list[ScoreCardOut]
    calibration: list[CalibrationBucket]

    priced_picks: int
    profit: float
    roi: float

    records: list[BacktestRecordOut] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #
class NewsSourceOut(BaseModel):
    key: str
    name: str
    url: str
    language: str
    scope: str
    topic: str = Field(
        default="football",
        description=(
            "football for a dedicated feed, sport for a combined one whose items "
            "are filtered by keyword"
        ),
    )


class NewsItemOut(BaseModel):
    source: str
    source_key: str
    language: str
    scope: str
    title: str
    url: str
    summary: str | None = None
    published_at: datetime | None = None


class NewsFeedOut(BaseModel):
    """Headlines plus the note explaining that they are not model input."""

    items: list[NewsItemOut] = Field(default_factory=list)
    note: str


class HealthOut(BaseModel):
    status: str
    environment: str
    model_version: str
    teams: int
    matches: int
    finished_matches: int
    predictions: int
