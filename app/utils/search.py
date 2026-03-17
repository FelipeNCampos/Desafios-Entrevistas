"""Search helpers for the transparency portal form."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
import time

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from app.utils.logs import get_logger


LOGGER = get_logger(__name__)
REFINE_BUTTON_SELECTOR = "button.header[aria-controls='box-busca-refinada']"
REFINE_PANEL_SELECTOR = "#box-busca-refinada"
SUBMIT_BUTTON_SELECTOR = "#btnConsultarPF"
RESULT_READY_SELECTORS = [
    "#resultados",
    "#resultados a.link-busca-nome",
    ".feedback-warning",
    ".feedback-danger",
]


@dataclass(slots=True)
class SearchPayload:
    nome: str | None = None
    cpf_ou_nis: str | None = None
    filtro_social: bool = False
    filtros: list[str] = field(default_factory=list)

    def main_term(self) -> str:
        return (self.cpf_ou_nis or self.nome or "").strip()


def _env_or_default(name: str, default: str | None = None) -> str | None:
    """Return the env value, ignoring empty strings."""
    value = os.getenv(name)
    if value is None:
        return default

    cleaned = value.strip()
    if not cleaned:
        return default

    return cleaned


def validate_payload(payload: SearchPayload) -> None:
    """Ensure the challenge mandatory search fields are respected."""
    if not payload.main_term():
        raise ValueError("Informe nome ou CPF/NIS para realizar a busca.")


def _locate_search_input(driver: WebDriver, timeout: int, preferred_selector: str):
    """Find the search input using multiple fallback selectors."""
    candidate_selectors = [
        preferred_selector,
        "#termo",
        "input#termo",
        "input[name='termo']",
        "input[type='search'][name='termo']",
    ]

    for selector in candidate_selectors:
        if not selector:
            continue
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            LOGGER.info("Search input found using selector %s", selector)
            return element
        except TimeoutException:
            continue

    js_element = driver.execute_script(
        """
        return (
            document.querySelector('#termo') ||
            document.querySelector('input[name="termo"]') ||
            document.querySelector('input[type="search"][name="termo"]')
        );
        """
    )
    if js_element is not None:
        LOGGER.info("Search input found using JavaScript fallback")
        return js_element

    raise TimeoutException("Search input field was not found.")


def _panel_is_visible(driver: WebDriver) -> bool:
    """Check whether the refine-search panel is currently visible."""
    elements = driver.find_elements(By.CSS_SELECTOR, REFINE_PANEL_SELECTOR)
    return bool(elements) and elements[0].is_displayed()


def open_refine_search(driver: WebDriver, timeout: int = 20) -> bool:
    """Expand the refine-search accordion before selecting filters."""
    if _panel_is_visible(driver):
        LOGGER.info("Refine a Busca section already open")
        return True

    driver.execute_script("window.scrollTo(0, 0);")
    button = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, REFINE_BUTTON_SELECTOR))
    )

    for attempt in range(3):
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                button,
            )
            if attempt == 0:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, REFINE_BUTTON_SELECTOR))
                ).click()
            else:
                driver.execute_script("arguments[0].click();", button)

            WebDriverWait(driver, 5).until(lambda current: _panel_is_visible(current))
            LOGGER.info("Refine a Busca section opened")
            return True
        except TimeoutException:
            LOGGER.info("Retrying Refine a Busca open attempt %s", attempt + 2)
            time.sleep(0.5)

    LOGGER.warning("Could not reopen Refine a Busca section before the screenshot")
    return False


def _ensure_checkbox_state(
    driver: WebDriver,
    checkbox_id: str,
    checked: bool,
    timeout: int,
) -> None:
    """Toggle a checkbox only when its current state differs from the target."""
    checkbox = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, checkbox_id))
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkbox)
    if checkbox.is_selected() != checked:
        driver.execute_script("arguments[0].click();", checkbox)
    LOGGER.info("Filter %s set to %s", checkbox_id, checked)


def apply_refine_filters(
    driver: WebDriver,
    payload: SearchPayload,
    timeout: int = 20,
) -> None:
    """Apply checkbox filters from the payload."""
    requested_filters = list(payload.filtros)
    if payload.filtro_social and "beneficiarioProgramaSocial" not in requested_filters:
        requested_filters.append("beneficiarioProgramaSocial")

    if not requested_filters:
        return

    open_refine_search(driver, timeout=timeout)
    for filter_id in requested_filters:
        _ensure_checkbox_state(driver, filter_id, True, timeout)


def run_search(driver: WebDriver, payload: SearchPayload, timeout: int = 20) -> None:
    """Fill the configured search input and submit the form."""
    validate_payload(payload)

    input_selector = _env_or_default("PORTAL_SEARCH_INPUT_SELECTOR", "#termo")
    submit_selector = _env_or_default("PORTAL_SEARCH_SUBMIT_SELECTOR")
    input_element = _locate_search_input(driver, timeout, input_selector)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_element)
    driver.execute_script("arguments[0].value = '';", input_element)
    input_element.clear()
    input_element.send_keys(payload.main_term())

    apply_refine_filters(driver, payload, timeout=timeout)
    _submit_search(driver, input_element, submit_selector, timeout=timeout)
    LOGGER.info("Search submitted with term: %s", payload.main_term())


def wait_for_search_results(driver: WebDriver, timeout: int = 20) -> None:
    """Wait until the portal renders either a result list or a feedback message."""
    WebDriverWait(driver, timeout).until(
        lambda current_driver: any(
            current_driver.find_elements(By.CSS_SELECTOR, selector)
            for selector in RESULT_READY_SELECTORS
        )
    )
    LOGGER.info("Search results view is ready")


def _submit_search(
    driver: WebDriver,
    input_element,
    submit_selector: str | None,
    timeout: int,
) -> None:
    """Submit the search form using Enter first and button/form fallbacks if needed."""
    try:
        input_element.send_keys(Keys.ENTER)
        wait_for_search_results(driver, timeout=min(timeout, 5))
        return
    except TimeoutException:
        LOGGER.info("Enter submission did not resolve results; trying fallback selectors")

    candidate_selectors = [
        submit_selector,
        SUBMIT_BUTTON_SELECTOR,
        "button[type='submit']",
        "input[type='submit']",
    ]
    for selector in candidate_selectors:
        if not selector:
            continue
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if not elements:
            continue

        submit_element = elements[0]
        try:
            if submit_element.is_displayed() and submit_element.is_enabled():
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});",
                    submit_element,
                )
                try:
                    submit_element.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", submit_element)
            else:
                driver.execute_script(
                    """
                    const element = arguments[0];
                    if (element.form && typeof element.form.requestSubmit === 'function') {
                        element.form.requestSubmit();
                    } else if (element.form) {
                        element.form.submit();
                    } else {
                        element.click();
                    }
                    """,
                    submit_element,
                )
            wait_for_search_results(driver, timeout=timeout)
            return
        except TimeoutException:
            LOGGER.info("Fallback submission with selector %s did not resolve results", selector)
            continue

    raise TimeoutException("Nao foi possivel submeter a busca com os seletores disponiveis.")
