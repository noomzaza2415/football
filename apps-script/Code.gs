/**
 * Google Apps Script receiver for football-ou-analytics.
 *
 * Why a receiver and not a fetcher
 * --------------------------------
 * Apps Script runs on Google's servers, so it cannot reach a backend on your own
 * machine. Neither can =IMPORTDATA(). This script therefore waits to be pushed
 * to: your computer makes the outbound request, which works with localhost and
 * needs no Google Cloud project, no service account and no key file.
 *
 * Setup
 * -----
 * 1. Open the spreadsheet, then Extensions, Apps Script.
 * 2. Replace the contents of Code.gs with this file and save.
 * 3. Run once from the editor (pick the `setup` function) and accept the
 *    permission prompt. This is what authorises the script to edit the sheet.
 * 4. Deploy, New deployment, Web app.
 *      Execute as:        Me
 *      Who has access:    Anyone
 *    "Anyone" is required because your machine calls it without a Google login.
 *    The SECRET below is what keeps the endpoint from being writable by anyone
 *    who guesses the URL, so change it before deploying.
 * 5. Copy the deployment URL, ending in /exec, into backend/.env:
 *
 *      GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/..../exec
 *      GOOGLE_APPS_SCRIPT_TOKEN=the-same-secret-as-below
 *
 * 6. From backend: python -m scripts.push_to_sheets
 *
 * Re-deploy (Manage deployments, edit, Version: New version) after any edit
 * here, or the old code keeps serving.
 */

/** Change this before deploying. Anything long and random will do. */
const SECRET = "change-me-to-something-long-and-random";

/** A tab is wiped and rewritten on each push, so stale rows cannot linger. */
const FREEZE_HEADER_ROW = true;

/**
 * Run this once from the editor to trigger the authorisation prompt.
 * It touches the sheet so Apps Script asks for the permission the web app needs.
 */
function setup() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  Logger.log("Authorised for: " + sheet.getName());
  return sheet.getName();
}

/** A browser visiting the URL gets a status line rather than an error. */
function doGet() {
  return json({
    ok: true,
    service: "football-ou-analytics sheet receiver",
    spreadsheet: SpreadsheetApp.getActiveSpreadsheet().getName(),
    tabs: SpreadsheetApp.getActiveSpreadsheet()
      .getSheets()
      .map(function (sheet) {
        return sheet.getName();
      }),
  });
}

/**
 * Receive one or more tables and write each to its own tab.
 *
 * Expected body:
 *   {
 *     "token": "...",
 *     "tables": [
 *       { "name": "backtest", "header": ["a","b"], "rows": [[1,2],[3,4]] }
 *     ]
 *   }
 */
function doPost(request) {
  let payload;
  try {
    payload = JSON.parse(request.postData.contents);
  } catch (error) {
    return json({ ok: false, error: "body is not valid JSON" }, 400);
  }

  if (payload.token !== SECRET) {
    // Deliberately vague: a wrong token should not reveal whether the URL is right.
    return json({ ok: false, error: "unauthorised" }, 401);
  }

  const tables = payload.tables;
  if (!Array.isArray(tables) || tables.length === 0) {
    return json({ ok: false, error: "no tables in payload" }, 400);
  }

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const written = [];

  for (let i = 0; i < tables.length; i++) {
    const table = tables[i];
    if (!table || !table.name || !Array.isArray(table.header)) {
      return json({ ok: false, error: "a table is missing name or header" }, 400);
    }
    const rows = Array.isArray(table.rows) ? table.rows : [];
    writeTab(spreadsheet, String(table.name), table.header, rows);
    written.push({ name: table.name, rows: rows.length });
  }

  updateStamp(spreadsheet, written);

  return json({ ok: true, written: written });
}

/** Replace one tab's contents, creating it when it does not exist yet. */
function writeTab(spreadsheet, name, header, rows) {
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
  }

  sheet.clear();

  const width = header.length;
  const values = [header];

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i] || [];
    const padded = [];
    // Sheets rejects a ragged range, so every row is padded to the header width.
    for (let column = 0; column < width; column++) {
      const cell = row[column];
      padded.push(cell === null || cell === undefined ? "" : cell);
    }
    values.push(padded);
  }

  sheet.getRange(1, 1, values.length, width).setValues(values);
  sheet.getRange(1, 1, 1, width).setFontWeight("bold");

  if (FREEZE_HEADER_ROW) {
    sheet.setFrozenRows(1);
  }
  sheet.autoResizeColumns(1, Math.min(width, 12));
}

/** A small tab recording when each table last arrived. */
function updateStamp(spreadsheet, written) {
  const name = "_updated";
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
  }

  sheet.clear();
  const values = [["table", "rows", "updated_at"]];
  const stamp = new Date();
  for (let i = 0; i < written.length; i++) {
    values.push([written[i].name, written[i].rows, stamp]);
  }

  sheet.getRange(1, 1, values.length, 3).setValues(values);
  sheet.getRange(1, 1, 1, 3).setFontWeight("bold");
  sheet.setFrozenRows(1);
}

function json(body, status) {
  // Apps Script web apps always answer 200; the ok flag carries the real result,
  // and the status is echoed in the body so the caller can report it.
  if (status) {
    body.status = status;
  }
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(
    ContentService.MimeType.JSON,
  );
}
