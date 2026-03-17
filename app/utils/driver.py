"""Selenium WebDriver bootstrap and environment-driven settings."""

from __future__ import annotations

from contextlib import contextmanager
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver

from app.utils.logs import get_logger


LOGGER = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class SeleniumSettings:
    base_url: str = "https://portaldatransparencia.gov.br/pessoa-fisica/busca/lista?pagina=1&tamanhoPagina=10&beneficiarioProgramaSocial=true"
    browser: str = "chrome"
    headless: bool = True
    implicit_wait_seconds: float = 0.0
    page_load_timeout_seconds: int = 30
    page_load_strategy: str = "eager"
    window_width: int = 1600
    window_height: int = 900
    driver_path: str | None = None
    min_action_interval_seconds: float = 0.4
    action_interval_jitter_seconds: float = 0.15
    navigation_retry_attempts: int = 2
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0
    max_consecutive_failures: int = 3
    max_results: int = 0
    result_worker_count: int = 10
    capture_result_screenshots: bool = True
    capture_detail_screenshots: bool = True
    stop_on_captcha: bool = True


@dataclass(slots=True)
class DriverRuntimeState:
    implicit_wait_seconds: float
    min_action_interval_seconds: float
    action_interval_jitter_seconds: float
    last_action_monotonic: float = 0.0
    cookies_accepted: bool = False
    consecutive_failures: int = 0


@lru_cache(maxsize=1)
def load_settings() -> SeleniumSettings:
    """Read Selenium configuration from environment variables."""
    base_url = os.getenv("PORTAL_TRANSPARENCIA_URL", "").strip()
    if not base_url:
        raise ValueError(
            "Environment variable PORTAL_TRANSPARENCIA_URL is required."
        )

    return SeleniumSettings(
        base_url=base_url,
        browser=os.getenv("SELENIUM_BROWSER", "chrome").strip().lower(),
        headless=_as_bool(os.getenv("SELENIUM_HEADLESS"), default=True),
        implicit_wait_seconds=float(os.getenv("SELENIUM_IMPLICIT_WAIT", "0")),
        page_load_timeout_seconds=int(os.getenv("SELENIUM_PAGE_LOAD_TIMEOUT", "30")),
        page_load_strategy=os.getenv("SELENIUM_PAGE_LOAD_STRATEGY", "eager").strip().lower(),
        window_width=int(os.getenv("SELENIUM_WINDOW_WIDTH", "1600")),
        window_height=int(os.getenv("SELENIUM_WINDOW_HEIGHT", "900")),
        driver_path=os.getenv("CHROMEDRIVER_PATH") or None,
        min_action_interval_seconds=float(
            os.getenv("PORTAL_MIN_ACTION_INTERVAL_SECONDS", "0.4")
        ),
        action_interval_jitter_seconds=float(
            os.getenv("PORTAL_ACTION_INTERVAL_JITTER_SECONDS", "0.15")
        ),
        navigation_retry_attempts=max(int(os.getenv("PORTAL_NAVIGATION_RETRY_ATTEMPTS", "2")), 1),
        backoff_base_seconds=float(os.getenv("PORTAL_BACKOFF_BASE_SECONDS", "1.0")),
        backoff_max_seconds=float(os.getenv("PORTAL_BACKOFF_MAX_SECONDS", "8.0")),
        max_consecutive_failures=max(int(os.getenv("PORTAL_MAX_CONSECUTIVE_FAILURES", "3")), 1),
        max_results=max(int(os.getenv("PORTAL_MAX_RESULTS", "0")), 0),
        result_worker_count=max(int(os.getenv("PORTAL_RESULT_WORKER_COUNT", "10")), 1),
        capture_result_screenshots=_as_bool(
            os.getenv("PORTAL_CAPTURE_RESULT_SCREENSHOTS"),
            default=True,
        ),
        capture_detail_screenshots=_as_bool(
            os.getenv("PORTAL_CAPTURE_DETAIL_SCREENSHOTS"),
            default=True,
        ),
        stop_on_captcha=_as_bool(os.getenv("PORTAL_STOP_ON_CAPTCHA"), default=True),
    )


def build_chrome_options(settings: SeleniumSettings) -> Options:
    """Create Chrome options compatible with headless execution."""
    options = Options()
    options.page_load_strategy = settings.page_load_strategy
    if settings.headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--start-maximized")
    options.add_argument(f"--window-size={settings.window_width},{settings.window_height}")
    options.add_argument("--lang=pt-BR")

    return options


def create_driver(settings: SeleniumSettings | None = None) -> WebDriver:
    """Instantiate and configure a Selenium WebDriver."""
    settings = settings or load_settings()

    if settings.browser != "chrome":
        raise ValueError(f"Unsupported browser: {settings.browser}")

    options = build_chrome_options(settings)
    service = Service(executable_path=settings.driver_path) if settings.driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(settings.implicit_wait_seconds)
    driver.set_page_load_timeout(settings.page_load_timeout_seconds)
    driver._portal_settings = settings
    driver._portal_runtime = DriverRuntimeState(
        implicit_wait_seconds=settings.implicit_wait_seconds,
        min_action_interval_seconds=settings.min_action_interval_seconds,
        action_interval_jitter_seconds=settings.action_interval_jitter_seconds,
    )

    LOGGER.info("Selenium driver created for %s", settings.base_url)
    return driver


def get_driver_settings(driver: WebDriver) -> SeleniumSettings:
    """Return the settings attached to the driver session."""
    settings = getattr(driver, "_portal_settings", None)
    if settings is None:
        settings = load_settings()
        driver._portal_settings = settings
    return settings


def get_driver_runtime(driver: WebDriver) -> DriverRuntimeState:
    """Return mutable runtime state for the current Selenium session."""
    runtime = getattr(driver, "_portal_runtime", None)
    if runtime is None:
        settings = get_driver_settings(driver)
        runtime = DriverRuntimeState(
            implicit_wait_seconds=settings.implicit_wait_seconds,
            min_action_interval_seconds=settings.min_action_interval_seconds,
            action_interval_jitter_seconds=settings.action_interval_jitter_seconds,
        )
        driver._portal_runtime = runtime
    return runtime


@contextmanager
def temporary_implicit_wait(driver: WebDriver, seconds: float):
    """Temporarily override the implicit wait without reloading settings."""
    runtime = get_driver_runtime(driver)
    previous_wait = runtime.implicit_wait_seconds
    driver.implicitly_wait(seconds)
    runtime.implicit_wait_seconds = seconds
    try:
        yield
    finally:
        driver.implicitly_wait(previous_wait)
        runtime.implicit_wait_seconds = previous_wait


def close_driver(driver: WebDriver | None) -> None:
    """Safely close the Selenium session."""
    if driver is None:
        return

    driver.quit()
    LOGGER.info("Selenium driver closed")
