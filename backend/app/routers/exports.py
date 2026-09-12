"""CSV export endpoints, for spreadsheets.

Two ways into Google Sheets. Download a file and use File, Import, which works
straight away on localhost. Or, once the API is reachable from the internet,
put a formula in a cell so the sheet refreshes itself:

    =IMPORTDATA("https://your-host/api/export/backtest.csv")

``IMPORTDATA`` is fetched by Google's servers, not by the browser, so it cannot
reach a machine on your own network. For a local database use the download, or
the ``scripts/export_to_sheets.py`` writer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import exporters
from app.analytics.backtest import NotEnoughHistoryError
from app.database import get_db

router = APIRouter(prefix="/export", tags=["export"])

TABLE_NAMES = sorted(exporters.TABLES)


def _csv_response(name: str, body: str) -> Response:
    # The BOM makes Excel and Sheets read the file as UTF-8 rather than guessing.
    return Response(
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("", summary="Which tables can be exported")
def index() -> dict[str, object]:
    return {
        "tables": TABLE_NAMES,
        "csv": [f"/api/export/{name}.csv" for name in TABLE_NAMES],
        "note": (
            "ดาวน์โหลดแล้วใช้ File, Import ใน Google Sheets ได้ทันที "
            "ส่วนสูตร IMPORTDATA ใช้ได้เมื่อ API เปิดให้เข้าถึงจากอินเทอร์เน็ตแล้วเท่านั้น"
        ),
    }


@router.get("/{table}.csv", summary="One table as CSV")
def export_csv(
    table: str,
    league: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=20000),
    min_train_matches: int | None = Query(default=None, ge=10, le=5000),
    db: Session = Depends(get_db),
) -> Response:
    try:
        header, rows = exporters.build_table(
            db,
            table,
            league=league,
            limit=limit,
            min_train_matches=min_train_matches,
        )
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"unknown table {table!r}; choose from {TABLE_NAMES}",
        ) from exc
    except NotEnoughHistoryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return _csv_response(table, exporters.to_csv(header, rows))
