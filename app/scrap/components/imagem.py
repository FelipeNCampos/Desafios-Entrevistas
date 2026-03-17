"""Screenshot helpers for capturing the full page and encoding as Base64."""

from __future__ import annotations

import base64
import io
import math
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from PIL import Image
from selenium.webdriver.remote.webdriver import WebDriver

from app.utils.logs import get_logger


LOGGER = get_logger(__name__)


def _capture_full_page_base64_via_cdp(driver: WebDriver) -> str | None:
    """Use Chrome DevTools full-page screenshot when available."""
    try:
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        content_size = metrics.get("contentSize", {})
        width = max(int(content_size.get("width", 0)), 1)
        height = max(int(content_size.get("height", 0)), 1)

        driver.execute_cdp_cmd(
            "Emulation.setDeviceMetricsOverride",
            {
                "mobile": False,
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
            },
        )
        screenshot = driver.execute_cdp_cmd(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "fromSurface": True,
            },
        )
        driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})
        data = screenshot.get("data")
        if data:
            LOGGER.info("Full-page screenshot captured via Chrome DevTools")
            return data
    except Exception:
        LOGGER.info("Chrome DevTools full-page screenshot unavailable; using scroll fallback")

    return None


def _read_page_metrics(driver: WebDriver) -> dict[str, int]:
    """Collect document and viewport dimensions from the browser."""
    metrics = driver.execute_script(
        """
        return {
            totalHeight: Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight
            ),
            viewportHeight: window.innerHeight,
            viewportWidth: window.innerWidth
        };
        """
    )
    return {
        "total_height": int(metrics["totalHeight"]),
        "viewport_height": int(metrics["viewportHeight"]),
        "viewport_width": int(metrics["viewportWidth"]),
    }


def _read_fixed_header_height(driver: WebDriver) -> int:
    """Estimate the vertical space occupied by fixed/sticky headers."""
    height = driver.execute_script(
        """
        const elements = Array.from(document.querySelectorAll('*'));
        let maxBottom = 0;
        for (const el of elements) {
            const style = window.getComputedStyle(el);
            if (!['fixed', 'sticky'].includes(style.position)) continue;
            const rect = el.getBoundingClientRect();
            if (rect.height <= 0) continue;
            if (rect.top > 5) continue;
            if (rect.bottom > window.innerHeight * 0.4) continue;
            maxBottom = Math.max(maxBottom, rect.bottom);
        }
        return Math.round(maxBottom);
        """
    )
    return max(int(height or 0), 0)


def _capture_scroll_screenshots(
    driver: WebDriver,
    scroll_pause_seconds: float,
    scroll_step_ratio: float,
) -> tuple[list[tuple[Image.Image, int]], int]:
    """Scroll through the page and capture screenshots for each viewport."""
    metrics = _read_page_metrics(driver)
    total_height = metrics["total_height"]
    viewport_height = max(metrics["viewport_height"], 1)
    fixed_header_height = _read_fixed_header_height(driver)
    scroll_step = max(int(viewport_height * scroll_step_ratio), 1)
    if fixed_header_height:
        scroll_step = max(min(scroll_step, viewport_height - fixed_header_height), 1)
    total_steps = max(math.ceil(max(total_height - viewport_height, 0) / scroll_step) + 1, 1)
    screenshots: list[tuple[Image.Image, int]] = []

    LOGGER.info(
        (
            "Capturing page screenshots with total_height=%s viewport_height=%s "
            "fixed_header_height=%s scroll_step=%s steps=%s"
        ),
        total_height,
        viewport_height,
        fixed_header_height,
        scroll_step,
        total_steps,
    )

    for step in range(total_steps):
        offset = min(step * scroll_step, max(total_height - viewport_height, 0))
        driver.execute_script("window.scrollTo(0, arguments[0]);", offset)
        time.sleep(scroll_pause_seconds)

        raw_bytes = driver.get_screenshot_as_png()
        screenshots.append((Image.open(io.BytesIO(raw_bytes)).convert("RGB"), offset))

    return screenshots, fixed_header_height


def _stitch_screenshots(
    driver: WebDriver,
    screenshots: list[tuple[Image.Image, int]],
    fixed_header_height: int,
) -> Image.Image:
    """Merge viewport screenshots into a single full-page image."""
    if not screenshots:
        raise ValueError("No screenshots were captured.")

    metrics = _read_page_metrics(driver)
    total_height = metrics["total_height"]
    image_width = screenshots[0][0].width
    image_height = max(total_height, screenshots[0][0].height)
    final_image = Image.new("RGB", (image_width, image_height))

    for index, (screenshot, offset) in enumerate(screenshots):
        paste_y = offset
        top_crop = fixed_header_height if index > 0 else 0
        remaining_height = image_height - paste_y
        if remaining_height <= 0:
            break

        available_height = max(screenshot.height - top_crop, 1)
        crop_height = min(available_height, remaining_height)
        chunk = screenshot.crop((0, top_crop, screenshot.width, top_crop + crop_height))
        final_image.paste(chunk, (0, paste_y))

    return final_image


def capture_full_page_base64(
    driver: WebDriver,
    image_format: str = "PNG",
    scroll_pause_seconds: float = 0.2,
    scroll_step_ratio: float = 0.45,
) -> str:
    """Capture the entire page, stitch the screenshots, and return Base64."""
    cdp_result = _capture_full_page_base64_via_cdp(driver)
    if cdp_result:
        return cdp_result

    original_offset = driver.execute_script("return window.pageYOffset;")
    screenshots, fixed_header_height = _capture_scroll_screenshots(
        driver=driver,
        scroll_pause_seconds=scroll_pause_seconds,
        scroll_step_ratio=scroll_step_ratio,
    )

    try:
        final_image = _stitch_screenshots(
            driver,
            screenshots,
            fixed_header_height,
        )
        buffer = io.BytesIO()
        final_image.save(buffer, format=image_format.upper())
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        LOGGER.info("Full-page screenshot encoded to Base64")
        return encoded
    finally:
        driver.execute_script("window.scrollTo(0, arguments[0]);", original_offset)
        for screenshot, _ in screenshots:
            screenshot.close()


def save_base64_to_file(image_base64: str, output_path: str) -> Path:
    """Persist a Base64-encoded image to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(image_base64))
    LOGGER.info("Screenshot written to %s", path)
    return path
