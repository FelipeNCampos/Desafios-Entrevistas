"""Shared helpers for integration-level configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from app.utils.logs import get_logger


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class IntegrationContext:
    google_drive_folder_id: str | None
    google_sheet_id: str | None
    google_sheet_title: str | None
    google_sheet_tab_name: str
    google_oauth_client_secret_file: str | None
    google_oauth_client_secret_json: str | None
    google_oauth_token_file: str
    google_service_account_file: str | None
    google_service_account_json: str | None
    notification_email_to: str | None
    notification_email_from: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_use_tls: bool


@lru_cache(maxsize=1)
def load_integration_context() -> IntegrationContext:
    """Load integration credentials and destinations from the environment."""
    context = IntegrationContext(
        google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID"),
        google_sheet_title=os.getenv("GOOGLE_SHEET_TITLE"),
        google_sheet_tab_name=os.getenv("GOOGLE_SHEET_TAB_NAME", "Resultados").strip() or "Resultados",
        google_oauth_client_secret_file=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE"),
        google_oauth_client_secret_json=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_JSON"),
        google_oauth_token_file=os.getenv("GOOGLE_OAUTH_TOKEN_FILE", ".google-oauth-token.json").strip()
        or ".google-oauth-token.json",
        google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        notification_email_to=os.getenv("NOTIFICATION_EMAIL_TO"),
        notification_email_from=os.getenv("NOTIFICATION_EMAIL_FROM"),
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    LOGGER.info("Integration context loaded")
    return context


def notifications_enabled(context: IntegrationContext | None = None) -> bool:
    """Check whether email notifications are fully configured."""
    active_context = context or load_integration_context()
    return all(
        [
            active_context.smtp_host,
            active_context.notification_email_to,
            active_context.notification_email_from,
        ]
    )


def sheets_enabled(context: IntegrationContext | None = None) -> bool:
    """Check whether Google Sheets integration is configured."""
    active_context = context or load_integration_context()
    return bool(
        active_context.google_oauth_client_secret_file
        or active_context.google_oauth_client_secret_json
        or active_context.google_service_account_file
        or active_context.google_service_account_json
    )


def google_oauth_enabled(context: IntegrationContext | None = None) -> bool:
    """Check whether Google OAuth client credentials are configured."""
    active_context = context or load_integration_context()
    return bool(
        active_context.google_oauth_client_secret_file
        or active_context.google_oauth_client_secret_json
    )


def google_service_account_enabled(context: IntegrationContext | None = None) -> bool:
    """Check whether Google service account credentials are configured."""
    active_context = context or load_integration_context()
    return bool(
        active_context.google_service_account_file
        or active_context.google_service_account_json
    )
