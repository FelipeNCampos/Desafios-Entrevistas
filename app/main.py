"""Entry point for navigation and full-page screenshot capture."""

from __future__ import annotations

import argparse
from datetime import datetime
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.scrap.components.imagem import capture_full_page_base64, save_base64_to_file
from app.scrap.main import save_execution_json, scrape_result_pages
from app.utils.driver import close_driver, create_driver, load_settings
from app.utils.integration.drive import upload_execution_artifacts
from app.utils.integration.notification import send_notification_email
from app.utils.integration.sheets import sync_execution_to_sheet
from app.utils.integration.summary import build_execution_summary
from app.utils.logs import get_logger
from app.utils.navegate import open_base_page
from app.utils.search import SearchPayload, open_refine_search, run_search
from selenium.webdriver.common.by import By


LOGGER = get_logger(__name__)
AVAILABLE_FILTERS = [
    "servidorPublico",
    "beneficiarioProgramaSocial",
    "portadorCPGF",
    "portadorCPDC",
    "sancaoVigente",
    "ocupanteImovelFuncional",
    "possuiContrato",
    "favorecidoRecurso",
    "emitenteNfe",
]


def _run_execution(
    termo: str,
    output_path: str,
    filtros: list[str] | None = None,
    max_results: int | None = None,
) -> dict[str, object]:
    """Execute the automation flow and return structured metadata."""
    settings = load_settings()
    driver = create_driver(settings)
    execution_dir = _create_execution_dir(output_path)
    filtros = filtros or []
    effective_max_results = settings.max_results if max_results is None else max(max_results, 0)
    try:
        open_base_page(driver, settings=settings)
        run_search(driver, SearchPayload(nome=termo, filtros=filtros))
        open_refine_search(driver)
        image_base64 = capture_full_page_base64(driver)
        saved_path = save_base64_to_file(image_base64, str(execution_dir / "00_resultados.png"))
        LOGGER.info("Print salvo em %s", saved_path)
        execution_payload: dict[str, object] = {
            "termo": termo,
            "filtros": filtros,
            "max_resultados": effective_max_results,
            "imagem_resultados_base64": image_base64,
            "resultados": [],
        }

        if _has_results(driver):
            execution_payload["resultados"] = scrape_result_pages(
                driver,
                execution_dir,
                max_results=effective_max_results,
            )
        else:
            LOGGER.info("No result links found for the current search")

        json_path = save_execution_json(execution_payload, execution_dir)
        execution_summary = build_execution_summary(execution_payload, execution_dir)
        drive_result = upload_execution_artifacts(execution_summary)
        if drive_result and drive_result.get("execution_folder_url"):
            execution_summary["drive_folder_url"] = drive_result["execution_folder_url"]
        sheet_result = sync_execution_to_sheet(execution_summary)
        if sheet_result and sheet_result.get("spreadsheet_url"):
            execution_summary["planilha_url"] = sheet_result["spreadsheet_url"]
            execution_summary["planilha_id"] = sheet_result["spreadsheet_id"]

        send_notification_email(
            result=execution_summary,
            subject=f"Resultado da automacao - {termo}",
            attachment_path=json_path,
        )
        LOGGER.info("Base64 gerado com %s caracteres", len(image_base64))
        return {
            "base64": image_base64,
            "execution_dir": str(execution_dir),
            "json_path": str(json_path),
            "summary": execution_summary,
            "payload": execution_payload,
        }
    finally:
        close_driver(driver)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the screenshot flow."""
    parser = argparse.ArgumentParser(
        description="Executa a navegacao, faz a pesquisa e captura o conteudo da pagina."
    )
    parser.add_argument(
        "termo",
        help="Termo pesquisado no campo com id 'termo'.",
    )
    parser.add_argument(
        "--param",
        action="append",
        choices=AVAILABLE_FILTERS,
        default=[],
        help="Filtro adicional da busca. Pode ser informado mais de uma vez.",
    )
    parser.add_argument(
        "--output",
        default="artifacts",
        help="Diretorio base onde a pasta da execucao sera criada.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Limita a quantidade de resultados processados. Use 0 para processar todos.",
    )
    return parser


def _create_execution_dir(base_output_dir: str) -> Path:
    """Create a timestamped directory for the current execution."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    execution_dir = Path(base_output_dir) / timestamp
    execution_dir.mkdir(parents=True, exist_ok=True)
    return execution_dir


def _has_results(driver) -> bool:
    """Check whether the search returned at least one result link."""
    return bool(driver.find_elements(By.CSS_SELECTOR, "#resultados a.link-busca-nome"))


def execute(
    termo: str,
    output_path: str,
    filtros: list[str] | None = None,
    max_results: int | None = None,
) -> str:
    """Open the page, search for the term, and save screenshots for the execution."""
    return str(
        _run_execution(
            termo=termo,
            output_path=output_path,
            filtros=filtros,
            max_results=max_results,
        )["base64"]
    )


def main() -> None:
    """CLI entry point."""
    args = build_parser().parse_args()
    execute(
        termo=args.termo,
        output_path=args.output,
        filtros=args.param,
        max_results=args.max_results,
    )


if __name__ == "__main__":
    main()
