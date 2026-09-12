"""Run a walk-forward backtest from the command line.

    python -m scripts.run_backtest
    python -m scripts.run_backtest --min-train 80 --window rolling --train-window 120
    python -m scripts.run_backtest --compare-last-n 10 15 20 30
    python -m scripts.run_backtest --csv backtest.csv --rows 15

Exits 1 when there is not enough history to test anything, so a scheduled run
can alert on it.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys

from app.analytics.backtest import NotEnoughHistoryError, format_report
from app.database import SessionLocal
from app import services

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("backtest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest of the Poisson goal model"
    )
    parser.add_argument("--league", default=None, help="restrict to one league")
    parser.add_argument(
        "--min-train",
        type=int,
        default=60,
        help="matches to warm up on before the first prediction (default 60)",
    )
    parser.add_argument(
        "--window",
        choices=["expanding", "rolling"],
        default="expanding",
        help="expanding uses all prior matches; rolling uses the last --train-window",
    )
    parser.add_argument(
        "--train-window", type=int, default=None, help="required for rolling mode"
    )
    parser.add_argument(
        "--last-n", type=int, default=None, help="form window per team (default from .env)"
    )
    parser.add_argument(
        "--rho", type=float, default=None, help="Dixon-Coles rho (default from .env)"
    )
    parser.add_argument("--line", type=float, default=2.5, help="line to test (default 2.5)")
    parser.add_argument(
        "--shrinkage",
        default=None,
        help="auto, off, or a number; defaults to MODEL_SHRINKAGE from .env",
    )
    parser.add_argument(
        "--compare-shrinkage",
        action="store_true",
        help="run with shrinkage off and on, and print both side by side",
    )
    parser.add_argument(
        "--rows", type=int, default=0, help="also print the last N tested matches"
    )
    parser.add_argument("--csv", default=None, help="write every tested match to this file")
    parser.add_argument(
        "--compare-last-n",
        type=int,
        nargs="+",
        default=None,
        help="run once per form window and print a comparison table",
    )
    return parser.parse_args(argv)


def parse_shrinkage(value: str | None):
    """CLI spelling of the shrinkage setting; None means use the .env default."""
    if value is None:
        return "__default__"
    lowered = value.strip().lower()
    if lowered in {"off", "none"}:
        return None
    if lowered == "auto":
        return "auto"
    return float(lowered)


def compare_shrinkage(db, args) -> int:
    """The before-and-after that justifies turning shrinkage on, or not."""
    print("=" * 72)
    print("เทียบผลก่อนและหลังเปิด shrinkage (walk-forward ทั้งสองแบบ)")
    print("=" * 72)
    print(f"{'ตั้งค่า':<22}{'ทายถูก':>10}{'Brier':>10}{'Log loss':>12}{'skill vs ลีกล้วน':>20}")

    rows = []
    for label, shrinkage in (("ปิด (raw ratios)", None), ("auto (empirical Bayes)", "auto")):
        try:
            report = services.run_backtest(
                db,
                league=args.league,
                min_train_matches=args.min_train,
                window=args.window,
                train_window=args.train_window,
                last_n=args.last_n,
                rho=args.rho,
                line=args.line,
                shrinkage=shrinkage,
            )
        except NotEnoughHistoryError as exc:
            logger.error("%s", exc)
            return 1

        cards = report.scorecards()
        model, league_only = cards[0], cards[3]
        skill = model.skill_against(league_only)
        rows.append((label, report, model, skill))
        print(
            f"{label:<22}{report.accuracy * 100:>9.1f}%{model.brier:>10.4f}"
            f"{model.log_loss:>12.4f}{skill:>+20.4f}"
        )

    if len(rows) == 2:
        before, after = rows[0], rows[1]
        delta = before[2].brier - after[2].brier
        print()
        print(f"Brier เปลี่ยนไป {delta:+.4f} (บวก = shrinkage ดีขึ้น)")
        if after[3] > before[3]:
            print("skill score ขยับไปทางบวก ควรเปิด shrinkage ไว้")
        else:
            print("skill score ไม่ดีขึ้น ยังไม่ควรสรุปว่า shrinkage ช่วย")
    return 0


def compare_form_windows(db, args, values: list[int]) -> int:
    """Sweep the form window, so the choice of 20 is checked rather than assumed."""
    print("=" * 72)
    print("เปรียบเทียบขนาดหน้าต่างฟอร์ม (walk-forward ทุกค่า)")
    print("=" * 72)
    print(f"{'ฟอร์มย้อนหลัง':<16}{'ทายถูก':>10}{'Brier':>10}{'Log loss':>12}{'MAE ประตู':>12}")

    best: tuple[float, int] | None = None
    for last_n in values:
        try:
            report = services.run_backtest(
                db,
                league=args.league,
                min_train_matches=args.min_train,
                window=args.window,
                train_window=args.train_window,
                last_n=last_n,
                rho=args.rho,
                line=args.line,
                shrinkage=parse_shrinkage(args.shrinkage),
            )
        except NotEnoughHistoryError as exc:
            logger.error("%s", exc)
            return 1

        card = report.scorecards()[0]
        print(
            f"{last_n:<16}{report.accuracy * 100:>9.1f}%{card.brier:>10.4f}"
            f"{card.log_loss:>12.4f}{report.mean_absolute_goal_error:>12.3f}"
        )
        if best is None or card.brier < best[0]:
            best = (card.brier, last_n)

    if best:
        print()
        print(f"Brier ต่ำสุดที่ฟอร์มย้อนหลัง {best[1]} นัด ({best[0]:.4f})")
        print("ระวัง: การเลือกค่าที่ดีที่สุดจากชุดทดสอบเดียวกันคือการ overfit ตัวพารามิเตอร์")
    return 0


def write_csv(report, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "kickoff",
                "league",
                "home",
                "away",
                "train_size",
                "predicted_total_goals",
                "prob_over",
                "pick",
                "home_goals",
                "away_goals",
                "total_goals",
                "actual",
                "correct",
                "profit",
            ]
        )
        for record in report.records:
            writer.writerow(
                [
                    record.kickoff.isoformat(),
                    record.league,
                    record.home_name,
                    record.away_name,
                    record.train_size,
                    f"{record.predicted_total_goals:.4f}",
                    f"{record.prob_over:.6f}",
                    record.pick,
                    record.actual_home_goals,
                    record.actual_away_goals,
                    record.actual_total_goals,
                    "OVER" if record.actual_over else "UNDER",
                    "" if record.correct is None else int(record.correct),
                    "" if record.profit() is None else f"{record.profit():.4f}",
                ]
            )
    print(f"\nเขียนผลรายนัดลงไฟล์ {path} แล้ว ({len(report.records)} แถว)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.window == "rolling" and not args.train_window:
        print("rolling mode ต้องระบุ --train-window ด้วย", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if args.compare_shrinkage:
            return compare_shrinkage(db, args)

        if args.compare_last_n:
            return compare_form_windows(db, args, args.compare_last_n)

        try:
            report = services.run_backtest(
                db,
                league=args.league,
                min_train_matches=args.min_train,
                window=args.window,
                train_window=args.train_window,
                last_n=args.last_n,
                rho=args.rho,
                line=args.line,
                shrinkage=parse_shrinkage(args.shrinkage),
            )
        except NotEnoughHistoryError as exc:
            logger.error("%s", exc)
            logger.error("ลองรัน python -m app.pipeline.run_ingest เพื่อดึงข้อมูลเพิ่ม")
            return 1

        print(format_report(report, top_rows=args.rows))

        if args.csv:
            write_csv(report, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
