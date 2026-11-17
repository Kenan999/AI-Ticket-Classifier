import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from evaluation.batching import pack, parse_results, request_batch, run
from evaluation.config import MODEL_LIMITS
from backend.llms.retry import LLMError

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.limits = replace(MODEL_LIMITS[("openai", "gpt-4.1-mini")], max_tickets=20)
        policy = patch.dict("evaluation.batching.MODEL_LIMITS", {("openai", "gpt-4.1-mini"): self.limits})
        policy.start()
        self.addCleanup(policy.stop)
        self.items = [{"id": "0", "text": "hello"}, {"id": "1", "text": "bye"}]
        self.rows = [{"id": "1", "category": "ORDER", "confidence": .8},
                     {"id": "0", "category": "ACCOUNT", "confidence": .9}]
    def test_id_mapping_and_invalid_results(self):
        self.assertEqual(parse_results({"results": self.rows}, self.items, ["ORDER","ACCOUNT"]),
                         [("ACCOUNT", .9), ("ORDER", .8)])
        for rows in [self.rows[:1], self.rows+self.rows[:1],
                     [dict(self.rows[0], id="unknown"), self.rows[1]],
                     [dict(self.rows[0], confidence=float("nan")), self.rows[1]],
                     [dict(self.rows[0], confidence=True), self.rows[1]]]:
            with self.assertRaises(LLMError):
                parse_results({"results": rows}, self.items, ["ORDER","ACCOUNT"])
    def test_packing_no_labels_and_boundaries(self):
        tickets = [{"text":"hi", "expected":"SECRET"} for _ in range(45)]
        batches = list(pack(tickets, "prompt", self.limits))
        self.assertEqual([len(b) for b in batches], [20,20,5])
        self.assertNotIn("SECRET", json.dumps(batches))
        self.assertEqual(len(list(pack(tickets[:3], "", replace(self.limits, output_tokens=256)))), 3)
        with self.assertRaises(ValueError):
            list(pack([{"text":"x"*20000}], "", self.limits))
    def test_both_provider_envelopes_and_truncation(self):
        for provider, envelope in [
            ("openai", {"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"results":self.rows})}}]}),
            ("gemini", {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps({"results":self.rows})}]}}]})]:
            with self.subTest(provider=provider), patch("evaluation.batching.read_provider_response", return_value=json.dumps(envelope)) as http:
                answers=request_batch(self.items,provider=provider,model="test",api_key="test",
                    prompt="prompt",categories=["ORDER","ACCOUNT"],limits=self.limits,timeout=8,retry_budget=120)
                self.assertEqual(answers[0],("ACCOUNT",.9))
                self.assertEqual(http.call_args.kwargs["retry_budget"],120)
                self.assertIn("tickets", http.call_args.args[0].data.decode())
            if provider=="openai": envelope["choices"][0]["finish_reason"]="length"
            else: envelope["candidates"][0]["finishReason"]="MAX_TOKENS"
            with patch("evaluation.batching.read_provider_response", return_value=json.dumps(envelope)):
                with self.assertRaises(LLMError):
                    request_batch(self.items,provider=provider,model="test",api_key="test",
                        prompt="prompt",categories=["ORDER","ACCOUNT"],limits=self.limits,timeout=8,retry_budget=120)
    def test_loop_pacing_errors_and_preflight(self):
        method={"provider":"openai","prompt_version":"V1"}
        env={"OPENAI_API_KEY":"test"}
        tickets=[{"text":"hello"} for _ in range(21)]
        with patch("evaluation.batching.request_batch",side_effect=[LLMError("failed"),[("ORDER",.8)]]) as http:
            waits=[]
            rows=run(tickets,method,env,waits.append)
            self.assertEqual(len(rows),21)
            self.assertEqual(sum(bool(r[3]) for r in rows),20)
            self.assertEqual(waits,[6])
            self.assertEqual(http.call_count,2)
        with patch("evaluation.batching.request_batch") as http:
            for invalid in [tickets+[{"text":"x"*20000}]]:
                with self.assertRaises(ValueError): run(invalid,method,env,lambda _:None)
            with self.assertRaises(ValueError): run(tickets,dict(method,prompt_version="V2"),env,lambda _:None)
            with self.assertRaises(ValueError): run(tickets,method,dict(env,OPENAI_MODEL="unknown"),lambda _:None)
            http.assert_not_called()
    def test_separate_result_paths(self):
        from evaluation.evaluate import results_path
        self.assertNotEqual(results_path("openai-v1","smoke"),results_path("openai-v1","smoke",batch=True))
        self.assertEqual(results_path("baseline","smoke"),results_path("baseline","smoke",batch=True))

    def test_progress_counts_actual_attempts_including_retries(self):
        states = []
        def fake_response(request, *, opener, **kwargs):
            body = json.loads(request.data)
            tickets = json.loads(body["messages"][1]["content"])["tickets"]
            opener(request)
            opener(request)  # simulate a retry performed by the shared helper
            rows = [{"id": item["id"], "category": "ORDER", "confidence": .9} for item in tickets]
            return json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"results":rows})}}]})
        with patch("evaluation.batching.read_provider_response", side_effect=fake_response), patch("evaluation.batching.urlopen"):
            result = run([{"text":"order"} for _ in range(21)],
                {"provider":"openai","prompt_version":"V1"},
                {"OPENAI_API_KEY":"test"}, lambda _: None, progress=states.append)
        self.assertEqual(len(result),21)
        self.assertEqual(states[0]["completed"],0)
        self.assertEqual(states[-1], {"completed":21,"total":21,"batches":2,"requests":4,"retries":2,"errors":0,"metadata_requests":0,"limits_source":"configured model limits"})

    def test_automatic_size_can_exceed_twenty(self):
        limits = replace(self.limits, max_tickets=None)
        batches = list(pack([{"text":"hi"} for _ in range(45)], "prompt", limits))
        self.assertEqual(len(batches),1)

    def test_live_metadata_and_fallback(self):
        import io
        from evaluation.provider_limits import model_limits
        payload = json.dumps({"inputTokenLimit":8000,"outputTokenLimit":1000}).encode()
        with patch("evaluation.provider_limits.urlopen", return_value=io.BytesIO(payload)):
            limits,source,count = model_limits("gemini","test","secret",self.limits)
        self.assertEqual(limits.input_budget,8000)
        self.assertEqual(limits.output_tokens,1000)
        self.assertEqual(count,1)
        self.assertIn("live",source)
        with patch("evaluation.provider_limits.urlopen",side_effect=OSError("offline")):
            limits,source,count = model_limits("gemini","test","secret",self.limits)
        self.assertEqual(limits,self.limits)
        self.assertIn("fallback",source)

    def test_rate_headers_wait_only_when_capacity_insufficient(self):
        from evaluation.provider_limits import RateWindow,duration
        self.assertEqual(duration("1m2.5s"),62.5)
        self.assertEqual(duration("250ms"),.25)
        self.assertIsNone(duration("not a duration"))
        state = RateWindow()
        with patch("evaluation.provider_limits.monotonic",return_value=100):
            state.observe({"x-ratelimit-remaining-tokens":"10","x-ratelimit-reset-tokens":"20s"})
        with patch("evaluation.provider_limits.monotonic",return_value=105):
            self.assertEqual(state.wait_for(100),15.25)
            self.assertEqual(state.wait_for(5),0)
        state.observe({})
        self.assertEqual(state.wait_for(100),0)

    def test_transport_errors_are_distinguished(self):
        for error, message in [(TimeoutError(), "timed out"), (OSError(), "connection failed"),
                               (ValueError(), "decoded")]:
            with patch("evaluation.batching.read_provider_response",side_effect=error):
                with self.assertRaisesRegex(LLMError,message):
                    request_batch(self.items,provider="openai",model="test",api_key="test",
                        prompt="p",categories=["ORDER"],limits=self.limits,timeout=60,retry_budget=300)
