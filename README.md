# Football Over/Under Analytics

A Poisson goal model for football Over/Under markets, with a FastAPI backend and
a Next.js dashboard. It fits attack and defense strengths from recent results,
turns them into a full scoreline probability matrix, and compares the model's
Over/Under probabilities with a posted market price.

> **Educational statistical analysis only.** Everything this project produces is
> a model estimate, not a prediction of what will happen and not a guarantee of
> any result. A model fitted on a few hundred matches will be wrong often. Using
> its output to bet real money carries financial risk and you can lose your
> stake. Nothing here is financial advice.

---

## What it does

1. **Ingest** results and fixtures from football-data.org or API-Football.
2. **Aggregate** each team's goals scored and conceded, split by home and away.
3. **Fit** attack and defense strengths relative to the league average.
4. **Predict** expected goals for a fixture, then build a 7x7 scoreline matrix
   with `scipy.stats.poisson`.
5. **Compare** the resulting Over/Under probabilities with the market price,
   with the bookmaker margin removed.
6. **Score** stored predictions against real results so the model's accuracy and
   calibration are visible rather than assumed.

---

## Requirements

| Tool | Version |
| --- | --- |
| Python | 3.11 or newer (tested on 3.11 and 3.14) |
| Node.js | 20 or newer |
| PostgreSQL | 14 or newer, or Docker |

---

## Quick start

Real Premier League data, no API key and no PostgreSQL server needed. The
default source is football-data.co.uk, a public CSV archive.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

cp .env.example .env            # optional; the defaults already work

# Five seasons of real results, with real Over/Under closing prices
DATABASE_URL="sqlite:///./real.db" python -m app.pipeline.run_ingest     --provider football-data-uk --competitions E0     --seasons 2022 2023 2024 2025 2026 --refresh-predictions

DATABASE_URL="sqlite:///./real.db" uvicorn app.main:app --reload --port 8000
```

There is also a simulated seed for when you want a database without touching
the network, `python -m scripts.seed_demo --drop-all`. Its market prices are
random numbers, so the value edges it shows are meaningless.

```bash
# 2. Frontend, in a second terminal
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open <http://localhost:3000>. The API docs are at <http://localhost:8000/docs>.

---

## Real setup

### 1. Database

With Docker:

```bash
export POSTGRES_PASSWORD='pick-something-strong'
docker compose up -d db
```

Or point `DATABASE_URL` at any PostgreSQL you already run. The tables are
created automatically in development; see *Migrations* below for production.

### 2. Environment variables

