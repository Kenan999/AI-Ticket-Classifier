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
from backend.classifier import CATEGORY_GUIDANCE, MODEL_VERSION
from backend.llm_classifier import (
    DEFAULT_CATEGORIES, LLMError, classify_with_gemini, configured_categories,
)

from evaluation.evaluate import classify_ticket
from evaluation.prompts import DEFAULT_PROMPT_VERSION, PROMPTS, render_prompt


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
    def test_default_categories_match_bitext(self):
        self.assertEqual(len(configured_categories("")), 9)
        self.assertEqual(configured_categories(""), DEFAULT_CATEGORIES)

    def test_categories_are_fixed_to_nine_exact_labels(self):
        # Deployment may change the order but cannot choose another label set.
        self.assertEqual(configured_categories(",".join(reversed(DEFAULT_CATEGORIES))),
                         DEFAULT_CATEGORIES)
        for invalid in ("Account,Account", "OnlyOne", "ACCOUNT,,REFUND",
                        "Bad/Name,GOOD", "Shipping,Billing"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                configured_categories(invalid)

    def test_gemini_request_and_json_output(self):
        def fake_open(req, timeout):
            self.assertEqual(req.get_method(), "POST")
            self.assertIn("gemini-3.5-flash-lite:generateContent", req.full_url)
            self.assertEqual(req.get_header("X-goog-api-key"), "test-only-key")
            self.assertEqual(timeout, 8)
            body = json.loads(req.data)
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            default_prompt = render_prompt(
                DEFAULT_PROMPT_VERSION, "gemini", DEFAULT_CATEGORIES,
                category_guidance=CATEGORY_GUIDANCE,
            )
            self.assertEqual(body["systemInstruction"]["parts"][0]["text"], default_prompt)
            self.assertIn("package is delayed", body["contents"][0]["parts"][0]["text"])
            return MockResponse(gemini_output("SHIPPING", 0.89))

        result = classify_with_gemini(
            "My package is delayed", api_key="test-only-key",
            categories=DEFAULT_CATEGORIES, opener=fake_open,
        )
        self.assertEqual(result.category, "SHIPPING")
        self.assertEqual(result.confidence, 0.89)
        self.assertEqual(result.model_version, "gemini:gemini-3.5-flash-lite")

    def test_supplied_instructions_are_sent_verbatim(self):
        instructions = "First line.\nSecond line. "

        def fake_open(req, timeout):
            body = json.loads(req.data)
            self.assertEqual(body["systemInstruction"]["parts"][0]["text"], instructions)
            self.assertEqual(json.loads(body["contents"][0]["parts"][0]["text"]),
                             {"ticket": "My account is locked"})
            return MockResponse(gemini_output("ACCOUNT", 0.8))

        with patch("backend.llm_classifier.render_prompt") as render_default:
            result = classify_with_gemini(
                "My account is locked", api_key="test", categories=DEFAULT_CATEGORIES,
                instructions=instructions, opener=fake_open,
            )
        render_default.assert_not_called()
        self.assertEqual(result.category, "ACCOUNT")

    def test_invalid_supplied_instructions_are_rejected_before_request(self):
        for instructions in ("", " \n", 42):
            with self.subTest(instructions=instructions), patch("backend.llm_classifier.urlopen") as opener:
                with self.assertRaises(LLMError):
                    classify_with_gemini(
                        "My account is locked", api_key="test", categories=DEFAULT_CATEGORIES,
                        instructions=instructions,
                    )
                opener.assert_not_called()

    def test_evaluation_uses_the_selected_gemini_prompt(self):
        for version in ("V1", "V2", "V3"):
            template = f"{version} example for {{categories}}."
            with self.subTest(version=version), patch.dict(PROMPTS[version], {"gemini": template}):
                expected = render_prompt(
                    version, "gemini", DEFAULT_CATEGORIES, category_guidance=CATEGORY_GUIDANCE,
                )
                with patch("backend.llm_classifier.urlopen") as opener, patch(
                    "backend.llm_classifier.render_prompt",
                ) as render_default:
                    opener.return_value = MockResponse(gemini_output("ACCOUNT", 0.8))
                    category, _, _, error = classify_ticket(
                        "My account is locked", provider=f"gemini-{version.lower()}",
                        env={"GEMINI_API_KEY": "test"},
                    )
                request = opener.call_args.args[0]
                body = json.loads(request.data)
                self.assertEqual(body["systemInstruction"]["parts"][0]["text"], expected)
                render_default.assert_not_called()
                self.assertEqual((category, error), ("ACCOUNT", ""))

    def test_refund_category(self):
        result = classify_with_gemini(
            "I want a refund", api_key="test", categories=DEFAULT_CATEGORIES,
            opener=lambda req, timeout: MockResponse(gemini_output("REFUND", .8)),
        )
        self.assertEqual(result.category, "REFUND")

    def test_invalid_model_response_rejected(self):
        for category, confidence in (
            ("NotAllowed", .9), ("ACCOUNT", 2.5), ("ACCOUNT", "certain"),
            ("ACCOUNT", True), ("ACCOUNT", -0.2),
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
                                    MockResponse(gemini_output("ACCOUNT", 0.93)))):
                    response = app.test_client().post("/classify", json={
                        "text": "I cannot sign in to my account",
                    })
            self.assertEqual(response.status_code, 200)
            result = response.json
            self.assertEqual(result["category"], "ACCOUNT")
            self.assertEqual(result["status"], "classified")
            self.assertEqual(result["model_version"], "gemini:gemini-3.5-flash-lite")
            self.assertFalse(result["reply_confirmed"])
            self.assertEqual(app.test_client().get("/case/" + result["ticket_id"]).json["category"], "ACCOUNT")

    def test_five_mvp_examples_through_backend_using_mock_model(self):
        # Five distinct categories from IHK-028; no real API access or billing.
        examples = (
            ("My parcel has not arrived and tracking is stuck.", "DELIVERY"),
            ("I returned my shoes and need a refund.", "REFUND"),
            ("My credit card payment failed at checkout.", "PAYMENT"),
            ("I want to change an item in my order.", "ORDER"),
            ("I cannot log in to my account.", "ACCOUNT"),
        )
        labels = tuple(label for _, label in examples)
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(review_path=Path(tmp) / "reviews.csv")
            app.config["TESTING"] = True
            for ticket, label in examples:
                with self.subTest(category=label), patch.dict(os.environ, {
                    "LLM_PROVIDER": "gemini",
                    "GEMINI_API_KEY": "mock-only-key",
                    "LLM_CATEGORIES": ",".join(DEFAULT_CATEGORIES),
                }):
                    with patch("backend.app.classify_with_gemini", return_value=
                               classify_with_gemini(ticket, api_key="mock-only-key",
                                   categories=DEFAULT_CATEGORIES,
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
            self.assertEqual(response.json["category"], "DELIVERY")
            self.assertEqual(response.json["model_version"], MODEL_VERSION)


if __name__ == "__main__":
    unittest.main()
