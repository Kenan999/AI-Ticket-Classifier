"""Offline OpenAI integration tests; all network responses are simulated."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from backend.app import create_app
from backend.classifier import MODEL_VERSION
from backend.llm_classifier import LLMError
from backend.openai_classifier import classify_with_openai, MAX_RESPONSE_BYTES


def response(category="ACCOUNT", confidence=.91):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content":
        json.dumps({"category": category, "confidence": confidence})}}]}).encode())


class OpenAIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-placeholder",
            "OPENAI_MODEL": "gpt-4.1-mini", "LLM_TIMEOUT_SECONDS": "8",
            "LLM_CATEGORIES": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app(review_path=Path(self.temp.name) / "reviews.csv")
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def classify(self):
        return self.client.post("/classify", json={"text": "My package has not arrived"})

    def test_route_calls_adapter_and_persists_valid_result(self):
        def fake_open(req, timeout):
            self.assertEqual(req.full_url, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(req.get_header("Authorization"), "Bearer test-placeholder")
            payload = json.loads(req.data)
            self.assertEqual(payload["model"], "gpt-4.1-mini")
            self.assertEqual(timeout, 8)
            self.assertEqual(json.loads(payload["messages"][1]["content"])["ticket"],
                             "My package has not arrived")
            return response()
        with patch("backend.openai_classifier.urlopen", side_effect=fake_open) as request:
            result = self.classify()
        request.assert_called_once()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["category"], "ACCOUNT")
        self.assertEqual(result.json["model_version"], "openai:gpt-4.1-mini")
        self.assertFalse(result.json["reply_confirmed"])
        self.assertNotIn("test-placeholder", result.get_data(as_text=True))
        saved = self.client.get("/case/" + result.json["ticket_id"]).json
        self.assertEqual(saved, result.json)

    def test_missing_key_never_calls_provider(self):
        os.environ.pop("OPENAI_API_KEY")
        with patch("backend.openai_classifier.urlopen") as request:
            result = self.classify()
        request.assert_not_called()
        self.assertEqual(result.json["model_version"], MODEL_VERSION)

    def test_baseline_never_calls_openai_even_with_key(self):
        os.environ["LLM_PROVIDER"] = "baseline"
        with patch("backend.openai_classifier.urlopen") as request:
            result = self.classify()
        request.assert_not_called()
        self.assertEqual(result.json["model_version"], MODEL_VERSION)

    def test_network_failure_falls_back_without_logging_secrets(self):
        with patch("backend.openai_classifier.urlopen", side_effect=URLError("test-placeholder")):
            with self.assertLogs(self.app.logger, level="WARNING") as logs:
                result = self.classify()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["category"], "DELIVERY")
        self.assertEqual(result.json["model_version"], MODEL_VERSION)
        self.assertNotIn("test-placeholder", " ".join(logs.output))

    def test_bad_provider_output_falls_back(self):
        for category, confidence in [("Unknown", .9), ("ACCOUNT", True),
                                     ("ACCOUNT", -1), ("ACCOUNT", 2), ("ACCOUNT", "high")]:
            with self.subTest(category=category, confidence=confidence):
                with patch("backend.openai_classifier.urlopen", return_value=response(category, confidence)):
                    result = self.classify()
                self.assertEqual(result.json["model_version"], MODEL_VERSION)

    def test_malformed_or_oversized_response_falls_back(self):
        for body in [b"not json", b"{}", b"x" * (MAX_RESPONSE_BYTES + 1)]:
            with self.subTest(size=len(body)):
                with patch("backend.openai_classifier.urlopen", return_value=io.BytesIO(body)):
                    result = self.classify()
                self.assertEqual(result.json["model_version"], MODEL_VERSION)

    def test_low_confidence_requires_human_review(self):
        with patch("backend.openai_classifier.urlopen", return_value=response(confidence=.2)):
            result = self.classify()
        self.assertTrue(result.json["review_required"])
        self.assertEqual(result.json["status"], "human_review")

    def test_invalid_timeout_avoids_network(self):
        os.environ["LLM_TIMEOUT_SECONDS"] = "invalid"
        with patch("backend.openai_classifier.urlopen") as request:
            result = self.classify()
        request.assert_not_called()
        self.assertEqual(result.json["model_version"], MODEL_VERSION)


if __name__ == "__main__":
    unittest.main()
