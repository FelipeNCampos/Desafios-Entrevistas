"""Email notification helpers."""

from __future__ import annotations

from collections.abc import Mapping
from email.message import EmailMessage
from html import escape
import smtplib
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from app.utils.integration.driver import load_integration_context, notifications_enabled
from app.utils.logs import get_logger


LOGGER = get_logger(__name__)
MAX_EMAIL_RESULTS = 10


def _sorted_email_results(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Return results ordered by total receipts descending for email summaries."""
    resultados = list(result.get("resultados", []))
    return sorted(
        resultados,
        key=lambda item: float(item.get("recebimentos_total") or 0),
        reverse=True,
    )


def build_notification_payload(
    result: Mapping[str, object],
    subject: str = "Resultado da automacao",
    attachment_path: str | Path | None = None,
) -> EmailMessage:
    """Create an email message from the automation result."""
    context = load_integration_context()
    if not context.notification_email_to:
        raise ValueError("Configure NOTIFICATION_EMAIL_TO no arquivo .env.")
    if not context.notification_email_from:
        raise ValueError("Configure NOTIFICATION_EMAIL_FROM no arquivo .env.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = context.notification_email_from
    message["To"] = context.notification_email_to
    message.set_content(_build_plain_text_content(result))
    message.add_alternative(_build_html_content(result), subtype="html")

    if attachment_path:
        path = Path(attachment_path)
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="json",
            filename=path.name,
        )

    LOGGER.info("Prepared email notification payload")
    return message


def send_notification_email(
    result: Mapping[str, object],
    subject: str = "Resultado da automacao",
    attachment_path: str | Path | None = None,
) -> None:
    """Send the automation result to the configured email address."""
    if int(result.get("quantidade_resultados") or 0) <= 0:
        LOGGER.info("Email notification skipped because the execution returned no results")
        return

    context = load_integration_context()
    if not notifications_enabled(context):
        LOGGER.info("Email notification skipped because SMTP/email settings are not fully configured")
        return

    message = build_notification_payload(
        result=result,
        subject=subject,
        attachment_path=attachment_path,
    )

    with smtplib.SMTP(context.smtp_host, context.smtp_port) as smtp:
        if context.smtp_use_tls:
            smtp.starttls()
        if context.smtp_username and context.smtp_password:
            smtp.login(context.smtp_username, context.smtp_password)
        smtp.send_message(message)

    LOGGER.info("Notification email sent to %s", context.notification_email_to)


def _build_plain_text_content(result: Mapping[str, object]) -> str:
    """Create a plain-text fallback version of the execution summary."""
    resultados = _sorted_email_results(result)
    displayed_results = resultados[:MAX_EMAIL_RESULTS]
    lines = [
        "A automacao foi concluida.",
        "",
        f"Execucao ID: {result.get('execucao_id', '-')}",
        f"Gerado em: {result.get('gerado_em', '-')}",
        f"Termo: {result.get('termo', '-')}",
        f"Filtros: {result.get('filtros_resumo', '-')}",
        f"Quantidade de resultados: {result.get('quantidade_resultados', 0)}",
        f"Pasta de execucao: {result.get('pasta_execucao', '-')}",
    ]

    drive_folder_url = result.get("drive_folder_url")
    if drive_folder_url:
        lines.append(f"Pasta da execucao no Google Drive: {drive_folder_url}")

    planilha_url = result.get("planilha_url")
    if planilha_url:
        lines.append(f"Planilha Google Sheets: {planilha_url}")

    lines.append("")
    lines.append(
        f"Resultados exibidos no e-mail: {len(displayed_results)} de {len(resultados)}"
    )
    lines.append("Resultados:")
    if not resultados:
        lines.append("- Nenhum resultado encontrado.")
        return "\n".join(lines)

    for item in displayed_results:
        lines.append(
            (
                f"- Nome: {item.get('nome', '-')}"
                f" | CPF: {item.get('cpf', '-')}"
                f" | Localidade: {item.get('localidade', '-')}"
                f" | Recebimentos: {item.get('recebimentos_resumo', '-')}"
                f" | Total: {item.get('recebimentos_total', 0)}"
                f" | Pasta Drive: {item.get('drive_folder_url', '-')}"
                f" | CAPTCHA: {item.get('captcha_detectado', False)}"
            )
        )
    if len(resultados) > len(displayed_results):
        lines.append(
            f"- {len(resultados) - len(displayed_results)} resultado(s) adicional(is) omitido(s) para reduzir o tamanho do e-mail."
        )
    return "\n".join(lines)


def _build_html_content(result: Mapping[str, object]) -> str:
    """Create the HTML email body with summary and results tables."""
    summary_rows = [
        ("Execucao ID", result.get("execucao_id", "-")),
        ("Gerado em", result.get("gerado_em", "-")),
        ("Termo", result.get("termo", "-")),
        ("Filtros", result.get("filtros_resumo", "-")),
        ("Quantidade de resultados", result.get("quantidade_resultados", 0)),
        ("Pasta de execucao", result.get("pasta_execucao", "-")),
    ]
    if result.get("drive_folder_url"):
        summary_rows.append(
            (
                "Pasta Google Drive",
                f"<a href=\"{escape(str(result['drive_folder_url']))}\">Abrir pasta</a>",
            )
        )
    if result.get("planilha_url"):
        summary_rows.append(
            (
                "Planilha Google Sheets",
                f"<a href=\"{escape(str(result['planilha_url']))}\">Abrir planilha</a>",
            )
        )

    result_rows = _build_result_table_rows(result)
    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #1f2937;">
        <p>A automacao foi concluida.</p>
        <h3>Resumo da execucao</h3>
        {_render_key_value_table(summary_rows)}
        <h3>Resultados</h3>
        {result_rows}
      </body>
    </html>
    """


def _build_result_table_rows(result: Mapping[str, object]) -> str:
    """Render the main result rows table for HTML email."""
    resultados = _sorted_email_results(result)
    if not resultados:
        return "<p>Nenhum resultado encontrado.</p>"

    displayed_results = resultados[:MAX_EMAIL_RESULTS]
    headers = ["Nome", "CPF", "Localidade", "Recebimentos", "Total", "Pasta Drive", "CAPTCHA"]
    rows: list[list[str]] = []
    for item in displayed_results:
        drive_folder_url = str(item.get("drive_folder_url") or "")
        drive_folder_html = (
            f"<a href=\"{escape(drive_folder_url)}\">Abrir pasta</a>"
            if drive_folder_url
            else "-"
        )
        rows.append(
            [
                escape(str(item.get("nome", "-"))),
                escape(str(item.get("cpf", "-"))),
                escape(str(item.get("localidade", "-"))),
                escape(str(item.get("recebimentos_resumo", "-"))),
                escape(str(item.get("recebimentos_total", 0))),
                drive_folder_html,
                escape(str(item.get("captcha_detectado", False))),
            ]
        )
    table_html = _render_html_table(headers, rows)
    if len(resultados) <= len(displayed_results):
        return table_html
    omitted_count = len(resultados) - len(displayed_results)
    return (
        f"<p>Exibindo os {len(displayed_results)} maiores totais entre {len(resultados)} resultados.</p>"
        f"{table_html}"
        f"<p>{omitted_count} resultado(s) adicional(is) foram omitido(s) para reduzir o tamanho da mensagem.</p>"
    )


def _render_key_value_table(rows: list[tuple[str, object]]) -> str:
    """Render a two-column summary table."""
    rendered_rows = []
    for key, value in rows:
        safe_key = escape(str(key))
        safe_value = value if str(value).startswith("<a ") else escape(str(value))
        rendered_rows.append(
            f"<tr><th style=\"text-align:left;padding:8px;border:1px solid #d1d5db;background:#f3f4f6;\">{safe_key}</th>"
            f"<td style=\"padding:8px;border:1px solid #d1d5db;\">{safe_value}</td></tr>"
        )
    return (
        "<table style=\"border-collapse:collapse;width:100%;margin-bottom:16px;\">"
        f"{''.join(rendered_rows)}"
        "</table>"
    )


def _render_html_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a generic HTML table."""
    header_html = "".join(
        f"<th style=\"padding:8px;border:1px solid #d1d5db;background:#f3f4f6;text-align:left;\">{escape(header)}</th>"
        for header in headers
    )
    row_html = []
    for row in rows:
        cells = "".join(
            f"<td style=\"padding:8px;border:1px solid #d1d5db;vertical-align:top;\">{cell}</td>"
            for cell in row
        )
        row_html.append(f"<tr>{cells}</tr>")
    return (
        "<table style=\"border-collapse:collapse;width:100%;\">"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
    )
