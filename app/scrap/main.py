"""Main scraping helpers for result collection and per-result extraction."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.scrap.components.imagem import capture_full_page_base64, save_base64_to_file
from app.scrap.components.panorama.detalhes import detect_recaptcha
from app.scrap.components.panorama.headers import (
    RESPONSIVE_SECTION_SELECTOR,
    clean_text as _clean_text,
    open_accordion_by_title,
    parse_brl_value as _parse_brl_value,
)
from app.utils.driver import close_driver, create_driver, get_driver_settings
from app.utils.logs import get_logger
from app.utils.navegate import navigate_to


LOGGER = get_logger(__name__)
RESULT_CONTAINER_SELECTOR = "#resultados"
RESULT_LINK_SELECTOR = "#resultados a.link-busca-nome"
PAGINATION_NEXT_SELECTOR = "li.next"
PAGINATION_NEXT_LINK_SELECTOR = "li.next a"
PAGINATION_ACTIVE_SELECTOR = "li.active, li.current, .pagination .active"
RESULT_PAGE_TIMEOUT_SECONDS = 10
RESULT_PAGE_COOKIE_TIMEOUT_SECONDS = 1
RESULT_ACCORDION_TIMEOUT_SECONDS = 4


def _slugify(value: str) -> str:
    """Create filesystem-safe names."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "resultado"


def _result_page_signature(driver: WebDriver) -> str:
    """Build a lightweight signature for the current result page."""
    active_items = driver.find_elements(By.CSS_SELECTOR, PAGINATION_ACTIVE_SELECTOR)
    active_text = _clean_text(active_items[0].text) if active_items else ""
    hrefs = [
        (element.get_attribute("href") or "").strip()
        for element in driver.find_elements(By.CSS_SELECTOR, RESULT_LINK_SELECTOR)
    ]
    return f"{active_text}|{'|'.join(hrefs)}"


def _next_results_page_available(driver: WebDriver) -> bool:
    """Return True when the next results page button is enabled."""
    next_items = driver.find_elements(By.CSS_SELECTOR, PAGINATION_NEXT_SELECTOR)
    if not next_items:
        return False
    classes = (next_items[0].get_attribute("class") or "").split()
    return "disabled" not in classes


def _click_next_results_page(driver: WebDriver, timeout: int) -> bool:
    """Advance to the next results page when available."""
    if not _next_results_page_available(driver):
        return False

    previous_signature = _result_page_signature(driver)
    next_link = WebDriverWait(driver, min(timeout, 5)).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, PAGINATION_NEXT_LINK_SELECTOR))
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_link)
    try:
        WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, PAGINATION_NEXT_LINK_SELECTOR))
        ).click()
    except Exception:
        driver.execute_script("arguments[0].click();", next_link)

    WebDriverWait(driver, timeout).until(
        lambda current_driver: _result_page_signature(current_driver) != previous_signature
    )
    return True


def collect_result_links(
    driver: WebDriver,
    timeout: int = 20,
    max_results: int | None = None,
) -> list[dict[str, str]]:
    """Collect all unique result links across the paginated results list."""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, RESULT_CONTAINER_SELECTOR))
    )

    effective_max_results = max(max_results or 0, 0)
    collected: list[dict[str, str]] = []
    seen_hrefs: set[str] = set()
    page_number = 1

    while True:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, RESULT_LINK_SELECTOR))
        )
        current_signature = _result_page_signature(driver)
        page_links = driver.find_elements(By.CSS_SELECTOR, RESULT_LINK_SELECTOR)
        page_added = 0

        for link in page_links:
            href = (link.get_attribute("href") or "").strip()
            name = _clean_text(link.text)
            absolute_href = urljoin(driver.current_url, href)
            if not href or absolute_href in seen_hrefs:
                continue

            seen_hrefs.add(absolute_href)
            collected.append({"name": name, "href": absolute_href})
            page_added += 1

            if effective_max_results and len(collected) >= effective_max_results:
                LOGGER.info("Collected %s result links and reached the configured limit", len(collected))
                return collected

        LOGGER.info(
            "Collected %s new links from results page %s (%s total)",
            page_added,
            page_number,
            len(collected),
        )

        if not _next_results_page_available(driver):
            LOGGER.info("Result pagination finished after %s pages", page_number)
            return collected

        if not _click_next_results_page(driver, timeout):
            LOGGER.info("Could not advance to the next result page; finishing collection")
            return collected

        WebDriverWait(driver, timeout).until(
            lambda current_driver: _result_page_signature(current_driver) != current_signature
        )
        page_number += 1


