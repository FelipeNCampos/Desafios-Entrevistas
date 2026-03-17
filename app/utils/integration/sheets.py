"""Google Sheets integration helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from app.utils.integration.driver import load_integration_context, sheets_enabled
from app.utils.integration.google import build_google_service, load_google_credentials
from app.utils.integration.summary import SHEET_HEADERS, build_sheet_rows
from app.utils.logs import get_logger


LOGGER = get_logger(__name__)


def sync_execution_to_sheet(summary: Mapping[str, object]) -> dict[str, object] | None:
    """Create or reuse a spreadsheet and append the current execution rows."""
    context = load_integration_context()
    if not sheets_enabled(context):
        LOGGER.info("Google Sheets sync skipped because Google credentials are not configured")
        return None

    credentials = load_google_credentials()
    sheets_service = build_google_service("sheets", "v4", credentials)
    drive_service = build_google_service("drive", "v3", credentials)

    spreadsheet = _ensure_spreadsheet(sheets_service, drive_service, context)
    sheet_name = spreadsheet["sheet_name"]
    spreadsheet_id = spreadsheet["spreadsheet_id"]

    _ensure_header_row(sheets_service, spreadsheet_id, sheet_name)
    rows = build_sheet_rows(dict(summary))
    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    result = {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet["spreadsheet_url"],
        "sheet_name": sheet_name,
        "rows_appended": len(rows),
    }
    LOGGER.info("Execution summary appended to Google Sheets: %s rows", len(rows))
    return result


def _ensure_spreadsheet(sheets_service, drive_service, context) -> dict[str, str]:
    """Create a spreadsheet when needed and ensure it is placed in the target Drive folder."""
    if context.google_sheet_id:
        metadata = sheets_service.spreadsheets().get(
            spreadsheetId=context.google_sheet_id
        ).execute()
        spreadsheet_id = metadata["spreadsheetId"]
        spreadsheet_url = metadata.get(
            "spreadsheetUrl",
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        )
        sheet_name = _ensure_sheet_tab(
            sheets_service,
            spreadsheet_id,
            metadata,
            context.google_sheet_tab_name,
        )
        return {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": spreadsheet_url,
            "sheet_name": sheet_name,
        }

    spreadsheet_title = (
        context.google_sheet_title
        or f"Resultados Automacao {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
    )
    sheet_name = context.google_sheet_tab_name or "Resultados"
    metadata = sheets_service.spreadsheets().create(
        body={
            "properties": {"title": spreadsheet_title},
            "sheets": [{"properties": {"title": sheet_name}}],
        }
    ).execute()
    spreadsheet_id = metadata["spreadsheetId"]
    spreadsheet_url = metadata.get(
        "spreadsheetUrl",
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
    )

    if context.google_drive_folder_id:
        parents = drive_service.files().get(
            fileId=spreadsheet_id,
            fields="parents",
            supportsAllDrives=True,
        ).execute().get("parents", [])
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=context.google_drive_folder_id,
            removeParents=",".join(parents),
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()

    LOGGER.info("Google Sheets spreadsheet created: %s", spreadsheet_id)
    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "sheet_name": sheet_name,
    }


def _resolve_sheet_name(metadata, preferred_name: str) -> str:
    """Return the preferred sheet tab when present or the first existing one."""
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == preferred_name:
            return preferred_name

    sheets = metadata.get("sheets", [])
    if sheets:
        return str(sheets[0].get("properties", {}).get("title") or preferred_name)
    return preferred_name


def _ensure_sheet_tab(
    sheets_service,
    spreadsheet_id: str,
    metadata,
    preferred_name: str,
) -> str:
    """Return the target sheet tab and create it when it does not exist."""
    existing_name = _resolve_sheet_name(metadata, preferred_name)
    if existing_name == preferred_name:
        return preferred_name

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": preferred_name,
                        }
                    }
                }
            ]
        },
    ).execute()
    LOGGER.info("Google Sheets tab created: %s", preferred_name)
    return preferred_name


def _ensure_header_row(sheets_service, spreadsheet_id: str, sheet_name: str) -> None:
    """Create or reconcile the header row with the current sheet schema."""
    header_range = f"{sheet_name}!A1:{_column_letter(len(SHEET_HEADERS))}1"
    response = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=header_range,
    ).execute()
    current_header = response.get("values", [[]])[0]
    if current_header == SHEET_HEADERS:
        return

    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": [SHEET_HEADERS]},
    ).execute()
    if current_header:
        LOGGER.info("Google Sheets header row updated to the latest schema")
    else:
        LOGGER.info("Google Sheets header row created")


def _column_letter(column_number: int) -> str:
    """Convert a 1-based column index to the corresponding sheet column letter."""
    result = []
    current = column_number
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))
