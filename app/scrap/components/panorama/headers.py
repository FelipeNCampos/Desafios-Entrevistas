"""Helpers for panorama accordion sections."""

from __future__ import annotations

import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[4]))

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from app.utils.logs import get_logger


LOGGER = get_logger(__name__)
ACCORDION_HEADER_SELECTOR = ".br-accordion .item > button.header[aria-controls]"
RESPONSIVE_SECTION_SELECTOR = ".responsive"


def clean_text(value: str) -> str:
    """Normalize extracted text content."""
    return " ".join((value or "").split())


def parse_brl_value(value: str) -> float | None:
    """Convert Brazilian currency text to a numeric value."""
    cleaned = clean_text(value)
    if "R$" not in cleaned:
        return None

    numeric = cleaned.split("R$", 1)[1].strip()
    numeric = numeric.replace(".", "").replace(",", ".")
    try:
        return float(numeric)
    except ValueError:
        return None


def expand_accordion_by_button(driver: WebDriver, button, timeout: int) -> bool:
    """Open an accordion section using its header button."""
    controls_id = (button.get_attribute("aria-controls") or "").strip()
    if not controls_id:
        return False

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    content = driver.find_element(By.ID, controls_id)
    if content.is_displayed():
        return True

    for attempt in range(3):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.05)
            if attempt == 0:
                button.click()
            else:
                driver.execute_script("arguments[0].click();", button)

            WebDriverWait(driver, min(timeout, 5)).until(
                lambda current: current.find_element(By.ID, controls_id).is_displayed()
            )
            return True
        except Exception:
            time.sleep(0.15)

    return False


def open_all_accordion_sections(driver: WebDriver, timeout: int = 10) -> None:
    """Expand all accordion sections available on the result details page."""
    buttons = driver.find_elements(By.CSS_SELECTOR, ACCORDION_HEADER_SELECTOR)
    if not buttons:
        LOGGER.info("No accordion sections found on result page")
        return

    opened = 0
    for button in buttons:
        if expand_accordion_by_button(driver, button, timeout):
            opened += 1
            time.sleep(0.05)

    LOGGER.info("Opened %s accordion sections on result page", opened)


def find_accordion_content_by_title(
    driver: WebDriver,
    title: str,
):
    """Return the content element for the accordion section title."""
    buttons = driver.find_elements(By.CSS_SELECTOR, ACCORDION_HEADER_SELECTOR)
    normalized_title = clean_text(title).lower()
    for button in buttons:
        title_elements = button.find_elements(By.CSS_SELECTOR, "span.title")
        controls_id = (button.get_attribute("aria-controls") or "").strip()
        if not title_elements or not controls_id:
            continue
        current_title = clean_text(title_elements[0].text).lower()
        if current_title == normalized_title:
            contents = driver.find_elements(By.ID, controls_id)
            if contents:
                return contents[0]
    return None


def open_accordion_by_title(driver: WebDriver, title: str, timeout: int = 10) -> bool:
    """Open only the accordion section matching the provided title."""
    buttons = driver.find_elements(By.CSS_SELECTOR, ACCORDION_HEADER_SELECTOR)
    normalized_title = clean_text(title).lower()
    for button in buttons:
        title_elements = button.find_elements(By.CSS_SELECTOR, "span.title")
        if not title_elements:
            continue
        current_title = clean_text(title_elements[0].text).lower()
        if current_title != normalized_title:
            continue
        opened = expand_accordion_by_button(driver, button, timeout)
        if opened:
            LOGGER.info("Accordion '%s' opened", title)
        else:
            LOGGER.warning("Could not open accordion '%s'", title)
        return opened
    return False