def _extract_field_by_label(driver: WebDriver, label: str) -> str:
    """Extract text that follows a labeled field in the summary area."""
    normalized_label = label.strip().lower()
    selectors = [
        (
            By.XPATH,
            (
                "//*[self::strong or self::span or self::div or self::dt]["
                f"contains(translate(normalize-space(.), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                f"'{normalized_label}')]/following-sibling::*[1]"
            ),
        ),
        (
            By.XPATH,
            (
                "//*[self::strong or self::span or self::div or self::dt]["
                f"contains(translate(normalize-space(.), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                f"'{normalized_label}')]/parent::*"
            ),
        ),
    ]

    for by, selector in selectors:
        try:
            elements = driver.find_elements(by, selector)
        except Exception:
            continue

        for element in elements:
            text = _clean_text(element.text)
            if not text:
                continue
            lower_text = text.lower()
            if normalized_label in lower_text:
                pieces = re.split(r"\s{2,}|:\s*", text, maxsplit=1)
                if len(pieces) > 1:
                    candidate = _clean_text(pieces[-1])
                    if candidate and candidate.lower() != normalized_label:
                        return candidate
                candidate = _clean_text(lower_text.replace(normalized_label, "", 1))
                if candidate:
                    return candidate
            else:
                return text

    return ""


def extract_person_summary(driver: WebDriver) -> dict[str, str]:
    """Extract top-level person metadata from the result page."""
    return {
        "nome": _extract_field_by_label(driver, "nome"),
        "cpf": _extract_field_by_label(driver, "cpf"),
        "localidade": _extract_field_by_label(driver, "localidade"),
    }


def extract_panorama_items(driver: WebDriver) -> list[dict[str, object]]:
    """Extract accordion section content from the panorama area."""
    panorama_items: list[dict[str, object]] = []
    buttons = driver.find_elements(By.CSS_SELECTOR, ".br-accordion .item > button.header[aria-controls]")

    for button in buttons:
        title_elements = button.find_elements(By.CSS_SELECTOR, "span.title")
        controls_id = (button.get_attribute("aria-controls") or "").strip()
        if not title_elements or not controls_id:
            continue

        title = _clean_text(title_elements[0].text)
        if not title:
            continue

        try:
            content = driver.find_element(By.ID, controls_id)
        except NoSuchElementException:
            continue

        if title.lower() == "recebimentos de recursos":
            resources = []
            for section in content.find_elements(By.CSS_SELECTOR, RESPONSIVE_SECTION_SELECTOR):
                raw_text = _clean_text(section.text)
                if not raw_text:
                    continue

                lines = [line.strip() for line in section.text.splitlines() if line.strip()]
                resource_name = lines[0] if lines else raw_text
                value = None
                for line in reversed(lines):
                    parsed = _parse_brl_value(line)
                    if parsed is not None:
                        value = parsed
                        break

                resources.append(
                    {
                        "nome": _clean_text(resource_name),
                        "valor": value,
                        "texto": raw_text,
                    }
                )

            panorama_items.append(
                {
                    "item": title,
                    "texto": _clean_text(content.text),
                    "recursos": resources,
                }
            )
            continue

        panorama_items.append(
            {
                "item": title,
                "texto": _clean_text(content.text),
            }
        )

    return panorama_items


