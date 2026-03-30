from __future__ import annotations

import unittest
from typing import cast

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.test_c9_review_surface_recovery import (
    FakeReviewApiState,
    _create_driver,
    running_review_servers,
)


class VerifiedChartTruthApiState(FakeReviewApiState):
    def __init__(self) -> None:
        super().__init__()
        self.requested_positions: list[int] = []

    def structure_for_position(self, position: int) -> dict[str, object]:
        self.requested_positions.append(position)
        return super().structure_for_position(position)

    def sync(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        status, response_payload = super().sync(payload)
        if status != 202:
            return status, response_payload

        review_structure = cast(dict[str, object], payload["review_structure"])
        return status, {
            **response_payload,
            "render_verification": {
                "verified": True,
                "direction": review_structure["direction"],
                "parent_anchor_source_timestamp": review_structure[
                    "parent_anchor_source_timestamp"
                ],
                "parent_anchor_price": review_structure["parent_anchor_price"],
                "terminal_extreme_source_timestamp": review_structure[
                    "terminal_extreme_source_timestamp"
                ],
                "terminal_extreme_price": review_structure["terminal_extreme_price"],
            },
        }


class ChartTruthSliceATests(unittest.TestCase):
    def test_chart_truth_page_shows_one_structure_and_verifies_one_fib(self) -> None:
        api_state = VerifiedChartTruthApiState()
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url.replace("/index.html", "/chart-truth.html"))

                body = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-state") == "synced"
                )

                self.assertEqual(body.get_attribute("data-chart-truth-verified"), "true")
                self.assertEqual(
                    body.get_attribute("data-chart-truth-error"),
                    "",
                )

                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-structure-id").text.strip(),
                    "db1-fib-0001",
                )
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-direction").text.strip(),
                    "UP",
                )
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-anchor-1").text.strip(),
                    "2026-03-02 08:00:00 @ 88350.70",
                )
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-anchor-2").text.strip(),
                    "2026-03-02 12:00:00 @ 89180.80",
                )

                self.assertEqual(api_state.requested_positions, [1])
                self.assertEqual(api_state.sync_attempts, {"db1-fib-0001": 1})
                self.assertFalse(driver.find_elements(By.ID, "sync-chart-button"))
                self.assertFalse(driver.find_elements(By.ID, "good-enough-button"))
                self.assertFalse(driver.find_elements(By.ID, "tradingview-status"))
                self.assertTrue(
                    driver.execute_script(
                        "return Boolean(window.__db1ChartTruthLastSync && window.__db1ChartTruthLastSync.render_verification && window.__db1ChartTruthLastSync.render_verification.verified);"
                    )
                )
            finally:
                driver.quit()


if __name__ == "__main__":
    unittest.main()