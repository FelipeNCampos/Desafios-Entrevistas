"""Shared Google API helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.integration.driver import (
    google_oauth_enabled,
    google_service_account_enabled,
    load_integration_context,
)


GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def load_google_credentials():
    """Load Google credentials, preferring OAuth 2.0 user credentials."""
    context = load_integration_context()
    scopes = [GOOGLE_SHEETS_SCOPE, GOOGLE_DRIVE_SCOPE]

    if google_oauth_enabled(context):
        return _load_google_oauth_credentials(scopes)
    if google_service_account_enabled(context):
        return _load_google_service_account_credentials(scopes)
    raise ValueError(
        "Configure GOOGLE_OAUTH_CLIENT_SECRET_FILE/JSON ou GOOGLE_SERVICE_ACCOUNT_FILE/JSON no arquivo .env."
    )


def _load_google_oauth_credentials(scopes: list[str]):
    """Load or bootstrap OAuth 2.0 user credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    context = load_integration_context()
    token_path = Path(context.google_oauth_token_file)
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), scopes=scopes)

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _persist_oauth_credentials(credentials, token_path)
        return credentials

    flow = _build_oauth_flow(scopes)
    credentials = flow.run_local_server(port=0)
    _persist_oauth_credentials(credentials, token_path)
    return credentials


def _build_oauth_flow(scopes: list[str]):
    """Build the installed-app OAuth flow from file or inline JSON."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    context = load_integration_context()
    if context.google_oauth_client_secret_file:
        return InstalledAppFlow.from_client_secrets_file(
            context.google_oauth_client_secret_file,
            scopes=scopes,
        )
    if context.google_oauth_client_secret_json:
        config = json.loads(context.google_oauth_client_secret_json)
        return InstalledAppFlow.from_client_config(config, scopes=scopes)
    raise ValueError(
        "Configure GOOGLE_OAUTH_CLIENT_SECRET_FILE ou GOOGLE_OAUTH_CLIENT_SECRET_JSON no arquivo .env."
    )


def _persist_oauth_credentials(credentials, token_path: Path) -> None:
    """Persist OAuth credentials for reuse in the next runs."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def _load_google_service_account_credentials(scopes: list[str]):
    """Load Google service account credentials from file or JSON."""
    from google.oauth2.service_account import Credentials

    context = load_integration_context()
    if context.google_service_account_file:
        return Credentials.from_service_account_file(
            context.google_service_account_file,
            scopes=scopes,
        )
    if context.google_service_account_json:
        info = json.loads(context.google_service_account_json)
        return Credentials.from_service_account_info(info, scopes=scopes)
    raise ValueError(
        "Configure GOOGLE_SERVICE_ACCOUNT_FILE ou GOOGLE_SERVICE_ACCOUNT_JSON no arquivo .env."
    )


def build_google_service(api_name: str, version: str, credentials):
    """Instantiate a Google API client."""
    from googleapiclient.discovery import build

    return build(api_name, version, credentials=credentials, cache_discovery=False)