def _process_result_page(
    index: int,
    result: dict[str, str],
    output_dir: Path,
    settings,
    result_page_timeout: int,
    accordion_timeout: int,
) -> dict[str, object]:
    """Process one result page in an isolated Selenium session."""
    worker_driver = create_driver(settings)
    try:
        navigate_to(
            worker_driver,
            result["href"],
            timeout=result_page_timeout,
            accept_cookies_timeout=RESULT_PAGE_COOKIE_TIMEOUT_SECONDS,
        )
        recebimentos_aberto = open_accordion_by_title(
            worker_driver,
            "Recebimentos de recursos",
            timeout=accordion_timeout,
        )
        captcha_detectado = detect_recaptcha(worker_driver)
        if captcha_detectado:
            LOGGER.warning("CAPTCHA detected while opening result %s", result["href"])

        person_summary = extract_person_summary(worker_driver)
        panorama = extract_panorama_items(worker_driver)

        image_base64 = ""
        image_path = ""
        if settings.capture_result_screenshots:
            image_base64 = capture_full_page_base64(worker_driver)
            saved_path = save_base64_to_file(
                image_base64,
                str(output_dir / f"{index:02d}_{_slugify(result['name'])}.png"),
            )
            image_path = str(saved_path)

        captcha_detectado = captcha_detectado or detect_recaptcha(worker_driver)
        detalhe_recebimentos: list[dict[str, object]] = []
        # Detail-page navigation remains disabled because it is triggering CAPTCHA frequently.
        # if recebimentos_aberto and not captcha_detectado:
        #     detalhe_recebimentos = process_recebimentos_detalhes(
        #         worker_driver,
        #         output_dir=output_dir,
        #         result_index=index,
        #         timeout=result_page_timeout,
        #     )

        return {
            "nome": person_summary.get("nome") or result["name"],
            "cpf": person_summary.get("cpf") or "",
            "localidade": person_summary.get("localidade") or "",
            "panorama": panorama,
            "detalhes_recebimentos": detalhe_recebimentos,
            "recebimentos_aberto": recebimentos_aberto,
            "captcha_detectado": captcha_detectado,
            "imagem_base64": image_base64,
            "imagem_path": image_path,
            "url": result["href"],
        }
    finally:
        close_driver(worker_driver)


def scrape_result_pages(
    driver: WebDriver,
    output_dir: str | Path,
    timeout: int = 20,
    max_results: int | None = None,
) -> list[dict[str, object]]:
    """Collect result links first, then process each result concurrently."""
    settings = get_driver_settings(driver)
    effective_max_results = settings.max_results if max_results is None else max(max_results, 0)
    results = collect_result_links(driver, timeout=timeout, max_results=effective_max_results)
    if not results:
        return []

    result_page_timeout = min(timeout, RESULT_PAGE_TIMEOUT_SECONDS)
    accordion_timeout = min(timeout, RESULT_ACCORDION_TIMEOUT_SECONDS)
    max_workers = min(settings.result_worker_count, len(results))
    extracted_results: list[dict[str, object] | None] = [None] * len(results)

    LOGGER.info(
        "Starting concurrent result extraction with %s workers for %s links",
        max_workers,
        len(results),
    )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="result-worker") as executor:
        pending_futures: dict[Future[dict[str, object]], int] = {
            executor.submit(
                _process_result_page,
                index,
                result,
                Path(output_dir),
                settings,
                result_page_timeout,
                accordion_timeout,
            ): position
            for position, (index, result) in enumerate(enumerate(results, start=1))
        }

        while pending_futures:
            completed, _ = wait(pending_futures, return_when=FIRST_COMPLETED)
            for future in completed:
                position = pending_futures.pop(future)
                extracted_results[position] = future.result()
                LOGGER.info(
                    "Processed result %s/%s",
                    position + 1,
                    len(results),
                )

    return [item for item in extracted_results if item is not None]


def save_execution_json(payload: dict[str, object], output_dir: str | Path) -> Path:
    """Persist the full execution payload to disk."""
    path = Path(output_dir) / "resultado.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("Execution JSON written to %s", path)
    return path


def main() -> None:
    """Development-only entry point kept for quick module imports."""
    LOGGER.info("This module is intended to be imported by app.main")


if __name__ == "__main__":
    main()
