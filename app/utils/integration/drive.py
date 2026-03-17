"""Google Drive helpers for uploading execution artifacts."""

from __future__ import annotations

from collections.abc import Mapping
import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from app.utils.integration.driver import load_integration_context, sheets_enabled
from app.utils.integration.google import build_google_service, load_google_credentials
from app.utils.logs import get_logger


LOGGER = get_logger(__name__)


def upload_execution_artifacts(summary: dict[str, object]) -> dict[str, object] | None:
    """Upload execution artifacts to Google Drive and enrich the summary with folder links."""
    context = load_integration_context()
    if context.skip_drive_upload:
        LOGGER.info("Google Drive upload skipped (SKIP_DRIVE_UPLOAD=true)")
        return None
    if not sheets_enabled(context):
        LOGGER.info("Google Drive upload skipped because Google credentials are not configured")
        return None

    try:
        credentials = load_google_credentials()
        drive_service = build_google_service("drive", "v3", credentials)
        execution_folder = _create_folder(
            drive_service=drive_service,
            name=f"execucao_{summary.get('execucao_id', 'resultado')}",
            parent_id=context.google_drive_folder_id,
        )

        for path in summary.get("arquivos_execucao", []):
            _upload_file_if_exists(drive_service, Path(path), execution_folder["id"])

        uploaded_individual_folders = 0
        for resultado in summary.get("resultados", []):
            artifact_paths = [Path(path) for path in resultado.get("artifact_paths", [])]
            if not artifact_paths:
                continue
            folder = _create_folder(
                drive_service=drive_service,
                name=_build_result_folder_name(resultado),
                parent_id=execution_folder["id"],
            )
            for path in artifact_paths:
                _upload_file_if_exists(drive_service, path, folder["id"])
            resultado["drive_folder_url"] = folder["url"]
            uploaded_individual_folders += 1

        summary["drive_folder_url"] = execution_folder["url"]
        LOGGER.info("Google Drive upload completed with %s result folders", uploaded_individual_folders)
        return {
            "execution_folder_id": execution_folder["id"],
            "execution_folder_url": execution_folder["url"],
            "uploaded_result_folders": uploaded_individual_folders,
        }
    except Exception as exc:
        LOGGER.warning("Google Drive upload failed and will be skipped: %s", exc)
        return None


def _build_result_folder_name(resultado: Mapping[str, object]) -> str:
    """Create a stable folder name per individual result."""
    nome = _slugify(str(resultado.get("nome") or "resultado"))
    cpf = _slugify(str(resultado.get("cpf") or "sem-cpf"))
    return f"{nome}_{cpf}"


def _slugify(value: str) -> str:
    """Create a filesystem-safe folder name."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "resultado"


def _create_folder(drive_service, name: str, parent_id: str | None = None) -> dict[str, str]:
    """Create a folder in Google Drive."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = drive_service.files().create(
        body=metadata,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()
    return {
        "id": folder["id"],
        "url": folder.get("webViewLink", f"https://drive.google.com/drive/folders/{folder['id']}"),
    }


def _upload_file_if_exists(drive_service, path: Path, parent_id: str) -> None:
    """Upload one local file to Google Drive when it exists."""
    if not path.exists() or not path.is_file():
        LOGGER.info("Skipping Drive upload for missing file %s", path)
        return

    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(path), resumable=False)
    drive_service.files().create(
        body={
            "name": path.name,
            "parents": [parent_id],
        },
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
