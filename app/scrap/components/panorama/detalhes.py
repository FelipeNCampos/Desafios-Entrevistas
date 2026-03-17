"""Helpers for receipt detail pages under the panorama section."""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[4]))

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from app.scrap.components.imagem import capture_full_page_base64, save_base64_to_file
from app.scrap.components.panorama.headers import clean_text, find_accordion_content_by_title
from app.utils.driver import get_driver_settings, temporary_implicit_wait
from app.utils.logs import get_logger
from app.utils.navegate import accept_all_cookies, navigate_to, wait_for_document_ready


LOGGER = get_logger(__name__)
DETAIL_LINK_SELECTOR = "a.br-button.secondary.mt-3[href*='/beneficios/']"
FULL_PAGINATION_BUTTON_ID = "btnPaginacaoCompleta"
NEXT_PAGE_SELECTOR = "#tabelaDetalheValoresSacados_next"
CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='captcha']",
    "iframe[src*='hcaptcha']",
    "iframe[title*='captcha' i]",
    ".g-recaptcha",
    ".h-captcha",
    ".hcaptcha-box",
    "#captcha",
    "[id*='captcha']",
    "[class*='captcha']",
    "[data-sitekey]",
    "[data-callback*='captcha']",
    "textarea[name='g-recaptcha-response']",
    "textarea[name='h-captcha-response']",
    "form[action*='captcha']",
]
CAPTCHA_TEXT_MARKERS = [
    "recaptcha",
    "hcaptcha",
    "captcha",
    "sou humano",
    "voce e humano",
    "você é humano",
    "nao sou um robo",
    "não sou um robô",
    "nao sou um robô",
    "não sou um robo",
    "verifique se voce e humano",
    "verifique se você é humano",
    "complete o desafio",
    "desafio de seguranca",
    "desafio de segurança",
    "acesso automatizado",
    "tráfego incomum",
    "trafego incomum",
    "unusual traffic",
    "checking your browser",
    "attention required",
]


