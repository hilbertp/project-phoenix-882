from __future__ import annotations

import unittest

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.test_c9_review_surface_recovery import (
    FakeReviewApiState,
    _create_driver,
    running_review_servers,
)


class ReviewSurfaceConfidenceTests(unittest.TestCase):
    def test_latest_submission_and_session_context_render_after_submit(self) -> None:
        api_state = FakeReviewApiState()
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                note_input = wait.until(
                    EC.presence_of_element_located((By.ID, "review-note-input"))
                )
                good_enough_button = wait.until(
                    EC.presence_of_element_located((By.ID, "good-enough-button"))
                )

                wait.until(lambda browser: good_enough_button.is_enabled())
                note_input.clear()
                note_input.send_keys("confidence note")
                good_enough_button.click()

                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 2"
                )

                latest_heading = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-heading"))
                )
                latest_structure = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-structure"))
                )
                latest_outcome = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-outcome"))
                )
                latest_note = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-note"))
                )
                latest_timestamp = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-timestamp"))
                )
                session_previous_action = wait.until(
                    EC.presence_of_element_located((By.ID, "session-previous-action"))
                )
                session_next_target = wait.until(
                    EC.presence_of_element_located((By.ID, "session-next-target"))
                )
                trail_list = wait.until(
                    EC.presence_of_element_located((By.ID, "session-trail-list"))
                )

                self.assertIn("db1-fib-0001", latest_heading.text)
                self.assertEqual(latest_structure.text.strip(), "db1-fib-0001")
                self.assertEqual(latest_outcome.text.strip(), "okay (good_enough)")
                self.assertEqual(latest_note.text.strip(), 'note: "confidence note"')
                self.assertIn("2026-03-31", latest_timestamp.text)
                self.assertIn("db1-fib-0001", session_previous_action.text)
                self.assertIn('note: "confidence note"', session_previous_action.text)
                self.assertEqual(session_next_target.text.strip(), "db1-fib-0002")
                self.assertIn("db1-fib-0001", trail_list.text)
                self.assertIn("okay (good_enough)", trail_list.text)
                self.assertIn("confidence note", trail_list.text)
            finally:
                driver.quit()

    def test_session_trail_persists_across_refresh(self) -> None:
        api_state = FakeReviewApiState()
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                note_input = wait.until(
                    EC.presence_of_element_located((By.ID, "review-note-input"))
                )
                adjusted_accept_button = wait.until(
                    EC.presence_of_element_located((By.ID, "adjusted-accept-button"))
                )

                wait.until(lambda browser: adjusted_accept_button.is_enabled())
                note_input.clear()
                note_input.send_keys("persisted note")
                adjusted_accept_button.click()

                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 2"
                )
                driver.refresh()

                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 2"
                )
                latest_structure = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-structure"))
                )
                latest_outcome = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-outcome"))
                )
                latest_note = wait.until(
                    EC.presence_of_element_located((By.ID, "latest-submission-note"))
                )
                session_previous_action = wait.until(
                    EC.presence_of_element_located((By.ID, "session-previous-action"))
                )
                trail_list = wait.until(
                    EC.presence_of_element_located((By.ID, "session-trail-list"))
                )

                self.assertEqual(latest_structure.text.strip(), "db1-fib-0001")
                self.assertEqual(latest_outcome.text.strip(), "meh (adjusted_accept)")
                self.assertEqual(latest_note.text.strip(), 'note: "persisted note"')
                self.assertIn("db1-fib-0001", session_previous_action.text)
                self.assertIn('note: "persisted note"', session_previous_action.text)
                self.assertIn("meh (adjusted_accept)", trail_list.text)
                self.assertIn("persisted note", trail_list.text)
            finally:
                driver.quit()


if __name__ == "__main__":
    unittest.main()