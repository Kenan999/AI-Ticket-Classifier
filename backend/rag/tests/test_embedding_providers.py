"""Offline checks for the shared RAG embedding interface."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.rag import embeddings, retriever


class EmbeddingProviderTests(unittest.TestCase):
    def test_adapters(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return b''
        for provider in ('gemini', 'openai', 'local'):
            with self.subTest(provider=provider):
                result = {'embedding': {'values': [0.1, 0.2]}} if provider == 'gemini' else {'data': [{'embedding': [0.1, 0.2]}]}
                with patch.dict('os.environ', {'GEMINI_API_KEY':'test','OPENAI_API_KEY':'test'}, clear=False), patch.object(embeddings, 'urlopen') as call:
                    response = call.return_value.__enter__.return_value
                    response.__iter__.return_value = iter([json.dumps(result).encode()])
                    with patch.object(embeddings.json, 'load', return_value=result):
                        self.assertEqual(embeddings.embed('policy', 'RETRIEVAL_DOCUMENT', provider), [0.1, 0.2])
                    self.assertTrue(call.called)

    def test_provider_indexes_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(retriever, 'ROOT', root), patch.object(retriever, 'INDEX', root/'rag_vectors.sqlite3'):
                self.assertNotEqual(retriever.index_path('openai'), retriever.index_path('local'))
                self.assertNotEqual(retriever.index_path('gemini'), retriever.index_path('openai'))
                with patch.object(retriever, 'KNOWLEDGE', Path(__file__).resolve().parents[1]/'knowledge'), patch.object(retriever, 'embed', return_value=[1.,0.]):
                    self.assertGreater(retriever.index_documents('local'), 0)
                    self.assertGreater(retriever.index_documents('openai'), 0)
                    self.assertEqual(retriever.retrieve('shipping?', provider='local')[0]['score'], 1.0)
                with sqlite3.connect(retriever.index_path('local')) as db:
                    self.assertEqual({row[0] for row in db.execute('select distinct model from documents')}, {embeddings.LOCAL_MODEL})

    def test_invalid_provider(self):
        with self.assertRaises(ValueError): retriever.index_path('unknown')
