"""Offline tests: never call the real Gemini API and never require an API key."""
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
from backend.llm_classifier import (
    DEFAULT_CATEGORIES, LLMError, classify_with_gemini, configured_categories,
)


class MockResponse:
    def __init__(self, payload):
        self.stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.stream.read(limit)


def gemini_output(category, confidence):
    return {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps({
                "category": category, "confidence": confidence,
            })}]}
        }]
    }


class GeminiTests(unittest.TestCase):
    def test_default_categories_match_existing_frontend(self):
        self.assertEqual(len(configured_categories("")), 7)
        self.assertEqual(configured_categories(""), DEFAULT_CATEGORIES)

    def test_categories_can_change_without_changing_code(self):
        self.assertEqual(configured_categories("Delivery,Refund,Payment,Order,Account"),
                         ("Delivery", "Refund", "Payment", "Order", "Account"))
        for invalid in ("Account,Account", "OnlyOne", "Account,,Refund", "Bad/Name,Good"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                configured_categories(invalid)

    def test_gemini_request_and_json_output(self):
        def fake_open(req, timeout):
            self.assertEqual(req.get_method(), "POST")
            self.assertIn("gemini-3.1-flash-lite:generateContent", req.full_url)
            self.assertEqual(req.get_header("X-goog-api-key"), "test-only-key")
            self.assertEqual(timeout, 8)
            body = json.loads(req.data)
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            self.assertIn("Shipping", body["systemInstruction"]["parts"][0]["text"])
            self.assertIn("package is delayed", body["contents"][0]["parts"][0]["text"])
            return MockResponse(gemini_output("Shipping", 0.89))

        result = classify_with_gemini(
            "My package is delayed", api_key="test-only-key",
            categories=DEFAULT_CATEGORIES, opener=fake_open,
        )
        self.assertEqual(result.category, "Shipping")
        self.assertEqual(result.confidence, 0.89)
        self.assertEqual(result.model_version, "gemini:gemini-3.1-flash-lite")

    def test_custom_category(self):
        result = classify_with_gemini(
            "I want a refund", api_key="test", categories=("Refund", "Order"),
            opener=lambda req, timeout: MockResponse(gemini_output("Refund", .8)),
        )
        self.assertEqual(result.category, "Refund")

    def test_invalid_model_response_rejected(self):
        for category, confidence in (
            ("NotAllowed", .9), ("Account", 2.5), ("Account", "certain"),
            ("Account", True), ("Account", -0.2),
        ):
            with self.subTest(category=category, confidence=confidence):
                with self.assertRaises(LLMError):
                    classify_with_gemini("My account is locked", api_key="test",
                        categories=DEFAULT_CATEGORIES,
                        opener=lambda req, timeout: MockResponse(
                            gemini_output(category, confidence)),
                    )

    def test_network_failure_raises_llm_error(self):
        with self.assertRaises(LLMError):
            classify_with_gemini("My order is late", api_key="test",
                categories=DEFAULT_CATEGORIES,
                opener=lambda req, timeout: (_ for _ in ()).throw(URLError("offline")),
            )

    def test_missing_key_fails_closed_in_adapter(self):
        with self.assertRaises(LLMError):
            classify_with_gemini("My order is late", api_key="",
                categories=DEFAULT_CATEGORIES)

    def test_provider_switch_preserves_endpoint_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(review_path=Path(tmp) / "reviews.csv")
            app.config["TESTING"] = True
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "test-only-key",
            }):
                with patch("backend.app.classify_with_gemini", return_value=
                           classify_with_gemini("abc", api_key="test",
                                categories=DEFAULT_CATEGORIES,
                                opener=lambda req, timeout:
                                    MockResponse(gemini_output("Account", 0.93)))):
                    response = app.test_client().post("/classify", json={
                        "text": "I cannot sign in to my account",
                    })
            self.assertEqual(response.status_code, 200)
            result = response.json
            self.assertEqual(result["category"], "Account")
            self.assertEqual(result["status"], "classified")
            self.assertEqual(result["model_version"], "gemini:gemini-3.1-flash-lite")
            self.assertFalse(result["reply_confirmed"])
            self.assertEqual(app.test_client().get("/case/" + result["ticket_id"]).json["category"], "Account")

    def test_five_mvp_examples_through_backend_using_mock_model(self):
        # Five distinct categories from IHK-028; no real API access or billing.
        examples = (
            ("My parcel has not arrived and tracking is stuck.", "Delivery"),
            ("I returned my shoes and need a refund.", "Refund"),
            ("My credit card payment failed at checkout.", "Payment"),
            ("I want to change an item in my order.", "Order"),
            ("I cannot log in to my account.", "Account"),
        )
        labels = tuple(label for _, label in examples)
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(review_path=Path(tmp) / "reviews.csv")
            app.config["TESTING"] = True
            for ticket, label in examples:
                with self.subTest(category=label), patch.dict(os.environ, {
                    "LLM_PROVIDER": "gemini",
                    "GEMINI_API_KEY": "mock-only-key",
                    "LLM_CATEGORIES": ",".join(labels),
                }):
                    with patch("backend.app.classify_with_gemini", return_value=
                               classify_with_gemini(ticket, api_key="mock-only-key",
                                   categories=labels,
                                   opener=lambda req, timeout: MockResponse(
                                       gemini_output(label, .91)))):
                        response = app.test_client().post("/classify", json={"text": ticket})
                    self.assertEqual(response.status_code, 200)
                    data = response.json
                    self.assertEqual(data["category"], label)
                    self.assertEqual(data["status"], "classified")
                    self.assertEqual(app.test_client().get("/case/" + data["ticket_id"]).json["category"], label)
            result = app.test_client().get("/cases").json
            self.assertEqual(len(result), 5)
            self.assertEqual({ticket["category"] for ticket in result}, set(labels))

    def test_fallback_when_gemini_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(review_path=Path(tmp) / "reviews.csv")
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "test-only-key",
            }):
                with patch("backend.app.classify_with_gemini", side_effect=LLMError("offline")):
                    response = app.test_client().post("/classify", json={
                        "text": "My package has not arrived",
                    })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["category"], "Shipping")
            self.assertEqual(response.json["model_version"], MODEL_VERSION)


if __name__ == "__main__":
    unittest.main()
