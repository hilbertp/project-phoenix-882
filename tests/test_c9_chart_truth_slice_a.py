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
                verdict_buttons = driver.find_elements(By.CSS_SELECTOR, ".chart-truth-verdict-button")
                self.assertEqual(len(verdict_buttons), 3)
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

    def test_chart_truth_page_allows_selecting_exactly_one_verdict(self) -> None:
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

                up_button = driver.find_element(By.ID, "chart-truth-verdict-up")
                down_button = driver.find_element(By.ID, "chart-truth-verdict-down")
                meh_button = driver.find_element(By.ID, "chart-truth-verdict-meh")
                save_button = driver.find_element(By.ID, "chart-truth-save-verdict")
                save_status = driver.find_element(By.ID, "chart-truth-save-status")
                selected_copy = driver.find_element(By.ID, "chart-truth-selected-verdict")

                self.assertEqual(selected_copy.text.strip(), "No verdict selected.")
                self.assertEqual(body.get_attribute("data-chart-truth-verdict"), "")
                self.assertEqual(body.get_attribute("data-chart-truth-saved-verdict"), "")
                self.assertEqual(save_status.text.strip(), "No saved verdict.")
                self.assertFalse(save_button.is_enabled())

                down_button.click()
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-verdict") == "down"
                )
                self.assertEqual(selected_copy.text.strip(), "Selected verdict: DOWN")
                self.assertTrue(save_button.is_enabled())
                self.assertEqual(up_button.get_attribute("aria-pressed"), "false")
                self.assertEqual(down_button.get_attribute("aria-pressed"), "true")
                self.assertEqual(meh_button.get_attribute("aria-pressed"), "false")

                meh_button.click()
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-verdict") == "meh"
                )
                self.assertEqual(selected_copy.text.strip(), "Selected verdict: MEH")
                self.assertEqual(up_button.get_attribute("aria-pressed"), "false")
                self.assertEqual(down_button.get_attribute("aria-pressed"), "false")
                self.assertEqual(meh_button.get_attribute("aria-pressed"), "true")
                self.assertTrue(save_button.is_enabled())
                self.assertEqual(api_state.sync_attempts, {"db1-fib-0001": 1})
            finally:
                driver.quit()

    def test_chart_truth_page_saves_selected_verdict_and_restores_it_after_reload(self) -> None:
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

                verdict_button = driver.find_element(By.ID, "chart-truth-verdict-up")
                save_button = driver.find_element(By.ID, "chart-truth-save-verdict")
                save_status = driver.find_element(By.ID, "chart-truth-save-status")
                selected_copy = driver.find_element(By.ID, "chart-truth-selected-verdict")

                verdict_button.click()
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-verdict") == "up"
                )
                save_button.click()

                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-saved-verdict") == "up"
                )
                self.assertEqual(selected_copy.text.strip(), "Selected verdict: UP")
                self.assertEqual(save_status.text.strip(), "Saved verdict: UP")
                self.assertFalse(save_button.is_enabled())
                self.assertEqual(
                    api_state.chart_truth_verdicts["db1-fib-0001"]["verdict"],
                    "up",
                )

                driver.refresh()

                body = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-state") == "synced"
                )
                wait.until(
                    lambda browser: body.get_attribute("data-chart-truth-saved-verdict") == "up"
                )

                self.assertEqual(body.get_attribute("data-chart-truth-verdict"), "up")
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-selected-verdict").text.strip(),
                    "Selected verdict: UP",
                )
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-save-status").text.strip(),
                    "Saved verdict: UP",
                )
                self.assertEqual(
                    driver.find_element(By.ID, "chart-truth-verdict-up").get_attribute("aria-pressed"),
                    "true",
                )
                self.assertFalse(driver.find_element(By.ID, "chart-truth-save-verdict").is_enabled())
                self.assertEqual(api_state.requested_positions, [1, 1])
                self.assertEqual(api_state.sync_attempts, {"db1-fib-0001": 2})
            finally:
                driver.quit()

    def test_chart_truth_saved_verdict_restores_in_new_browser_session(self) -> None:
        api_state = VerifiedChartTruthApiState()
        with running_review_servers(api_state) as urls:
            first_driver = _create_driver(urls.api_base_url)
            second_driver = None
            try:
                first_wait = WebDriverWait(first_driver, 60)
                first_driver.get(urls.ui_url.replace("/index.html", "/chart-truth.html"))

                first_body = first_wait.until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                first_wait.until(
                    lambda browser: first_body.get_attribute("data-chart-truth-state") == "synced"
                )
                first_driver.find_element(By.ID, "chart-truth-verdict-down").click()
                first_wait.until(
                    lambda browser: first_body.get_attribute("data-chart-truth-verdict") == "down"
                )
                first_driver.find_element(By.ID, "chart-truth-save-verdict").click()
                first_wait.until(
                    lambda browser: first_body.get_attribute("data-chart-truth-saved-verdict") == "down"
                )
            finally:
                first_driver.quit()

            second_driver = _create_driver(urls.api_base_url)
            try:
                second_wait = WebDriverWait(second_driver, 60)
                second_driver.get(urls.ui_url.replace("/index.html", "/chart-truth.html"))

                second_body = second_wait.until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                second_wait.until(
                    lambda browser: second_body.get_attribute("data-chart-truth-state") == "synced"
                )
                second_wait.until(
                    lambda browser: second_body.get_attribute("data-chart-truth-saved-verdict") == "down"
                )

                self.assertEqual(
                    second_driver.find_element(By.ID, "chart-truth-selected-verdict").text.strip(),
                    "Selected verdict: DOWN",
                )
                self.assertEqual(
                    second_driver.find_element(By.ID, "chart-truth-save-status").text.strip(),
                    "Saved verdict: DOWN",
                )
                self.assertEqual(
                    second_driver.find_element(By.ID, "chart-truth-verdict-down").get_attribute("aria-pressed"),
                    "true",
                )
            finally:
                second_driver.quit()


if __name__ == "__main__":
    unittest.main()