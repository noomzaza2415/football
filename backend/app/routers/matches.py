"""Match and per-match prediction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import services
from app.analytics.poisson_model import InsufficientDataError
from app.database import get_db
from app.schemas import MatchOut, MatchSummaryOut, PredictionOut, RefreshPredictionRequest

router = APIRouter(prefix="/matches", tags=["matches"])


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

    summaries: list[MatchSummaryOut] = []
    for match in matches:
        prediction = None
        sample = 0
        if include_prediction:
            try:
                prediction, sample = services.run_model_for_match(db, match)
            except InsufficientDataError:
                prediction = None
        summaries.append(services.summarize_match(db, match, prediction, sample))
    return summaries


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
    point_in_time: bool = Query(
        default=False,
        description="Fit only on matches that finished before kick-off, for honest backtests",
    ),
    db: Session = Depends(get_db),
) -> PredictionOut:
    match = services.get_match(db, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"match {match_id} not found")

    try:
        prediction, sample = services.run_model_for_match(
            db, match, point_in_time=point_in_time
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
