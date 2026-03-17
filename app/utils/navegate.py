"""Helpers for page navigation."""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from app.utils.driver import (
    SeleniumSettings,
    close_driver,
    create_driver,
    get_driver_settings,
    get_driver_runtime,
    load_settings,
    temporary_implicit_wait,
)
from app.utils.logs import get_logger


LOGGER = get_logger(__name__)


def open_base_page(driver: WebDriver, settings: SeleniumSettings | None = None) -> None:
    """Open the configured transparency portal URL."""
    current_settings = settings or load_settings()
    navigate_to(driver, current_settings.base_url)


def pace_navigation(driver: WebDriver, min_interval_seconds: float | None = None) -> None:
    """Enforce a minimum interval between navigation actions."""
    runtime = get_driver_runtime(driver)
    interval = (
        runtime.min_action_interval_seconds
        if min_interval_seconds is None
        else min_interval_seconds
    )
    jitter = runtime.action_interval_jitter_seconds if min_interval_seconds is None else 0.0
    if interval <= 0:
        runtime.last_action_monotonic = time.monotonic()
        return

    elapsed = time.monotonic() - runtime.last_action_monotonic
    target_interval = interval + random.uniform(0.0, max(jitter, 0.0))
    if elapsed < target_interval:
        time.sleep(target_interval - elapsed)
    runtime.last_action_monotonic = time.monotonic()


def wait_for_document_ready(
    driver: WebDriver,
    timeout: int = 20,
    target_state: str = "complete",
) -> None:
    """Block until the browser reports the page as loaded enough for the caller."""
    expected_states = (
        {"interactive", "complete"}
        if target_state == "interactive"
        else {"complete"}
    )
    WebDriverWait(driver, timeout).until(
        lambda current_driver: current_driver.execute_script(
            "return document.readyState"
        )
        in expected_states
    )
    LOGGER.info("Document readyState reached %s", target_state)


def navigate_to(
    driver: WebDriver,
    url: str,
    timeout: int = 20,
    accept_cookies_timeout: int = 2,
) -> None:
    """Open an URL while respecting the session pacing rules."""
    settings = get_driver_settings(driver)
    last_error: Exception | None = None

    for attempt in range(1, settings.navigation_retry_attempts + 1):
        try:
            pace_navigation(driver)
            LOGGER.info("Opening URL: %s (attempt %s/%s)", url, attempt, settings.navigation_retry_attempts)
            driver.get(url)
            wait_for_document_ready(driver, timeout=timeout)
            accept_all_cookies(driver, timeout=accept_cookies_timeout)
            _register_navigation_success(driver)
            return
        except Exception as exc:
            last_error = exc
            _register_navigation_failure(driver, settings, url, attempt, exc)
            if attempt >= settings.navigation_retry_attempts:
                break

    if last_error is not None:
        raise last_error


def _register_navigation_success(driver: WebDriver) -> None:
    """Reset failure counters after a successful navigation."""
    runtime = get_driver_runtime(driver)
    runtime.consecutive_failures = 0


def _register_navigation_failure(
    driver: WebDriver,
    settings: SeleniumSettings,
    url: str,
    attempt: int,
    error: Exception,
) -> None:
    """Apply exponential backoff after navigation failures."""
    runtime = get_driver_runtime(driver)
    runtime.consecutive_failures += 1
    backoff_seconds = min(
        settings.backoff_base_seconds * (2 ** max(runtime.consecutive_failures - 1, 0)),
        settings.backoff_max_seconds,
    )
    LOGGER.warning(
        "Navigation failure for %s on attempt %s/%s: %s. Backing off for %.2fs",
        url,
        attempt,
        settings.navigation_retry_attempts,
        error,
        backoff_seconds,
    )
    if runtime.consecutive_failures >= settings.max_consecutive_failures:
        raise RuntimeError(
            "Numero maximo de falhas consecutivas atingido; abortando para evitar insistencia no portal."
        ) from error
    time.sleep(backoff_seconds)


def accept_all_cookies(driver: WebDriver, timeout: int = 10) -> bool:
    """Click the consent button when it is available on the page."""
    runtime = get_driver_runtime(driver)
    if runtime.cookies_accepted:
        return False

    deadline = time.monotonic() + timeout

    try:
        with temporary_implicit_wait(driver, 0):
            while time.monotonic() < deadline:
                buttons = driver.find_elements(By.ID, "accept-all-btn")
                if buttons:
                    button = buttons[0]
                    if button.is_displayed() and button.is_enabled():
                        try:
                            button.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", button)
                        runtime.cookies_accepted = True
                        LOGGER.info("Consent button accept-all-btn clicked")
                        return True
                time.sleep(0.1)
    except Exception:
        LOGGER.info("Consent button accept-all-btn could not be clicked")

    LOGGER.info("Consent button accept-all-btn not found")
    return False


def main() -> None:
    """Open the configured URL and validate the navigation helpers."""
    driver = create_driver()
    try:
        open_base_page(driver)
        LOGGER.info("Navigation test completed successfully")
    finally:
        close_driver(driver)


if __name__ == "__main__":
    main()
