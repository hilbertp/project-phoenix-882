from __future__ import annotations

import unittest

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.test_c9_review_surface_recovery import (
    FakeReviewApiState,
    _create_driver,
    _structure,
    _structure_payload,
    running_review_servers,
)


class ReviewSurfaceThroughputTests(unittest.TestCase):
    def test_keyboard_shortcuts_drive_core_actions_and_toggle_view(self) -> None:
        api_state = FakeReviewApiState()
        api_state.structures = [
            _structure_payload(
                structure_id="db1-fib-0001",
                current_position=1,
                total_structures=3,
                previous_structure=None,
            ),
            _structure_payload(
                structure_id="db1-fib-0002",
                current_position=2,
                total_structures=3,
                previous_structure=_structure(
                    structure_id="db1-fib-0001-prev",
                    direction="up",
                    parent_anchor_source_timestamp="2026-03-01T08:00:00",
                    terminal_extreme_source_timestamp="2026-03-01T12:00:00",
                ),
            ),
            _structure_payload(
                structure_id="db1-fib-0003",
                current_position=3,
                total_structures=3,
                previous_structure=_structure(
                    structure_id="db1-fib-0002-prev",
                    direction="up",
                    parent_anchor_source_timestamp="2026-03-02T08:00:00",
                    terminal_extreme_source_timestamp="2026-03-02T12:00:00",
                ),
            ),
        ]

        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                body = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                review_target_id = wait.until(
                    EC.presence_of_element_located((By.ID, "review-target-id"))
                )
                comparison_mode_copy = wait.until(
                    EC.presence_of_element_located((By.ID, "comparison-mode-copy"))
                )
                comparison_mode_pill = wait.until(
                    EC.presence_of_element_located((By.ID, "comparison-mode-pill"))
                )

                wait.until(
                    lambda browser: browser.find_element(By.ID, "good-enough-button").is_enabled()
                )
                self.assertEqual(review_target_id.text.strip(), "db1-fib-0001")
                self.assertIn("db1-fib-0001", comparison_mode_copy.text)

                body.send_keys("m")
                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 3"
                )
                self.assertEqual(api_state.submissions[0]["review_outcome"], "adjusted_accept")
                self.assertEqual(review_target_id.text.strip(), "db1-fib-0002")
                self.assertIn("db1-fib-0002", comparison_mode_copy.text)

                body.send_keys("v")
                wait.until(
                    lambda browser: browser.find_element(By.ID, "viewing-label").text.strip()
                    == "previous"
                )
                self.assertEqual(
                    comparison_mode_pill.text.strip().lower(),
                    "previous comparison",
                )

                body.send_keys("v")
                wait.until(
                    lambda browser: browser.find_element(By.ID, "viewing-label").text.strip()
                    == "current"
                )
                self.assertEqual(comparison_mode_pill.text.strip().lower(), "current view")

                body.send_keys("w")
                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 3 of 3"
                )
                self.assertEqual(api_state.submissions[1]["review_outcome"], "flatout_wrong")
                self.assertEqual(review_target_id.text.strip(), "db1-fib-0003")

                wait.until(
                    lambda browser: browser.find_element(By.ID, "good-enough-button").is_enabled()
                )
                body.send_keys("o")
                wait.until(lambda browser: len(api_state.submissions) == 3)
                self.assertEqual(api_state.submissions[2]["review_outcome"], "good_enough")
            finally:
                driver.quit()

    def test_retry_shortcut_retries_tradingview_sync(self) -> None:
        api_state = FakeReviewApiState(fail_first_sync_for={"db1-fib-0001"})
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                body = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                tradingview_status = wait.until(
                    EC.presence_of_element_located((By.ID, "tradingview-status"))
                )
                sync_button = wait.until(
                    EC.presence_of_element_located((By.ID, "sync-chart-button"))
                )

                wait.until(lambda browser: "TradingView sync failed:" in tradingview_status.text)
                self.assertEqual(sync_button.text.strip(), "retry TradingView sync")

                body.send_keys("r")

                wait.until(
                    lambda browser: "TradingView synced for db1-fib-0001" in tradingview_status.text
                )
                self.assertEqual(api_state.sync_attempts["db1-fib-0001"], 2)
            finally:
                driver.quit()


if __name__ == "__main__":
    unittest.main()