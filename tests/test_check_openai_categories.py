"""Offline checks for the manual OpenAI smoke runner; no real API calls."""
import contextlib
import importlib
import io
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import check_openai_categories as smoke
from backend.classifier import PredictionResult
from backend.llm_classifier import LLMError


class CategorySmokeTests(unittest.TestCase):
    def test_preview_needs_no_key_or_backend_app(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch.object(smoke, "run_checks") as run:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(smoke.main([]), 0)
        run.assert_not_called()
        self.assertIn("Preview only", output.getvalue())
        self.assertEqual(len(smoke.EXAMPLES), 7)
        self.assertEqual(len({category for category, _ in smoke.EXAMPLES}), 7)

    def test_missing_key_stops_before_requests(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ValueError):
                smoke.run_checks()

    def test_route_results_storage_cleanup_and_fallback_detection(self):
        # Import app inside isolated storage even when this test is run on its own.
        with tempfile.TemporaryDirectory() as directory:
            with smoke.temporary_environment({"REVIEW_CSV_PATH": str(Path(directory) / "reviews.csv")}):
                app_module = importlib.import_module("backend.app")

        original_factory = app_module.create_app
        paths = []

        def capture_factory(*args, **kwargs):
            paths.append(Path(kwargs["case_db_path"]))
            return original_factory(*args, **kwargs)

        def model_response(request, timeout):
            payload = json.loads(request.data)
            text = json.loads(payload["messages"][1]["content"])["ticket"]
            category = next(label for label, example in smoke.EXAMPLES if example == text)
            content = json.dumps({"category": category, "confidence": .9})
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "offline-placeholder", "OPENAI_MODEL": "gpt-4.1-mini",
            "LLM_PROVIDER": "baseline", "LLM_CATEGORIES": "", "LLM_TIMEOUT_SECONDS": "8",
            "REVIEW_CSV_PATH": "original-review-path",
        }):
            with patch.object(app_module, "create_app", side_effect=capture_factory):
                with patch("backend.openai_classifier.urlopen", side_effect=model_response) as network:
                    results = smoke.run_checks()
                self.assertEqual(network.call_count, 7)
                self.assertTrue(all(result.passed for result in results))
                self.assertEqual(os.environ["LLM_PROVIDER"], "baseline")
                self.assertEqual(os.environ["REVIEW_CSV_PATH"], "original-review-path")
                self.assertTrue(all(not path.parent.exists() for path in paths))

                with patch.object(app_module, "classify_with_openai", side_effect=LLMError("offline")):
                    with patch.object(app_module, "predict_ticket",
                                      return_value=PredictionResult("Shipping", .9, "baseline")):
                        results = smoke.run_checks()
                shipping = next(result for result in results if result.expected == "Shipping")
                self.assertEqual(shipping.actual, "Shipping")
                self.assertTrue(shipping.saved_ok)
                self.assertFalse(shipping.provider_ok)
                self.assertFalse(shipping.passed)

    def test_wrong_category_or_missing_saved_case_cannot_pass(self):
        self.assertFalse(smoke.CheckResult("Shipping", "Orders", True, True).passed)
        self.assertFalse(smoke.CheckResult("Shipping", "Shipping", True, False).passed)


if __name__ == "__main__":
    unittest.main()
