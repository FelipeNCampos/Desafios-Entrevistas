"""Shared summary builders for email and Google Sheets integrations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


SHEET_HEADERS = [
    "Execucao ID",
    "Gerado Em",
    "Termo",
    "Filtros",
    "Quantidade Resultados",
    "Nome",
    "CPF",
    "Localidade",
    "Recebimentos",
    "Total Recebimentos",
    "Captcha Detectado",
    "Pasta Execucao",
    "Pasta Resultado Drive",
    "URL Resultado",
]


def _extract_recebimentos(resultado: dict[str, object]) -> list[dict[str, object]]:
    """Read receipt resources from the panorama payload."""
    recebimentos: list[dict[str, object]] = []
    for item in resultado.get("panorama", []):
        if item.get("item") != "Recebimentos de recursos":
            continue
        for recurso in item.get("recursos", []):
            recebimentos.append(
                {
                    "nome": recurso.get("nome"),
                    "valor": recurso.get("valor"),
                }
            )
    return recebimentos


def _format_filters(filters: list[str] | None) -> str:
    """Format the filter list for display."""
    if not filters:
        return "-"
    return ", ".join(filters)


def _format_recebimentos(recebimentos: list[dict[str, object]]) -> str:
    """Format receipt items for email and Sheets."""
    if not recebimentos:
        return "-"
    parts = []
    for item in recebimentos:
        nome = str(item.get("nome") or "Recurso")
        valor = item.get("valor")
        if valor in {None, ""}:
            parts.append(nome)
        else:
            parts.append(f"{nome}: {valor}")
    return " | ".join(parts)


def _sum_recebimentos(recebimentos: list[dict[str, object]]) -> float:
    """Calculate the numeric sum of receipt values."""
    total = 0.0
    for item in recebimentos:
        valor = item.get("valor")
        if isinstance(valor, (int, float)):
            total += float(valor)
            continue
        if isinstance(valor, str):
            normalized = valor.replace("R$", "").replace(".", "").replace(",", ".").strip()
            try:
                total += float(normalized)
            except ValueError:
                continue
    return round(total, 2)


def _collect_result_artifact_paths(resultado: dict[str, object]) -> list[str]:
    """Collect all local artifact paths related to one result."""
    paths: list[str] = []
    image_path = str(resultado.get("imagem_path") or "").strip()
    if image_path:
        paths.append(image_path)

    for detalhe in resultado.get("detalhes_recebimentos", []):
        for screenshot_path in detalhe.get("screenshots", []):
            normalized = str(screenshot_path or "").strip()
            if normalized:
                paths.append(normalized)

    unique_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return unique_paths


def _result_has_captcha(resultado: dict[str, object]) -> bool:
    """Return True when the main page or any detail page detected CAPTCHA."""
    if bool(resultado.get("captcha_detectado")):
        return True
    return any(
        bool(detalhe.get("captcha_detectado"))
        for detalhe in resultado.get("detalhes_recebimentos", [])
    )


def build_execution_summary(
    execution_payload: dict[str, object],
    execution_dir: Path,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Create a reusable summary payload for email and Sheets."""
    generated_at = generated_at or datetime.now()
    filtros = list(execution_payload.get("filtros", []))
    resultados_resumo: list[dict[str, object]] = []

    for resultado in execution_payload.get("resultados", []):
        recebimentos = _extract_recebimentos(resultado)
        recebimentos_total = _sum_recebimentos(recebimentos)
        resultados_resumo.append(
            {
                "nome": resultado.get("nome") or "",
                "cpf": resultado.get("cpf") or "",
                "localidade": resultado.get("localidade") or "",
                "recebimentos_de_recursos": recebimentos,
                "recebimentos_resumo": _format_recebimentos(recebimentos),
                "recebimentos_total": recebimentos_total,
                "captcha_detectado": _result_has_captcha(resultado),
                "drive_folder_url": None,
                "artifact_paths": _collect_result_artifact_paths(resultado),
                "url": resultado.get("url") or "",
            }
        )

    return {
        "execucao_id": execution_dir.name,
        "gerado_em": generated_at.isoformat(timespec="seconds"),
        "termo": execution_payload.get("termo"),
        "filtros": filtros,
        "filtros_resumo": _format_filters(filtros),
        "quantidade_resultados": len(execution_payload.get("resultados", [])),
        "pasta_execucao": str(execution_dir),
        "arquivos_execucao": [
            str(path)
            for path in [
                execution_dir / "00_resultados.png",
                execution_dir / "resultado.json",
            ]
            if path.exists()
        ],
        "resultados": resultados_resumo,
        "planilha_url": None,
        "drive_folder_url": None,
    }


def build_sheet_rows(summary: dict[str, object]) -> list[list[str]]:
    """Flatten the summary payload to spreadsheet rows."""
    base_values = [
        str(summary.get("execucao_id") or ""),
        str(summary.get("gerado_em") or ""),
        str(summary.get("termo") or ""),
        str(summary.get("filtros_resumo") or "-"),
        str(summary.get("quantidade_resultados") or 0),
    ]
    execution_dir = str(summary.get("pasta_execucao") or "")
    resultados = list(summary.get("resultados", []))

    if not resultados:
        return [
            base_values
            + [
                "",
                "",
                "",
                "-",
                "0",
                "False",
                execution_dir,
                "",
                "",
            ]
        ]

    rows: list[list[str]] = []
    for resultado in resultados:
        rows.append(
            base_values
            + [
                str(resultado.get("nome") or ""),
                str(resultado.get("cpf") or ""),
                str(resultado.get("localidade") or ""),
                str(resultado.get("recebimentos_resumo") or "-"),
                str(resultado.get("recebimentos_total") or 0),
                str(bool(resultado.get("captcha_detectado"))),
                execution_dir,
                str(resultado.get("drive_folder_url") or ""),
                str(resultado.get("url") or ""),
            ]
        )
    return rows
