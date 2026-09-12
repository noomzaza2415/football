"""Push the analysis tables into a Google Sheet.

Setup, once
-----------
1. In Google Cloud, create a project and enable the Google Sheets API.
2. Create a **service account** and download its JSON key.
3. Open your spreadsheet, press Share, and share it as **Editor** with the
   service account's email, the ``...@....iam.gserviceaccount.com`` address
   inside that JSON file. Without this step every write returns 403, because
   the service account is a separate identity from your own Google account.
4. Put the path and the sheet id in ``backend/.env``:

       GOOGLE_SERVICE_ACCOUNT_FILE=C:/keys/football-ou-sheets.json
       GOOGLE_SHEET_ID=1AbC...the long id in the sheet's URL...

The key file is a credential. Keep it outside the repository; ``.gitignore``
already excludes ``*.json`` keys in the backend folder, but the safest place is
another directory entirely.

Then
----
    python -m scripts.export_to_sheets
    python -m scripts.export_to_sheets --tables backtest predictions
    python -m scripts.export_to_sheets --dry-run

Each table is written to its own worksheet tab, replacing what was there. One
worksheet per table means a chart or pivot built on a tab keeps working after
the next run.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app import exporters
from app.config import get_settings
from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("sheets")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MISSING_DEPENDENCY = (
    "ยังไม่ได้ติดตั้งไลบรารีของ Google Sheets\n"
    "  pip install gspread google-auth"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export tables to a Google Sheet")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=sorted(exporters.TABLES),
        choices=sorted(exporters.TABLES),
        help="which tables to write (default: all)",
    )
    parser.add_argument("--league", default=None, help="restrict to one league")
    parser.add_argument(
        "--min-train",
        type=int,
        default=300,
        help="warm-up length for the backtest table (default 300)",
    )
    parser.add_argument(
        "--sheet-id", default=None, help="override GOOGLE_SHEET_ID for one run"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build the tables and report their size without writing anything",
    )
    return parser.parse_args(argv)


def build_tables(db, names: list[str], *, league: str | None, min_train: int):
    """Build each requested table, skipping any that cannot be produced."""
    built: dict[str, tuple[list[str], list[list]]] = {}
    for name in names:
        try:
            built[name] = exporters.build_table(
                db, name, league=league, min_train_matches=min_train
            )
        except Exception as exc:  # one unavailable table must not stop the rest
            logger.error("ข้าม %s: %s", name, exc)
    return built


def open_sheet(sheet_id: str, credentials_file: str):
    """Authorise with the service account and open the spreadsheet."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise SystemExit(MISSING_DEPENDENCY) from exc

    credentials = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def write_tab(spreadsheet, name: str, header: list[str], rows: list[list]) -> None:
    """Replace one worksheet's contents, creating the tab if it is missing."""
    import gspread

    values = [header] + [["" if cell is None else cell for cell in row] for row in rows]

    try:
        worksheet = spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=name, rows=max(len(values) + 10, 100), cols=max(len(header), 10)
        )

    # Clear first, otherwise a shorter run leaves stale rows below the new data.
    worksheet.clear()
    worksheet.update(values, "A1", value_input_option="USER_ENTERED")
    worksheet.freeze(rows=1)
    logger.info("เขียน %s แล้ว %s แถว", name, len(rows))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    with SessionLocal() as db:
        tables = build_tables(
            db, args.tables, league=args.league, min_train=args.min_train
        )

    if not tables:
        logger.error("ไม่มีตารางที่สร้างได้ ลองรัน ingest ก่อน")
        return 1

    if args.dry_run:
        for name, (header, rows) in tables.items():
            logger.info("%s: %s คอลัมน์ %s แถว", name, len(header), len(rows))
        logger.info("dry run ไม่ได้เขียนอะไรลงชีต")
        return 0

    sheet_id = args.sheet_id or settings.google_sheet_id
    credentials_file = settings.google_service_account_file

    if not sheet_id or not credentials_file:
        logger.error(
            "ต้องตั้ง GOOGLE_SHEET_ID และ GOOGLE_SERVICE_ACCOUNT_FILE ใน .env ก่อน "
            "ดูขั้นตอนที่หัวไฟล์นี้ หรือใช้ --dry-run เพื่อดูข้อมูลก่อน"
        )
        return 2

    spreadsheet = open_sheet(sheet_id, credentials_file)
    for name, (header, rows) in tables.items():
        write_tab(spreadsheet, name, header, rows)

    logger.info("เสร็จแล้ว: https://docs.google.com/spreadsheets/d/%s", sheet_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
