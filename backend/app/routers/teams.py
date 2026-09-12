"""Team endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import TeamOut, TeamStatsOut, TeamWithStatsOut

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut], summary="List every team")
def list_teams(
    league: str | None = Query(default=None, description="Filter by league code"),
    search: str | None = Query(default=None, description="Case-insensitive name match"),
    db: Session = Depends(get_db),
) -> list[TeamOut]:
    return services.list_teams(db, league=league, search=search)


@router.get("/{team_id}", response_model=TeamOut, summary="One team")
def get_team(team_id: int, db: Session = Depends(get_db)) -> TeamOut:
    team = services.get_team(db, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"team {team_id} not found")
    return team


@router.get(
    "/{team_id}/stats",
    response_model=TeamWithStatsOut,
    summary="Aggregated stats and model strengths for one team",
)
def get_team_stats(team_id: int, db: Session = Depends(get_db)) -> TeamWithStatsOut:
    team = services.get_team(db, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"team {team_id} not found")

    stats = services.get_team_stats(db, team_id)
    return TeamWithStatsOut(
        team=TeamOut.model_validate(team),
        stats=TeamStatsOut.model_validate(stats) if stats else None,
    )


@router.post(
    "/rebuild-stats",
    summary="Recompute every team_stats row from the match history",
    status_code=status.HTTP_200_OK,
)
def rebuild_stats(
    league: str | None = Query(default=None), db: Session = Depends(get_db)
) -> dict[str, int | str]:
    updated = services.rebuild_team_stats(db, league=league)
    return {"updated_teams": updated, "status": "ok"}
