"""Backtest endpoints: how the model did on matches it had never seen."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import services
from app.analytics.backtest import NotEnoughHistoryError
from app.database import get_db
from app.schemas import (
    BacktestOut,
    BacktestRecordOut,
    CalibrationBucket,
    PredictionHistoryOut,
    ScoreCardOut,
)

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get(
    "/history",
    response_model=PredictionHistoryOut,
    summary="Stored predictions scored against the real result",
)
def history(
    league: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> PredictionHistoryOut:
    data = services.prediction_history(
        db, league=league, limit=limit, model_version=model_version
    )
    return PredictionHistoryOut(**data)


@router.get(
    "/backtest",
    response_model=BacktestOut,
    summary="Walk-forward backtest: refit before every match, predict, then score",
)
def backtest(
    league: str | None = Query(default=None),
    min_train_matches: int = Query(
        default=60,
        ge=10,
        le=5000,
        description="Matches used to warm up before the first prediction",
    ),
    window: Literal["expanding", "rolling"] = Query(
        default="expanding",
        description="expanding trains on all prior matches; rolling on the last train_window",
    ),
    train_window: int | None = Query(
        default=None, ge=10, le=5000, description="Required when window is rolling"
    ),
    last_n: int | None = Query(default=None, ge=4, le=100),
    rho: float | None = Query(default=None, ge=-0.3, le=0.3),
    line: float = Query(default=2.5, gt=0, le=10),
    include_records: bool = Query(
        default=False, description="Include every scored match, not just the summary"
    ),
    db: Session = Depends(get_db),
) -> BacktestOut:
    try:
        report = services.run_backtest(
            db,
            league=league,
            min_train_matches=min_train_matches,
            window=window,
            train_window=train_window,
            last_n=last_n,
            rho=rho,
            line=line,
        )
    except NotEnoughHistoryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    cards = report.scorecards()
    base_rate = cards[2] if len(cards) > 2 else None

    return BacktestOut(
        model_version=report.model_version,
        line=report.line,
        window=report.window,
        train_window=report.train_window,
        min_train_matches=report.min_train_matches,
        last_n=report.last_n,
        rho=report.rho,
        tested=report.tested,
        scored=len(report.scored),
        accuracy=report.accuracy,
        actual_over_rate=report.actual_over_rate,
        mean_absolute_goal_error=report.mean_absolute_goal_error,
        rmse_goals=report.rmse_goals,
        scorecards=[
            ScoreCardOut(
                name=card.name,
                brier=card.brier,
                log_loss=card.log_loss,
                samples=card.samples,
                skill_vs_base_rate=(
                    card.skill_against(base_rate) if base_rate is not None else None
                ),
            )
            for card in cards
        ],
        calibration=[
            CalibrationBucket(
                bucket=bucket.bucket,
                predicted_probability=bucket.predicted_probability,
                actual_rate=bucket.actual_rate,
                samples=bucket.samples,
            )
            for bucket in report.calibration()
        ],
        priced_picks=len(report.priced_picks),
        profit=report.profit,
        roi=report.roi,
        records=(
            [
                BacktestRecordOut(
                    match_id=record.match_id,
                    kickoff=record.kickoff,
                    league=record.league,
                    home_team=record.home_name,
                    away_team=record.away_name,
                    train_size=record.train_size,
                    predicted_total_goals=record.predicted_total_goals,
                    prob_over=record.prob_over,
                    model_pick=record.pick,
                    actual_home_goals=record.actual_home_goals,
                    actual_away_goals=record.actual_away_goals,
                    actual_total_goals=record.actual_total_goals,
                    actual_result="OVER" if record.actual_over else "UNDER",
                    correct=record.correct,
                    profit=record.profit(),
                )
                for record in report.records
            ]
            if include_records
            else []
        ),
    )