def _slugify(value: str) -> str:
    """Create filesystem-safe names."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "detalhe"


def _next_page_available(driver: WebDriver) -> bool:
    """Check whether the next pagination button is enabled."""
    items = driver.find_elements(By.CSS_SELECTOR, NEXT_PAGE_SELECTOR)
    if not items:
        return False
    classes = items[0].get_attribute("class") or ""
    return "disabled" not in classes.split()


def _scroll_to_element(driver: WebDriver, element) -> None:
    """Scroll the page until the target element is centered in the viewport."""
    driver.execute_script(
        """
        arguments[0].scrollIntoView({
            behavior: 'auto',
            block: 'center',
            inline: 'center'
        });
        """,
        element,
    )
    time.sleep(0.2)


def detect_recaptcha(driver: WebDriver) -> bool:
    """Detect CAPTCHA or anti-bot challenge markers on the current page."""
    try:
        with temporary_implicit_wait(driver, 0):
            for selector in CAPTCHA_SELECTORS:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
    except Exception:
        LOGGER.info("Could not inspect page for CAPTCHA markers using DOM selectors")

    text_sources = [
        (driver.title or "").lower(),
        (driver.page_source or "").lower(),
    ]
    try:
        body_text = driver.execute_script(
            """
            return (
                document.body && (document.body.innerText || document.body.textContent) || ''
            );
            """
        )
        text_sources.append((body_text or "").lower())
    except Exception:
        LOGGER.info("Could not inspect page text for CAPTCHA markers")

    return any(marker in source for source in text_sources for marker in CAPTCHA_TEXT_MARKERS)


def _click_next_page(driver: WebDriver, timeout: int) -> bool:
    """Go to the next page in the detail table when possible."""
    if not _next_page_available(driver):
        return False

    try:
        next_button = WebDriverWait(driver, min(timeout, 5)).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, f"{NEXT_PAGE_SELECTOR} button"))
        )
        _scroll_to_element(driver, next_button)
        try:
            WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, f"{NEXT_PAGE_SELECTOR} button"))
            ).click()
        except TimeoutException:
            driver.execute_script("arguments[0].click();", next_button)
    except TimeoutException:
        LOGGER.info("Next page button was not available in time; finishing pagination")
        return False
    except Exception:
        LOGGER.info("Could not click next page button; finishing pagination")
        return False

    time.sleep(0.5)
    return True


def _save_detail_page_screenshot(
    driver: WebDriver,
    output_dir: Path,
    result_index: int,
    recurso_name: str,
    page_number: int,
) -> Path:
    """Capture and save a screenshot of the current detail page."""
    image_base64 = capture_full_page_base64(driver)
    filename = (
        f"{result_index:02d}_detalhe_{_slugify(recurso_name)}_pagina_{page_number:02d}.png"
    )
    return save_base64_to_file(image_base64, str(output_dir / filename))


def process_recebimentos_detalhes(
    driver: WebDriver,
    output_dir: str | Path,
    result_index: int,
    timeout: int = 20,
) -> list[dict[str, object]]:
    """Open each receipt detail page, paginate through it, and save screenshots."""
    settings = get_driver_settings(driver)
    content = find_accordion_content_by_title(driver, "Recebimentos de recursos")
    if content is None:
        LOGGER.info("Recebimentos de recursos section not found")
        return []

    detail_targets: list[dict[str, str]] = []
    seen_hrefs: set[str] = set()
    for detail_link in content.find_elements(By.CSS_SELECTOR, DETAIL_LINK_SELECTOR):
        href = (detail_link.get_attribute("href") or "").strip()
        recurso_name = ""
        try:
            parent = detail_link.find_element(
                By.XPATH,
                "./ancestor::div[contains(@class, 'responsive')]",
            )
            strong_elements = parent.find_elements(By.XPATH, "./strong[1]")
            if strong_elements:
                recurso_name = clean_text(strong_elements[0].text)
        except Exception:
            recurso_name = ""

        absolute_href = urljoin(driver.current_url, href)
        if href and absolute_href not in seen_hrefs:
            seen_hrefs.add(absolute_href)
            detail_targets.append(
                {
                    "href": absolute_href,
                    "recurso": recurso_name,
                }
            )

    details_output: list[dict[str, object]] = []
    for detail_target in detail_targets:
        href = detail_target["href"]
        recurso_name = detail_target["recurso"]

        navigate_to(driver, href, timeout=timeout, accept_cookies_timeout=1)
        if detect_recaptcha(driver):
            LOGGER.warning("reCAPTCHA detected while opening detail for %s", recurso_name)
            details_output.append(
                {
                    "recurso": recurso_name,
                    "url": href,
                    "screenshots": [],
                    "captcha_detectado": True,
                }
            )
            if settings.stop_on_captcha:
                LOGGER.warning("Stopping detail processing after CAPTCHA detection")
                break
            continue

        full_pagination_buttons = driver.find_elements(By.ID, FULL_PAGINATION_BUTTON_ID)
        if full_pagination_buttons:
            _scroll_to_element(driver, full_pagination_buttons[0])
            try:
                full_pagination_buttons[0].click()
            except Exception:
                driver.execute_script("arguments[0].click();", full_pagination_buttons[0])
            time.sleep(0.8)

        screenshots: list[str] = []
        page_number = 1
        while True:
            accept_all_cookies(driver, timeout=1)
            if detect_recaptcha(driver):
                LOGGER.warning("reCAPTCHA detected during pagination for %s", recurso_name)
                details_output.append(
                    {
                        "recurso": recurso_name,
                        "url": href,
                        "screenshots": screenshots,
                        "captcha_detectado": True,
                    }
                )
                break
            if settings.capture_detail_screenshots:
                screenshot_path = _save_detail_page_screenshot(
                    driver,
                    Path(output_dir),
                    result_index,
                    recurso_name or "recurso",
                    page_number,
                )
                screenshots.append(str(screenshot_path))
                LOGGER.info(
                    "Saved detail screenshot for %s page %s in %s",
                    recurso_name,
                    page_number,
                    screenshot_path,
                )

            if not _click_next_page(driver, timeout=timeout):
                break

            wait_for_document_ready(driver, timeout=timeout)
            page_number += 1

        if not details_output or details_output[-1].get("recurso") != recurso_name:
            details_output.append(
                {
                    "recurso": recurso_name,
                    "url": href,
                    "screenshots": screenshots,
                    "captcha_detectado": False,
                }
            )

        if details_output[-1].get("captcha_detectado") and settings.stop_on_captcha:
            LOGGER.warning("Stopping detail processing after CAPTCHA detection")
            break

    return details_output
