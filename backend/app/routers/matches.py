"""Match, matchday and per-match prediction endpoints."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import services
from app.analytics.poisson_model import InsufficientDataError
from app.models import MatchStatus
from app.schemas import (
    DateRangeOut,
    MatchDayOut,
    MatchDayViewOut,
    MatchOut,
    MatchSummaryOut,
    PredictionOut,
    RefreshPredictionRequest,
)
from app.database import get_db

router = APIRouter(prefix="/matches", tags=["matches"])

MAX_RANGE_DAYS = 60


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """A calendar day as a half-open UTC window."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


@router.get(
    "/calendar",
    response_model=DateRangeOut,
    summary="Which days actually have matches, for the date picker",
)
def calendar(
    league: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> DateRangeOut:
    days = services.match_day_counts(db, league=league)
    if not days:
        return DateRangeOut()

    return DateRangeOut(
        earliest=datetime.fromisoformat(days[0]["date"]).replace(tzinfo=timezone.utc),
        latest=datetime.fromisoformat(days[-1]["date"]).replace(tzinfo=timezone.utc),
        days=[MatchDayOut(**day) for day in days],
    )


@router.get(
    "/day",
    response_model=MatchDayViewOut,
    summary="One day of matches with the model summary for each",
)
def match_day(
    day: date | None = Query(
        default=None,
        description="Calendar day in YYYY-MM-DD. Defaults to the nearest day with matches.",
    ),
    league: str | None = Query(default=None),
    include_prediction: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> MatchDayViewOut:
    """The default view: whatever day is most worth looking at right now.

    A finished match on this day is predicted only from matches that kicked off
    before it, so a past day shows what the model would have said at the time
    rather than a model that already knows the score.
    """
    resolved = day or services.nearest_match_day(db, league=league)
    if resolved is None:
        return MatchDayViewOut(
            day=None,
            matches=[],
            freshness=services.data_freshness(db),
        )

    start, end = _day_bounds(resolved)
    matches = services.matches_between(db, start, end, league=league, limit=200)
    summaries = services.summarize_many(
        db, matches, include_prediction=include_prediction
    )

    counts = services.match_day_counts(db, league=league)
    dates = [entry["date"] for entry in counts]
    key = resolved.isoformat()
    previous_day = next((d for d in reversed(dates) if d < key), None)
    next_day = next((d for d in dates if d > key), None)

    return MatchDayViewOut(
        day=resolved,
        matches=summaries,
        previous_day=date.fromisoformat(previous_day) if previous_day else None,
        next_day=date.fromisoformat(next_day) if next_day else None,
        freshness=services.data_freshness(db),
    )


@router.get(
    "/range",
    response_model=list[MatchSummaryOut],
    summary="Matches between two dates",
)
def match_range(
    date_from: date = Query(description="First day, inclusive"),
    date_to: date = Query(description="Last day, inclusive"),
    league: str | None = Query(default=None),
    include_prediction: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[MatchSummaryOut]:
    if date_to < date_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_to is before date_from"
        )
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"range is limited to {MAX_RANGE_DAYS} days",
        )

    start, _ = _day_bounds(date_from)
    _, end = _day_bounds(date_to)
    matches = services.matches_between(db, start, end, league=league, limit=limit)
    return services.summarize_many(db, matches, include_prediction=include_prediction)


@router.get(
    "/upcoming",
    response_model=list[MatchSummaryOut],
    summary="Scheduled matches with a short model summary for each card",
)
def upcoming(
    days: int = Query(default=14, ge=1, le=60),
    league: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    include_prediction: bool = Query(
        default=True, description="Set false for a much cheaper listing"
    ),
    db: Session = Depends(get_db),
) -> list[MatchSummaryOut]:
    matches = services.upcoming_matches(db, days=days, league=league, limit=limit)
    return services.summarize_many(db, matches, include_prediction=include_prediction)


@router.get("/{match_id}", response_model=MatchOut, summary="One match")
def get_match(match_id: int, db: Session = Depends(get_db)) -> MatchOut:
    match = services.get_match(db, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"match {match_id} not found")
    return match


@router.get(
    "/{match_id}/prediction",
    response_model=PredictionOut,
    summary="Full analysis: expected goals, probability table and market comparison",
)
def get_prediction(
    match_id: int,
    point_in_time: bool | None = Query(
        default=None,
        description=(
            "Fit only on matches that finished before kick-off. Defaults to true "
            "for a match that has already been played, which is the only honest "
            "way to show one."
        ),
    ),
    db: Session = Depends(get_db),
) -> PredictionOut:
    match = services.get_match(db, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"match {match_id} not found")

    honest = match.is_finished if point_in_time is None else point_in_time

    try:
        prediction, sample = services.run_model_for_match(
            db, match, point_in_time=honest
        )
    except InsufficientDataError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    stored = services.latest_prediction(db, match_id)
    return services.serialize_prediction(
        match, prediction, sample, created_at=stored.created_at if stored else None
    )


@router.post(
    "/{match_id}/refresh-prediction",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Re-run the model and store the result as a new prediction row",
)
def refresh_prediction(
    match_id: int,
    body: RefreshPredictionRequest | None = None,
    db: Session = Depends(get_db),
) -> PredictionOut:
    match = services.get_match(db, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"match {match_id} not found")

    body = body or RefreshPredictionRequest()
    try:
        prediction, sample = services.run_model_for_match(
            db,
            match,
            last_n=body.last_n,
            max_goals=body.max_goals,
            rho=body.rho,
            lines=body.lines,
        )
    except InsufficientDataError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    stored = services.store_prediction(db, match, prediction, sample)
    return services.serialize_prediction(
        match, prediction, sample, created_at=stored.created_at
    )
