"""Retry and batch failure tests using only local responses and a fake clock."""

from email.message import Message
import io
import json
import unittest
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError

from backend.llms.gemini import DEFAULT_CATEGORIES, LLMError, classify_with_gemini
from backend.llms.openai import classify_with_openai
from evaluation.evaluate import run_evaluation


def provider_error(status, payload=None, **header_values):
    headers = Message()
    for name, value in header_values.items():
        headers[name.replace("_", "-")] = value
    body = io.BytesIO(json.dumps(payload or {}).encode())
    return HTTPError("https://example.test", status, "test HTTP error", headers, body)


def success_response(provider):
    result = json.dumps({"category": "ACCOUNT", "confidence": 0.9})
    if provider == "Gemini":
        payload = {"candidates": [{"content": {"parts": [{"text": result}]}}]}
    else:
        payload = {"choices": [{"message": {"content": result}}]}
    return io.BytesIO(json.dumps(payload).encode())


class ProviderRetryTests(unittest.TestCase):
    def setUp(self):
        pacing = patch("evaluation.evaluate.sleep")
        self.addCleanup(pacing.stop)
        self.pacing = pacing.start()
        self.now = 0
        clock = patch("backend.llms.retry.monotonic", side_effect=lambda: self.now)
        waits = patch("backend.llms.retry.sleep", side_effect=self.advance)
        jitter = patch("backend.llms.retry.uniform", return_value=0)
        for mocked in (clock, waits, jitter):
            self.addCleanup(mocked.stop)
        clock.start()
        self.waits = waits.start()
        jitter.start()

    def advance(self, seconds):
        self.now += seconds

    def test_both_providers_retry_rate_limit_and_service_unavailable(self):
        for provider, classify in (("Gemini", classify_with_gemini), ("OpenAI", classify_with_openai)):
            with self.subTest(provider=provider):
                self.waits.reset_mock()
                opener = Mock(side_effect=[
                    provider_error(429, Retry_After="2"),
                    provider_error(503),
                    success_response(provider),
                ])
                result = classify("My account is locked", api_key="test",
                                  categories=DEFAULT_CATEGORIES, opener=opener)
                self.assertEqual(result.category, "ACCOUNT")
                self.assertEqual(self.waits.call_args_list, [call(2), call(1)])
                self.assertEqual([attempt.kwargs["timeout"] for attempt in opener.call_args_list],
                                 [8, 6, 5])

    def test_gemini_retry_info_can_exceed_time_budget(self):
        error = provider_error(429, {"error": {"details": [{
            "@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "9.25s",
        }]}})
        opener = Mock(side_effect=error)
        with self.assertRaisesRegex(LLMError, "retry wait exceeds timeout"):
            classify_with_gemini("My account is locked", api_key="test",
                                 categories=DEFAULT_CATEGORIES, opener=opener)
        opener.assert_called_once()
        self.waits.assert_not_called()

    def test_openai_quota_and_auth_errors_fail_immediately(self):
        for error, message in (
            (provider_error(429, {"error": {"code": "insufficient_quota"}}), "quota exhausted"),
            (provider_error(401), "HTTP 401"),
        ):
            with self.subTest(code=error.code):
                opener = Mock(side_effect=error)
                with self.assertRaisesRegex(LLMError, message):
                    classify_with_openai("My account is locked", api_key="test",
                                         categories=DEFAULT_CATEGORIES, opener=opener)
                opener.assert_called_once()
                self.waits.assert_not_called()

    def test_batch_continues_with_next_ticket_after_retry_exhaustion(self):
        tickets = [
            {"ticket_id": "first", "text": "My account is locked", "expected": "ACCOUNT"},
            {"ticket_id": "second", "text": "I cannot sign in", "expected": "ACCOUNT"},
        ]
        with patch("backend.llms.openai.urlopen", side_effect=[
            provider_error(429), provider_error(429), provider_error(429), success_response("OpenAI"),
        ]) as opener, patch("evaluation.evaluate.load_env", return_value={"OPENAI_API_KEY": "test"}):
            first, second = run_evaluation(tickets, provider="openai-v1")
        self.assertEqual(opener.call_count, 4)
        self.assertEqual(self.waits.call_args_list, [call(0.5), call(1)])
        self.assertIn("rate limit (HTTP 429); retries exhausted", first["error"])
        self.assertFalse(first["correct"])
        self.assertEqual(second["error"], "")
        self.assertTrue(second["correct"])


    def test_batch_budget_allows_long_wait_but_caps_request_timeout(self):
        for name, classify in [("Gemini", classify_with_gemini), ("OpenAI", classify_with_openai)]:
            opener = Mock(side_effect=[provider_error(429, Retry_After="60"), success_response(name)])
            result = classify("My account is locked", api_key="test", categories=DEFAULT_CATEGORIES,
                              opener=opener, retry_budget=120)
            self.assertEqual(result.category, "ACCOUNT")
            self.assertEqual(opener.call_args_list[-1].kwargs['timeout'], 8)

    def test_evaluation_paces_cloud_but_not_rules(self):
        tickets = [{'text':'account', 'expected':'ACCOUNT'}] * 3
        with patch('evaluation.evaluate.classify_ticket', return_value=('ACCOUNT', .9, 'test', '')), patch('evaluation.evaluate.load_env', return_value={}):
            run_evaluation(tickets, provider='openai-v1')
            self.assertEqual(self.pacing.call_args_list, [call(6), call(6)])
            self.pacing.reset_mock()
            run_evaluation(tickets, provider='baseline')
            self.pacing.assert_not_called()

    def test_evaluation_default_waits_three_minutes_but_remains_bounded(self):
        from evaluation.config import RETRY_BUDGET_SECONDS
        self.assertEqual(RETRY_BUDGET_SECONDS, 300)
        tickets = [{"text": "My account is locked", "expected": "ACCOUNT"}]
        with patch("evaluation.evaluate.load_env", return_value={"GEMINI_API_KEY": "test"}), patch(
            "backend.llms.gemini.urlopen", side_effect=[
                provider_error(429, {"error": {"details": [{
                    "@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "180s"
                }]}}), success_response("Gemini")
            ]) as opener:
            rows = run_evaluation(tickets, provider="gemini-v1")
        self.assertFalse(rows[0]["error"])
        self.assertEqual(opener.call_count, 2)
        self.waits.assert_called_once_with(180)
        self.waits.reset_mock()
        with patch("evaluation.evaluate.load_env", return_value={"GEMINI_API_KEY": "test"}), patch(
            "backend.llms.gemini.urlopen", side_effect=provider_error(429, Retry_After="400")
        ) as opener:
            rows = run_evaluation(tickets, provider="gemini-v1")
        self.assertIn("requested 400.0s", rows[0]["error"])
        self.assertIn("total budget 300.0s", rows[0]["error"])
        opener.assert_called_once()
        self.waits.assert_not_called()
