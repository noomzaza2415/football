"""Push the analysis tables to a Google Sheet through an Apps Script web app.

This is the route that needs no Google Cloud project, no service account and no
key file. Apps Script runs on Google's servers and so cannot reach a backend on
your own machine, and neither can the IMPORTDATA formula; instead a small script
bound to the sheet waits to be pushed to, and this command does the pushing.

Setup is in ``apps-script/Code.gs``. In short: paste it into the sheet's Apps
Script editor, run ``setup`` once to grant permission, deploy it as a web app,
then put the deployment URL and the secret in ``backend/.env``:

    GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/..../exec
    GOOGLE_APPS_SCRIPT_TOKEN=the-same-secret-as-in-Code.gs

Then

    python -m scripts.push_to_sheets
    python -m scripts.push_to_sheets --tables backtest team_stats
    python -m scripts.push_to_sheets --dry-run
    python -m scripts.push_to_sheets --ping
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from typing import Any

import httpx

from app import exporters
from app.config import get_settings
from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("sheets")

REQUEST_TIMEOUT = 120.0

#: Apps Script accepts a large body, but one table per request keeps each write
#: quick and makes a failure name the table that failed.
ONE_TABLE_PER_REQUEST = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Push tables to a Google Sheet via Apps Script"
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        default=sorted(exporters.TABLES),
        choices=sorted(exporters.TABLES),
        help="which tables to push (default: all)",
    )
    parser.add_argument("--league", default=None, help="restrict to one league")
    parser.add_argument(
        "--min-train",
        type=int,
        default=300,
        help="warm-up length for the backtest table (default 300)",
    )
    parser.add_argument("--url", default=None, help="override GOOGLE_APPS_SCRIPT_URL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build the tables and report their size without sending anything",
    )
    parser.add_argument(
        "--ping",
        action="store_true",
        help="check the deployment answers, and list the tabs it can see",
    )
    return parser.parse_args(argv)


def json_safe(value: Any) -> Any:
    """Values Apps Script can read back as text or numbers.

    A date or datetime becomes ISO text rather than something JSON cannot hold.
    Sheets parses that back into a real date when the cell format allows it.
    """
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def build_payload_tables(
    db, names: list[str], *, league: str | None, min_train: int
) -> list[dict]:
    """Build each requested table, skipping any that cannot be produced."""
    tables: list[dict] = []
    for name in names:
        try:
            header, rows = exporters.build_table(
                db, name, league=league, min_train_matches=min_train
            )
        except Exception as exc:  # one unavailable table must not stop the rest
            logger.error("ข้าม %s: %s", name, exc)
            continue

        tables.append(
            {
                "name": name,
                "header": list(header),
                "rows": [[json_safe(cell) for cell in row] for row in rows],
            }
        )
    return tables


def post(url: str, body: dict) -> dict:
    """Send one request and interpret the Apps Script reply.

    An Apps Script web app answers 200 even for a refusal, and redirects to a
    googleusercontent host to deliver the body, so redirects must be followed.
    """
    try:
        response = httpx.post(
            url,
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise SystemExit(f"ส่งไม่สำเร็จ: {exc}") from exc

    if response.status_code >= 400:
        raise SystemExit(
            f"Apps Script ตอบ {response.status_code}. "
            "ตรวจว่า deploy เป็น Web app และตั้ง Who has access เป็น Anyone แล้ว"
        )

    text = response.text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # An HTML body here almost always means a Google sign-in page, which is
        # what a deployment restricted to your account returns.
        hint = (
            "ได้ HTML กลับมาแทน JSON ซึ่งมักหมายความว่า deployment ยังไม่ได้ตั้ง "
            "Who has access เป็น Anyone"
        )
        raise SystemExit(f"{hint}\n{text[:200]}")


def ping(url: str) -> int:
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.error("ติดต่อ Apps Script ไม่ได้: %s", exc)
        return 1

    try:
        body = response.json()
    except ValueError:
        logger.error(
            "ได้ HTML กลับมา ไม่ใช่ JSON ให้ตั้ง Who has access เป็น Anyone แล้ว deploy ใหม่"
        )
        return 1

    logger.info("เชื่อมต่อได้: %s", body.get("spreadsheet", "(ไม่ทราบชื่อชีต)"))
    logger.info("แท็บที่มีอยู่: %s", ", ".join(body.get("tabs", [])))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    url = args.url or settings.google_apps_script_url
    token = settings.google_apps_script_token

    if args.ping:
        if not url:
            logger.error("ยังไม่ได้ตั้ง GOOGLE_APPS_SCRIPT_URL ใน .env")
            return 2
        return ping(url)

    with SessionLocal() as db:
        tables = build_payload_tables(
            db, args.tables, league=args.league, min_train=args.min_train
        )

    if not tables:
        logger.error("ไม่มีตารางที่สร้างได้ ลองรัน ingest ก่อน")
        return 1

    if args.dry_run:
        for table in tables:
            logger.info(
                "%s: %s คอลัมน์ %s แถว",
                table["name"],
                len(table["header"]),
                len(table["rows"]),
            )
        logger.info("dry run ไม่ได้ส่งอะไรออกไป")
        return 0

    if not url or not token:
        logger.error(
            "ต้องตั้ง GOOGLE_APPS_SCRIPT_URL และ GOOGLE_APPS_SCRIPT_TOKEN ใน .env ก่อน "
            "ดูขั้นตอนใน apps-script/Code.gs หรือใช้ --dry-run เพื่อดูข้อมูลก่อน"
        )
        return 2

    batches = [[table] for table in tables] if ONE_TABLE_PER_REQUEST else [tables]

    for batch in batches:
        reply = post(url, {"token": token, "tables": batch})
        if not reply.get("ok"):
            error = reply.get("error", "ไม่ทราบสาเหตุ")
            if error == "unauthorised":
                error += " (GOOGLE_APPS_SCRIPT_TOKEN ไม่ตรงกับ SECRET ใน Code.gs)"
            logger.error("%s: %s", batch[0]["name"], error)
            return 1

        for written in reply.get("written", []):
            logger.info("เขียนแท็บ %s แล้ว %s แถว", written["name"], written["rows"])

    logger.info("เสร็จแล้ว เปิดชีตดูได้เลย")
    return 0


if __name__ == "__main__":
    sys.exit(main())
