"""Provider selection contract, with temporary storage and no network calls."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import create_app
from backend.keyword_classifier import CATEGORY_GUIDANCE, DATASET_CATEGORIES, PredictionResult
from backend.llms.gemini import LLMError
from backend.evaluation import evaluate


class ProviderSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {
            'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'openai-test-secret',
            'GEMINI_API_KEY': 'gemini-test-secret', 'OPENAI_MODEL': 'gpt-4.1-mini',
            'GEMINI_MODEL': 'gemini-3.1-flash-lite', 'LLM_CATEGORIES': '',
            'LLM_TIMEOUT_SECONDS': '8',
        })
        env.start(); self.addCleanup(env.stop)
        self.app = create_app(review_path=Path(temp.name) / 'reviews.csv')
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.openai_patch = patch('backend.app.classify_with_openai', return_value=
                                 PredictionResult('DELIVERY', .9, 'openai:gpt-4.1-mini'))
        self.gemini_patch = patch('backend.app.classify_with_gemini', return_value=
                                 PredictionResult('DELIVERY', .9, 'gemini:gemini-3.1-flash-lite'))
        self.openai = self.openai_patch.start(); self.addCleanup(self.openai_patch.stop)
        self.gemini = self.gemini_patch.start(); self.addCleanup(self.gemini_patch.stop)

    def send(self, **values):
        return self.client.post('/classify', json={'text': 'My package has not arrived.', **values})

    def test_provider_list_is_safe_and_does_not_call_cloud(self):
        response = self.client.get('/providers', headers={'Origin': 'http://localhost:8000'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            'default_provider': 'openai',
            'providers': [
                {'id': 'baseline', 'label': 'Local rules', 'configured': True},
                {'id': 'openai', 'label': 'OpenAI', 'configured': True},
                {'id': 'gemini', 'label': 'Gemini', 'configured': True},
            ],
        })
        self.assertNotIn('test-secret', response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://localhost:8000')
        self.openai.assert_not_called(); self.gemini.assert_not_called()
        with patch.dict(os.environ, {'OPENAI_API_KEY': ' ', 'GEMINI_API_KEY': ''}):
            entries = self.client.get('/providers').json['providers']
            self.assertEqual([p['configured'] for p in entries], [True, False, False])

    def test_each_selection_routes_and_persists_without_changing_default(self):
        for provider in ('gemini', 'baseline', 'openai'):
            with self.subTest(provider=provider):
                self.openai.reset_mock(); self.gemini.reset_mock()
                response = self.send(provider=provider)
                self.assertEqual(response.status_code, 200)
                result = response.json
                self.assertEqual(result['provider'], provider)
                self.assertEqual(result['requested_provider'], provider)
                self.assertFalse(result['fallback_used'])
                self.assertEqual(self.openai.call_count, int(provider == 'openai'))
                self.assertEqual(self.gemini.call_count, int(provider == 'gemini'))
                self.assertEqual(self.client.get('/case/'+result['ticket_id']).json, result)
                self.assertEqual(os.environ['LLM_PROVIDER'], 'openai')
                self.assertEqual(self.client.get('/providers').json['default_provider'], 'openai')
        restarted = create_app(review_path=self.app.config['REVIEW_PATH'])
        self.assertEqual(len(restarted.test_client().get('/cases').json), 3)

    def test_invalid_provider_neither_calls_cloud_nor_saves_case(self):
        for value in (None, [], {}, True, 1, '', 'unknown', 'OpenAI', ' openai '):
            with self.subTest(value=value):
                response = self.send(provider=value)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['error']['code'], 'invalid_provider')
        self.openai.assert_not_called(); self.gemini.assert_not_called()
        self.assertEqual(self.client.get('/cases').json, [])

    def test_explicit_missing_key_returns_error_without_saving_or_fallback(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': '', 'GEMINI_API_KEY': ' '}):
            for provider in ('openai', 'gemini'):
                response = self.send(provider=provider)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json['error']['code'], 'provider_not_configured')
        self.openai.assert_not_called(); self.gemini.assert_not_called()
        self.assertEqual(self.client.get('/cases').json, [])

    def test_explicit_provider_failure_is_safe_and_does_not_save(self):
        for provider, adapter in [('openai', self.openai), ('gemini', self.gemini)]:
            with self.subTest(provider=provider):
                adapter.side_effect = LLMError('private provider body and test-secret')
                with self.assertLogs(self.app.logger, level='WARNING') as logs:
                    response = self.send(provider=provider)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json['error']['code'], 'provider_unavailable')
                self.assertNotIn('test-secret', response.get_data(as_text=True)+' '.join(logs.output))
        self.assertEqual(self.client.get('/cases').json, [])

    def test_omitting_provider_uses_default_and_retains_visible_fallback(self):
        response = self.send()
        self.assertEqual(response.json['provider'], 'openai')
        self.openai.assert_called_once()
        self.openai.side_effect = LLMError('offline')
        with self.assertLogs(self.app.logger, level='WARNING'):
            result = self.send().json
        self.assertEqual(result['requested_provider'], 'openai')
        self.assertEqual(result['provider'], 'baseline')
        self.assertTrue(result['fallback_used'])
        self.assertEqual(self.client.get('/case/'+result['ticket_id']).json, result)

    def test_second_client_keeps_its_default_after_first_client_selects(self):
        self.send(provider='gemini')
        result = self.app.test_client().post('/classify', json={'text': 'Where is my parcel?'}).json
        self.assertEqual(result['provider'], 'openai')

    def test_client_cannot_override_server_configuration(self):
        for field in ('model', 'api_key', 'OPENAI_MODEL', 'GEMINI_MODEL',
                      'OPENAI_API_KEY', 'GEMINI_API_KEY', 'timeout',
                      'categories', 'prompt', 'settings'):
            with self.subTest(field=field):
                response = self.send(provider='openai', **{field: 'client-value'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['error']['code'], 'unsupported_fields')
                self.assertNotIn('client-value', response.get_data(as_text=True))
        self.openai.assert_not_called(); self.gemini.assert_not_called()
        self.assertEqual(self.client.get('/cases').json, [])

    def test_cloud_adapters_receive_only_server_settings(self):
        for provider, adapter, key_name, model_name in (
            ('openai', self.openai, 'OPENAI_API_KEY', 'OPENAI_MODEL'),
            ('gemini', self.gemini, 'GEMINI_API_KEY', 'GEMINI_MODEL'),
        ):
            with self.subTest(provider=provider), patch.dict(os.environ, {
                key_name: 'server-secret', model_name: 'server-model',
                'LLM_TIMEOUT_SECONDS': '12',
                'LLM_CATEGORIES': ','.join(reversed(DATASET_CATEGORIES)),
            }):
                response = self.send(provider=provider)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(adapter.call_args.kwargs, {
                    'api_key': 'server-secret', 'model': 'server-model',
                    'timeout': 12.0, 'categories': DATASET_CATEGORIES,
                })
                self.assertNotIn('server-secret', response.get_data(as_text=True))

    def test_invalid_server_default_matches_baseline_behavior(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'unknown'}):
            self.assertEqual(self.client.get('/providers').json['default_provider'], 'baseline')
            self.assertEqual(self.send().json['provider'], 'baseline')
        self.openai.assert_not_called(); self.gemini.assert_not_called()


class VersionedEvaluationTests(unittest.TestCase):
    def test_every_provider_and_version_uses_the_nine_label_prompt(self):
        category = "DELIVERY"
        response = json.dumps({"category": category, "confidence": 0.91})
        ticket = {"ticket_id": "fixture", "text": "Where is my parcel?", "expected": category}
        providers = {
            "gemini": (
                "backend.llms.gemini.urlopen",
                {"candidates": [{"content": {"parts": [{"text": response}]}}]},
            ),
            "openai": (
                "backend.llms.openai.urlopen",
                {"choices": [{"message": {"content": response}}]},
            ),
        }
        for provider, (urlopen, payload) in providers.items():
            for version in ("V1", "V2", "V3"):
                with self.subTest(provider=provider, version=version):
                    with patch.object(
                        evaluate, "load_env", return_value={f"{provider.upper()}_API_KEY": "test"},
                    ), patch(urlopen, return_value=io.BytesIO(json.dumps(payload).encode())) as send:
                        rows = evaluate.run_evaluation([ticket], provider=f"{provider}-{version.lower()}")

                    if version in ("V2", "V3"):
                        send.assert_not_called()
                        self.assertIn("not configured", rows[0]["error"])
                        self.assertFalse(rows[0]["correct"])
                        continue
                    send.assert_called_once()
                    request = json.loads(send.call_args.args[0].data)
                    if provider == "gemini":
                        instructions = request["systemInstruction"]["parts"][0]["text"]
                    else:
                        instructions = request["messages"][0]["content"]
                    self.assertIn(json.dumps(DATASET_CATEGORIES), instructions)
                    self.assertEqual(instructions.count(CATEGORY_GUIDANCE), 1)
                    self.assertEqual(rows[0]["prompt_version"], version)
                    self.assertEqual(rows[0]["predicted"], category)
                    self.assertTrue(rows[0]["correct"])


if __name__ == '__main__':
    unittest.main()
