"""Actual application/evaluation execution paths with fake provider transport."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend.app import create_app
from backend.evaluation import evaluate, batching
from backend.tickets.categories import DATASET_CATEGORIES
from backend.llms import openai, gemini
from backend.observation.integration import install_evaluation
from backend.observation.tracing import run_scope
from backend.observation.database import DEFAULT_CONFIG
from backend.observation import store


class Response(BytesIO):
    status = 200
    headers = {"x-request-id": "request-example", "x-ratelimit-remaining-requests": "99",
               "authorization": "must-not-be-saved", "set-cookie": "private"}

    def __init__(self, provider="openai", result=None, usage=True):
        result = result or {"category": "ACCOUNT", "confidence": .9}
        text = json.dumps(result)
        if provider == "openai":
            envelope = {"model": "gpt-4.1-mini", "choices": [
                {"finish_reason": "stop", "message": {"content": text}}]}
            if usage:
                envelope["usage"] = {"prompt_tokens": 100, "completion_tokens": 20,
                    "total_tokens": 120, "prompt_tokens_details": {"cached_tokens": 10}}
        else:
            envelope = {"modelVersion": "gemini-3.5-flash-lite", "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
            if usage:
                envelope["usageMetadata"] = {"promptTokenCount": 100, "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 5, "cachedContentTokenCount": 10, "totalTokenCount": 125}
        super().__init__(json.dumps(envelope).encode())


class ObservationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.db = self.directory / "observation.sqlite3"
        self.config_path = self.directory / "config.json"
        self.config = json.loads(DEFAULT_CONFIG.read_text())
        self.config["database"]["path"] = str(self.db)
        self.config["recording"]["enabled"] = True
        self.save_config()
        env = patch.dict(os.environ, {
            "OBSERVATION_CONFIG": str(self.config_path), "OPENAI_API_KEY": "fake-private-key",
            "GEMINI_API_KEY": "fake-private-key", "OPENAI_MODEL": "gpt-4.1-mini",
            "GEMINI_MODEL": "gemini-3.5-flash-lite", "LLM_CATEGORIES": "",
            "LLM_TIMEOUT_SECONDS": "8", "LLM_PROVIDER": "openai",
        })
        env.start()
        self.addCleanup(env.stop)
        # No real network access is permitted in any test.
        for target in ("backend.llms.openai.urlopen", "backend.llms.gemini.urlopen",
                       "backend.evaluation.batching.urlopen", "backend.evaluation.provider_limits.urlopen"):
            blocker = patch(target, side_effect=AssertionError("Unexpected network call"))
            blocker.start()
            self.addCleanup(blocker.stop)
        for target in ("backend.evaluation.evaluate.sleep", "backend.llms.retry.sleep"):
            sleeper = patch(target)
            sleeper.start()
            self.addCleanup(sleeper.stop)
        app = create_app(review_path=self.directory / "reviews.csv")
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.tickets = [{"ticket_id": str(n), "text": "account locked", "expected": "ACCOUNT"} for n in range(2)]
        self.env = {"OPENAI_API_KEY": "fake-private-key", "GEMINI_API_KEY": "fake-private-key",
                    "EVALUATION_REQUEST_INTERVAL_SECONDS": "0"}

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def rows(self):
        if not self.db.exists():
            return []
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM observations ORDER BY created_at")]

    def post(self, provider="openai"):
        return self.client.post("/classify", json={"text": "account locked", "provider": provider})

    def test_both_app_providers_record_actual_models_usage_cost_and_ticket(self):
        for provider in ("openai", "gemini"):
            with patch(f"backend.llms.{provider}.urlopen", return_value=Response(provider)):
                response = self.post(provider)
            self.assertEqual(response.status_code, 200)
            row = self.rows()[-1]
            self.assertEqual(row["source"], "application")
            self.assertEqual(row["provider"], provider)
            self.assertEqual(row["model"], os.environ[provider.upper() + "_MODEL"])
            self.assertIsNone(row["error_json"])
            metadata = json.loads(row["request_json"])["_observation"]
            self.assertEqual(metadata["ticket_id"], response.json["ticket_id"])
            self.assertEqual(metadata["prompt_version"], "V1")
            metrics = json.loads(row["response_json"])["_observation"]
            self.assertEqual(metrics["input_tokens"], 100)
            expected = .000069 if provider == "openai" else .0000898
            self.assertAlmostEqual(metrics["estimated_standard_cost_usd"], expected)
            self.assertEqual(metrics["response_headers"]["x-request-id"], "request-example")
            self.assertGreaterEqual(metrics["duration_seconds"], 0)
            self.assertTrue(row["completed_at"])
        raw = json.dumps(self.rows())
        for secret in ("fake-private-key", "must-not-be-saved", "set-cookie"):
            self.assertNotIn(secret, raw)
        self.assertEqual(len({r["run_id"] for r in self.rows()}), 2)

    def test_retry_records_failed_attempt_then_success_in_same_run(self):
        error = HTTPError("https://example.invalid", 429, "busy", {}, BytesIO(b'{"error":{"code":"rate_limit"}}'))
        with patch("backend.llms.openai.urlopen", side_effect=[error, Response()]) as transport:
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(transport.call_count, 2)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_id"], rows[1]["run_id"])
        self.assertIsNotNone(rows[0]["error_json"])
        self.assertIsNone(rows[1]["error_json"])
        self.assertEqual(json.loads(rows[1]["request_json"])["_observation"]["attempt_number"], 2)

    def test_invalid_classification_records_error_despite_http_success(self):
        with patch("backend.llms.openai.urlopen", return_value=Response(result={"category":"INVALID","confidence":.9})):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        row = self.rows()[0]
        self.assertIn("unknown category", row["error_json"])
        self.assertEqual(json.loads(row["response_json"])["_observation"]["http_status"], 200)

    def test_timeout_and_fallback_keep_failure_and_ticket_link(self):
        with patch("backend.llms.openai.urlopen", side_effect=TimeoutError("timeout fake-private-key")):
            response = self.client.post("/classify", json={"text":"account locked"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["fallback_used"])
        row = self.rows()[0]
        self.assertIsNone(row["response_json"])
        self.assertIn("TimeoutError", row["error_json"])
        self.assertNotIn("fake-private-key", row["error_json"])
        self.assertTrue(json.loads(row["request_json"])["_observation"]["fallback_used"])

    def test_recording_disabled_or_filtered_does_not_write(self):
        for enabled, sources in ((False, ["application"]), (True, ["evaluation"])):
            self.config["recording"].update(enabled=enabled, sources=sources)
            self.save_config()
            with patch("backend.llms.openai.urlopen", return_value=Response()):
                self.assertEqual(self.post().status_code, 200)
        self.assertFalse(self.db.exists())

    def test_bad_config_or_database_failure_does_not_break_classification(self):
        self.config_path.write_text("not json")
        with patch("backend.llms.openai.urlopen", return_value=Response()):
            self.assertEqual(self.post().status_code, 200)
        self.save_config()
        with patch("backend.observation.store.start", side_effect=sqlite3.OperationalError("private detail")), patch(
                "backend.llms.openai.urlopen", return_value=Response()):
            self.assertEqual(self.post().status_code, 200)
        with patch("backend.observation.store.finish", side_effect=sqlite3.OperationalError()), patch(
                "backend.llms.openai.urlopen", return_value=Response()):
            self.assertEqual(self.post().status_code, 200)

    def test_locked_database_does_not_break_classification(self):
        with closing(store.connect(self.config)) as lock:
            store.schema(lock)
            lock.commit()
            lock.execute("BEGIN EXCLUSIVE")
            with patch("backend.llms.openai.urlopen", return_value=Response()):
                self.assertEqual(self.post().status_code, 200)
            lock.rollback()
        self.assertEqual(self.rows(), [])

    def test_evaluation_single_run_groups_requests_and_preserves_predictions(self):
        install_evaluation()
        install_evaluation()  # rerendering must not duplicate records
        with patch("backend.evaluation.evaluate.load_env", return_value=self.env), patch(
                "backend.llms.openai.urlopen", side_effect=lambda *a, **k: Response()):
            results = evaluate.run_evaluation(self.tickets, provider="openai-v2")
        self.assertTrue(all(r["correct"] for r in results))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["source"] for r in rows}, {"evaluation"})
        self.assertEqual(len({r["run_id"] for r in rows}), 1)
        for row in rows:
            self.assertEqual(json.loads(row["request_json"])["_observation"]["prompt_version"], "V2")
        with patch("backend.evaluation.evaluate.load_env", return_value=self.env), patch(
                "backend.llms.gemini.urlopen", return_value=Response("gemini")):
            evaluate.run_evaluation(self.tickets[:1], provider="gemini-v1")
        self.assertNotEqual(rows[0]["run_id"], self.rows()[-1]["run_id"])

    def test_evaluation_batch_captures_one_request_for_both_tickets(self):
        install_evaluation()
        def batch_response(request, **kwargs):
            payload = json.loads(request.data)
            items = json.loads(payload["messages"][1]["content"])["tickets"]
            return Response(result={"results": [
                {"id": item["id"], "category":"ACCOUNT", "confidence":.9} for item in items]})
        with patch("backend.evaluation.evaluate.load_env", return_value=self.env), patch(
                "backend.evaluation.batching.urlopen", side_effect=batch_response):
            results = evaluate.run_evaluation(self.tickets, provider="openai-v1", batch=True)
        self.assertTrue(all(r["correct"] for r in results))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["request_json"])["_observation"]["batch_size"], 2)

    def test_invalid_batch_is_marked_failed(self):
        install_evaluation()
        with patch("backend.evaluation.evaluate.load_env", return_value=self.env), patch(
                "backend.evaluation.batching.urlopen", return_value=Response(result={"results":[]})):
            results = evaluate.run_evaluation(self.tickets, provider="openai-v1", batch=True)
        self.assertTrue(all(r["error"] for r in results))
        self.assertIn("Incomplete batch", self.rows()[0]["error_json"])

    def test_baseline_and_unscoped_calls_do_not_generate_llm_records(self):
        install_evaluation()
        evaluate.run_evaluation(self.tickets, provider="baseline")
        self.assertEqual(self.post("baseline").status_code, 200)
        openai.classify_with_openai("account", api_key="fake-private-key",
                                    categories=DATASET_CATEGORIES, opener=lambda *a, **k: Response())
        self.assertEqual(self.rows(), [])

    def test_parallel_sources_keep_their_own_run_context(self):
        with closing(store.connect(self.config)) as db:
            store.schema(db)
            db.commit()
        def classify(source):
            with run_scope(source):
                return openai.classify_with_openai("account", api_key="fake-private-key",
                    categories=DATASET_CATEGORIES, opener=lambda *a, **k: Response())
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(classify, ["application", "evaluation"]))
        rows = self.rows()
        self.assertEqual({r["source"] for r in rows}, {"application", "evaluation"})
        self.assertEqual(len({r["run_id"] for r in rows}), 2)

    def test_bounded_payload_marks_truncation_and_unknown_usage(self):
        self.config["recording"]["max_content_bytes"] = 1024
        self.save_config()
        with patch("backend.llms.openai.urlopen", return_value=Response(usage=False)):
            self.post()
        row = self.rows()[0]
        self.assertTrue(json.loads(row["request_json"])["truncated"])
        self.assertIsNone(json.loads(row["response_json"])["_observation"]["estimated_standard_cost_usd"])


if __name__ == "__main__":
    unittest.main()