Copy `backend/.env.example` to `backend/.env` and fill it in. Nothing is
hardcoded and `.env` is gitignored.

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/football_ou` |
| `DATA_PROVIDER` | `football-data` or `api-football` |
| `FOOTBALL_DATA_API_KEY` | Free key from football-data.org |
| `API_FOOTBALL_API_KEY` | Key from api-football.com |
| `COMPETITIONS` | `PL` or `PL,BL1,SA` for football-data; `39,140` for API-Football |
| `SEASONS_BACK` | How many seasons of history to pull |
| `MODEL_LAST_N_MATCHES` | Form window per team, 20 by default |
| `MODEL_RHO` | Dixon-Coles low-score correction, `0` disables it |
| `MODEL_SHRINKAGE` | `auto`, `off`, or a constant in matches. Leave on `auto` |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Optional. Service account JSON key for the Sheets export |
| `GOOGLE_SHEET_ID` | Optional. The id from the spreadsheet URL |
| `MODEL_LINES` | Lines to compute, `1.5,2.5,3.5` by default |
| `CORS_ORIGINS` | Where the frontend is served from |

The frontend needs one variable in `frontend/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
```

### 3. Data sources

Three are supported. Only the first needs no account.

| Provider | Key | Covers | Over/Under prices |
| --- | --- | --- | --- |
| `football-data-uk` | none | 20+ European divisions, back to the 1990s, plus a weekly fixtures file | **Yes**, opening and closing |
| `football-data` | free key | Major European leagues, fixtures and results | No, odds are a paid add-on |
| `api-football` | paid key | Very wide coverage, plus lineups and injuries | Depends on the plan |

`football-data-uk` is the default because it is the only free source here
carrying real Over/Under 2.5 bookmaker prices. Without those, the market
comparison on the match page and the market baseline in the backtest have
nothing real to compare against, and the model cannot be judged properly.

Its division codes are letters: `E0` Premier League, `E1` Championship, `D1`
Bundesliga, `SP1` La Liga, `I1` Serie A, `F1` Ligue 1, `N1` Eredivisie.

```bash
cd backend
python -m app.pipeline.run_ingest --provider football-data-uk     --competitions E0 --seasons 2022 2023 2024 2025 2026 --refresh-predictions
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--provider` | Override `DATA_PROVIDER` for one run |
| `--competitions PL BL1` | Override the competition list |
| `--seasons 2023 2024` | Season start years |
| `--skip-stats` | Do not rebuild `team_stats` afterwards |
| `--refresh-predictions` | Store a prediction for every upcoming match |

Every write is keyed on `(external_id, source)`, so re-running the ingest
updates rows rather than duplicating them. football-data.co.uk publishes no
match ids, so the key there is division, season, home and away team; an
upcoming fixture takes its season from its own kick-off date rather than from
the season being ingested, or every season ingested would add another copy of
it. The free football-data.org tier allows ten requests a minute, which is why
that client sleeps between calls.

### 4. Schedule it

A daily run is enough: fixtures move slowly and results land within hours.

- **Linux or macOS**: `backend/scripts/ingest_cron.sh`, wired up with `crontab -e`.
- **Windows**: `backend/scripts/ingest_task.ps1`, registered with
  `Register-ScheduledTask`.

Both scripts contain their own install instructions in the header and read the
API key from `.env` rather than from the schedule definition.

---

## The model

### Team strength

For each team, over its last `MODEL_LAST_N_MATCHES` games:

```
attack_home  = (goals scored at home    per game) / (league average home goals)
defense_home = (goals conceded at home  per game) / (league average away goals)
attack_away  = (goals scored away       per game) / (league average away goals)
defense_away = (goals conceded away     per game) / (league average home goals)
```

A value of 1.0 is exactly average. Ratios are clamped to the range 0.25 to 3.0
so one freak scoreline in a short sample cannot distort the next fixture, and a
team with fewer than three games at a venue falls back to 1.0 for that venue,
which collapses its expected goals to the league average rather than to noise.

### Shrinkage

A raw ratio is a mean of a handful of Poisson draws over a league average, so
it carries a lot of estimation noise. Walk-forward testing showed that noise
costing more than the signal earned, so every ratio is pulled back toward 1.0
in proportion to how thin the evidence behind it is:

```
strength = 1 + k * (raw_ratio - 1)        k = n / (n + c)
```

`c` is derived rather than tuned. For a role whose league average is `L`, a
mean over `n` Poisson draws has variance `L / n`, so the ratio's noise variance
is `1 / (n * L)`. The spread observed across teams is signal plus noise, so
subtracting the noise leaves the signal and `c = 1 / (L * signal)`. That is the
standard empirical-Bayes result. Deriving it avoids picking `c` from the same
backtest used to judge the model, which is the overfitting the walk-forward
test exists to prevent.

The observed variance is itself estimated from only `k` teams, and a sample
variance has a relative standard error of about `sqrt(2 / (k - 1))`: roughly
82% at four teams, 32% at twenty. Taking it at face value in a small league
invents signal that is not there, so it is discounted by one standard error
first. The two errors are not symmetric. Overstating the signal brings back the
noisy model, while understating it falls back to the league-average baseline,
which is the safer failure.

Set `MODEL_SHRINKAGE=off` to recover the raw ratios and the older behaviour.

### Expected goals

```
lambda_home = attack_home(home) * defense_away(away) * league_average_home_goals
lambda_away = attack_away(away) * defense_home(home) * league_average_away_goals
```

### Scoreline matrix

Both scorelines are treated as independent Poisson variables, so the joint
probability of an exact score is the product of the two marginals. The matrix
covers 0-0 to 6-6 by default and is renormalised to sum to 1, which folds the
small tail beyond six goals back into the grid.

Summing cells gives everything else: Over/Under at any line, the full total goals
distribution, the 1X2 split and the most likely scoreline.

### Dixon-Coles correction

Independent Poisson is known to underrate 0-0 and 1-1. Setting `MODEL_RHO` to a
small negative number (-0.05 to -0.15 is the usual fitted range) applies the
Dixon-Coles adjustment to the four lowest scorelines. Set it to 0 to disable.

### Odds and value

Decimal odds convert to an implied probability with `1 / odds`. The two sides of
a market always sum to more than 100%; that surplus is the bookmaker margin. The
API strips it proportionally before comparing, so the reported edge is the model
against a fair price rather than against the margin.

An edge means the model and the market disagree. On a sample this size, that is
usually the model being wrong.

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Row counts and model version |
| `GET` | `/api/teams` | Every team, filterable by `league` and `search` |
| `GET` | `/api/teams/{id}` | One team |
| `GET` | `/api/teams/{id}/stats` | Aggregates and fitted strengths |
| `POST` | `/api/teams/rebuild-stats` | Recompute `team_stats` from `matches` |
| `GET` | `/api/matches/day` | One matchday. Omit `day` for the nearest one |
| `GET` | `/api/matches/calendar` | Which days have matches, for the date picker |
| `GET` | `/api/matches/range` | Matches between two dates, up to 60 days |
| `GET` | `/api/matches/upcoming` | Scheduled matches with a short model summary |
| `GET` | `/api/matches/{id}` | One match |
| `GET` | `/api/matches/{id}/prediction` | Full analysis and market comparison |
| `POST` | `/api/matches/{id}/refresh-prediction` | Re-run the model and store it |
| `GET` | `/api/predictions/history` | Stored predictions scored against results |
| `GET` | `/api/predictions/backtest` | Walk-forward backtest against four baselines |
| `GET` | `/api/news` | Headlines from public RSS feeds, Thai and international |
| `GET` | `/api/news/match/{id}` | Headlines naming either side of one fixture |
| `GET` | `/api/export/{table}.csv` | matches, predictions, backtest or team_stats as CSV |

`GET /api/matches/{id}/prediction?point_in_time=true` refits using only matches
that finished before kick-off, which is what makes a backtest honest.

`POST /api/matches/{id}/refresh-prediction` accepts an optional body to override
the model for one run:

```json
{ "last_n": 15, "max_goals": 8, "rho": -0.1, "lines": [1.5, 2.5, 3.5, 4.5] }
```

Interactive docs are at `/docs`.

---

## Database schema

| Table | Contents |
| --- | --- |
| `teams` | Name, league, country, crest, provider id |
| `matches` | Both sides, kick-off, league, status, goals, optional market prices |
| `team_stats` | Aggregates and fitted strengths, rebuilt from `matches` |
| `predictions` | One row per model run: expected goals, line probabilities, distribution |

`team_stats` is a materialised view in table form: everything in it can be
recomputed from `matches` with `POST /api/teams/rebuild-stats`. `predictions` is
an append-only log, which is what lets the performance page score old runs.

---

## Frontend

| Route | Contents |
| --- | --- |
| `/` | One matchday: every fixture on a chosen day, with expected goals and the Over/Under split |
| `/?day=YYYY-MM-DD` | That day instead. Arrows skip to the next and previous day that has football |
| `/matches/[id]` | Expected goals, total-goals distribution chart, line table, market comparison, likely scorelines, related headlines |
| `/performance` | Walk-forward results against four baselines, hit rate over time, calibration |

### The matchday view

The home page opens on the day that matters now: the next day with fixtures, or
the most recent day with results once the fixture list runs out. Football is not
played every day, so defaulting to today would usually show an empty page, and
the arrows jump between days that actually have matches rather than stepping by
24 hours.

A **past** day shows what the model would have said **before kick-off**. Each
finished match is refitted on matches that kicked off earlier and nothing else,
and the card is labelled to say so. Showing the current model against a result
it has already absorbed would make the page look far better than the model is.

### How current the data is

The page states the age of the stored data and refreshes itself every two
minutes, which the reader can switch off. What it cannot do is be live: the
sources publish on their own schedule, so a freshly rendered page can hold data
that is a day old. The bar says when the last ingest ran rather than implying a
live feed. For fresher numbers, run the ingest again.

### News

Headlines come from public RSS feeds, three international and four Thai. RSS is
published for software to read, unlike scraping a page, which breaks on every
redesign and is generally against a site's terms.

Thai publishers mostly offer a combined sport feed, so those items are filtered
by football keywords before being shown.

**No headline reaches the model.** There is no defined path from "the striker is
a doubt" to a number of expected goals, and inventing one would produce output
nobody could check. The backtest already shows the model has no edge over a
league average; an unvalidated adjustment would make it worse and unmeasurable.
Headlines sit beside the analysis as context for the reader, and the panel says
so. If injuries are to inform the model, the route is structured injury data
plus an adjustment whose value the backtest demonstrates.

Dark dashboard theme. The chart colours are a validated set: Over is warm, Under
is cool, every adjacent pair clears the colour-vision-deficiency separation
threshold against the chart surface, and both sides always carry a text label so
nothing depends on hue alone. Every page carries the disclaimer.

---

## Tests

```bash
cd backend
pytest              # 215 tests
pytest --cov=app    # with coverage
```

Coverage is on the parts where a silent error would be worst:

- `tests/test_poisson_model.py` checks the matrix sums to 1, that Over and Under
  are complementary on a half line and push on a whole line, that Over falls as
  the line rises, that strengths are clamped, and that Over 2.5 matches a hand
  computed value for two unit lambdas.
- `tests/test_odds.py` checks implied probability, margin removal, edge and
  expected value, and the Kelly cap.
- `tests/test_stats_builder.py` checks the venue split, form string and rates.
- `tests/test_providers.py` and `tests/test_provider_uk.py` parse recorded
  upstream payloads, covering the messy cases: undrawn cup ties, postponed
  matches, blank price columns, paged responses, and a rolling fixtures file
  that must not duplicate itself once per season ingested. No network access.
- `tests/test_shrinkage.py` checks that shrinkage never overshoots past 1.0,
  trusts larger samples more, preserves the ordering of teams, and reproduces
  the league-average baseline exactly at its `k = 0` extreme.
- `tests/test_backtest.py` checks the walk-forward engine, above all that no
  match can influence its own prediction: rewriting the final result leaves
  every earlier prediction byte-identical, and shuffling the input order
  changes nothing because the engine sorts by kick-off itself.
- `tests/test_api.py` and `tests/test_backtest_api.py` run every endpoint
  against an in-memory SQLite database, so they need neither PostgreSQL nor an
  API key.

---

## Walk-forward backtesting

`pytest` proves the maths is right. It says nothing about whether the model
predicts anything. That is what the walk-forward backtest is for.

The procedure is strictly chronological. Matches are sorted by kick-off, the
first `--min-train` are used only to warm up, and then for every remaining
match the model is refitted **using only matches that kicked off before it**,
asked for a prediction, and scored once the result is revealed. No match, and
nothing after it, can reach the fit that predicts it.

```bash
cd backend
python -m scripts.run_backtest --min-train 60 --rows 10
```

| Flag | Effect |
| --- | --- |
| `--min-train N` | Matches used to warm up before the first prediction |
| `--window rolling --train-window N` | Train on only the last N matches instead of all history |
| `--last-n N` | Form window per team |
| `--rho R` | Dixon-Coles correction |
| `--line L` | Line to test, 2.5 by default |
| `--compare-last-n 8 12 20 40` | Sweep the form window and print a comparison |
| `--csv out.csv` | Write every tested match for your own analysis |
| `--shrinkage auto`, `off`, `N` | Override `MODEL_SHRINKAGE` for one run |
| `--compare-shrinkage` | Run with shrinkage off and on, side by side |

The same run is available at `GET /api/predictions/backtest` and is rendered
on the performance page.

### Why a hit rate is not the headline

If 74% of matches go over 2.5, a model that always says Over scores 74% and
knows nothing. So every run is scored against four baselines on exactly the
same matches, using Brier score and log loss rather than accuracy:

| Baseline | What it is |
| --- | --- |
| always over | Predict Over every time |
| base rate | Predict the Over rate observed so far |
| league only | The same Poisson machinery with every team forced to average strength |
| market | The posted price with the margin removed, where odds exist |

The `league only` row is the one that matters most: it isolates exactly what
the attack and defense strength step adds, because everything else about the
two forecasters is identical.

### What the backtest currently says

### Results on real data

Five Premier League seasons, 1950 matches, 1150 of them predicted out of
sample with a 400 match warm-up. Real closing prices throughout.

| Forecaster | Brier | Log loss |
| --- | --- | --- |
| Model | 0.2448 | 0.6828 |
| Always over | 0.4140 | 2.8658 |
| Historical over rate | 0.2438 | 0.6807 |
| Poisson, league average only | 0.2435 | 0.6800 |
| **Market, margin removed** | **0.2384** | **0.6695** |

Three things follow, and none of them are flattering.

**The model ties its own baselines.** Skill against the league-average Poisson
is -0.005, near enough to zero. Knowing each team's attack and defense adds
almost nothing over assuming every team is average, once the estimate is
honest about how little evidence stands behind it.

**The model loses to the market.** Skill against the vig-free closing price is
-0.027. The market is a better forecaster of total goals than this model, which
is the expected result and worth stating plainly.

**Flat staking loses money.** Backing every non-neutral pick at the closing
price returns about -3.5% per unit over 1042 bets. That is roughly the
bookmaker margin, which is what a model with no edge is supposed to produce.

### Why shrinkage is on

Without it the model is worse still. On simulated leagues drawn from known
fixed team ratings, Brier skill against `league only` was clearly negative at
every history size, and shrinkage removes almost all of that loss:

| History | Skill, shrinkage off | Skill, shrinkage auto |
| --- | --- | --- |
| 600 | -0.0375 | -0.0004 |
| 1200 | -0.0406 | +0.0001 |
| 2400 | -0.0482 | -0.0041 |
| 4000 | -0.0481 | -0.0068 |

It buys back the loss; it does not buy an edge.

Two things explain the ceiling. The estimator is unbiased, so the original gap
was estimation noise, and shrinkage is the correct remedy for exactly that. But
totals are also intrinsically hard: a strong attack meeting a strong defense
cancels out, so total expected goals varies far less than either side's does,
and there is less for team strength to explain than there would be in a match
result or handicap market.

Treat this as the honest current state of the project rather than a formality.
Anyone extending the model should re-run both checks and confirm the skill
score moves the right way:

```bash
python -m scripts.run_backtest --min-train 400
python -m scripts.run_backtest --compare-shrinkage
```

---

## Google Sheets

Two routes, depending on whether the API is reachable from the internet.

**Download and import.** Every table is available as CSV:

| Table | Contents |
| --- | --- |
| `matches` | Every match, its result and the stored market prices |
| `predictions` | Each stored forecast beside the result it was scored against |
| `backtest` | One row per out-of-sample match from a walk-forward run |
| `team_stats` | Per-team aggregates and fitted strengths |

```
http://localhost:8000/api/export/backtest.csv
```

Then File, Import in Sheets. `backtest` is the one worth analysing: one row per
match the model had never seen, with what it said and what happened.

**Write to the sheet directly.** `scripts/export_to_sheets.py` writes each table
to its own worksheet tab, so a chart or pivot built on a tab keeps working after
the next run. It needs a Google service account:

1. In Google Cloud, create a project and enable the Google Sheets API.
2. Create a service account and download its JSON key.
3. Share the spreadsheet as **Editor** with the service account's
   `...@....iam.gserviceaccount.com` address. Skipping this is the usual cause
   of a 403: the service account is a separate identity from your own account.
4. Set `GOOGLE_SERVICE_ACCOUNT_FILE` and `GOOGLE_SHEET_ID` in `backend/.env`,
   keeping the key file outside the repository.

```bash
pip install gspread google-auth
python -m scripts.export_to_sheets --dry-run   # check the tables first
python -m scripts.export_to_sheets
```

A formula such as `=IMPORTDATA("https://host/api/export/backtest.csv")` also
works, but only once the API is published: Google's servers fetch that URL, so
they cannot reach a server on your own machine.

---

## Migrations

Tables are created automatically when `ENVIRONMENT=development`. For anything
else, use Alembic, which is already a dependency:

```bash
cd backend
alembic init migrations       # once
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## Project layout

