"""Football news headlines, as reading context beside the analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.pipeline import news as news_lib
from app.schemas import NewsFeedOut, NewsItemOut, NewsSourceOut

router = APIRouter(prefix="/news", tags=["news"])

NOTE = (
    "พาดหัวข่าวเป็นข้อมูลประกอบการอ่านของคุณเท่านั้น ไม่ได้ถูกนำเข้าไปคำนวณในโมเดล "
    "เพราะยังไม่มีวิธีแปลงข้อความข่าวเป็นค่าประตูคาดหวังที่ตรวจสอบความถูกต้องได้"
)


def _serialize(items: list[news_lib.NewsItem]) -> list[NewsItemOut]:
    return [
        NewsItemOut(
            source=item.source,
            source_key=item.source_key,
            language=item.language,
            scope=item.scope,
            title=item.title,
            url=item.url,
            summary=item.summary,
            published_at=item.published_at,
        )
        for item in items
    ]


@router.get("/sources", response_model=list[NewsSourceOut], summary="Feeds that are read")
def sources() -> list[NewsSourceOut]:
    return [
        NewsSourceOut(
            key=source.key,
            name=source.name,
            url=source.url,
            language=source.language,
            scope=source.scope,
            topic=source.topic,
        )
        for source in news_lib.SOURCES
    ]


@router.get("", response_model=NewsFeedOut, summary="Latest football headlines")
def latest(
    language: str | None = Query(
        default=None, description="Filter to one language, th or en"
    ),
    source: list[str] | None = Query(default=None, description="Feed keys to read"),
    limit: int = Query(default=20, ge=1, le=60),
) -> NewsFeedOut:
    if source:
        unknown = [key for key in source if key not in news_lib.SOURCES_BY_KEY]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"unknown news source: {unknown}",
            )

    items = news_lib.fetch_news(keys=source, language=language, limit=limit)
    return NewsFeedOut(items=_serialize(items), note=NOTE)


@router.get(
    "/match/{match_id}",
    response_model=NewsFeedOut,
    summary="Headlines naming either side of one fixture",
)
def for_match(
    match_id: int,
    language: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=30),
    db: Session = Depends(get_db),
) -> NewsFeedOut:
    match = services.get_match(db, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"match {match_id} not found")

    items = news_lib.news_for_match(
        match.home_team.name, match.away_team.name, limit=limit, language=language
    )
    return NewsFeedOut(items=_serialize(items), note=NOTE)
