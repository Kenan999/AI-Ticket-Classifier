"""Provider selection contract, with temporary storage and no network calls."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import create_app
from backend.classifier import PredictionResult
from backend.llm_classifier import LLMError


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
                                 PredictionResult('Shipping', .9, 'openai:gpt-4.1-mini'))
        self.gemini_patch = patch('backend.app.classify_with_gemini', return_value=
                                 PredictionResult('Shipping', .9, 'gemini:gemini-3.1-flash-lite'))
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

    def test_invalid_server_default_matches_baseline_behavior(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'unknown'}):
            self.assertEqual(self.client.get('/providers').json['default_provider'], 'baseline')
            self.assertEqual(self.send().json['provider'], 'baseline')
        self.openai.assert_not_called(); self.gemini.assert_not_called()


if __name__ == '__main__':
    unittest.main()