```
backend/
  app/
    analytics/
      poisson_model.py    # league averages, strengths, shrinkage, Over/Under
      backtest.py         # walk-forward engine, baselines, scoring
      odds.py             # implied probability, vig removal, edge, Kelly
      stats_builder.py    # team_stats aggregation
    exporters.py          # flat tables for CSV and Google Sheets
    pipeline/
      news.py             # RSS reader, never model input
      providers/          # football-data.co.uk CSV, football-data.org, API-Football
      etl.py              # idempotent upserts
      run_ingest.py       # CLI entry point for cron
    routers/              # teams, matches, predictions
    models.py             # SQLAlchemy ORM
    schemas.py            # Pydantic response models
    services.py           # database to model and back
    config.py             # settings from environment variables
    main.py               # FastAPI app
  scripts/
    seed_demo.py          # simulated data, no API key needed
    run_backtest.py       # walk-forward backtest CLI
    export_to_sheets.py   # write the tables into a Google Sheet
    ingest_cron.sh        # Linux and macOS schedule
    ingest_task.ps1       # Windows schedule
  tests/
frontend/
  app/                    # home, match detail, performance
  components/
    charts/               # recharts components, shared theme
  lib/                    # typed API client, formatters, types
docker-compose.yml        # PostgreSQL for development
```

---

## Limitations

Worth knowing before reading anything into the output:

- **Goals only, no players at all.** The database has no player table. Lineups,
  injuries, suspensions, red cards, rest days, weather, travel and fixture
  congestion are all invisible to the model. A team losing its first-choice
  striker and its first-choice keeper on the same day changes nothing in the
  numbers this project produces, which is a serious omission for a totals
  model. See the backtest section: this is one plausible reason the model
  cannot separate itself from a league-average baseline.
- **Independence.** Poisson assumes the two teams' goal counts are independent,
  which they are not. The Dixon-Coles term patches the worst of it at low scores.
- **Flat form window.** The last 20 matches all count equally; a result from
  eight months ago weighs as much as last week's.
- **Thin samples.** Early in a season the strengths are mostly noise. The API
  reports how many matches a fit used, and the UI shows it.
- **No closing line.** Without stored market prices there is no way to tell
  whether an edge was real or the model simply disagreed with a sharper number.
#   f o o t b a l l 
 
 