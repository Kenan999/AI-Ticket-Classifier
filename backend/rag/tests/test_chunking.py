import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.rag.chunking import bounded_sections, MAX_INPUT_BYTES
from backend.rag import retriever


class ChunkingTests(unittest.TestCase):
    def test_paragraphs_are_kept_when_possible(self):
        self.assertEqual(list(bounded_sections('One sentence.\n\nAnother sentence.', 50)), ['One sentence.\n\nAnother sentence.'])

    def test_long_sentences_are_bounded(self):
        text = 'A long sentence. ' * 500
        parts = list(bounded_sections(text, 100))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p.encode('utf-8')) <= 100 for p in parts))
        self.assertEqual(' '.join(' '.join(parts).split()), ' '.join(text.split()))

    def test_unicode_word_is_bounded(self):
        parts = list(bounded_sections('😀' * 100, 32))
        self.assertEqual(''.join(parts), '😀' * 100)
        self.assertTrue(all(len(p.encode('utf-8')) <= 32 for p in parts))

    def test_real_policy_chunks(self):
        paths = sorted(retriever.KNOWLEDGE.rglob('*.md'))
        self.assertTrue(paths)
        for path in paths:
            chunks = list(retriever.document_chunks(path))
            self.assertTrue(chunks)
            self.assertEqual(len({c[0] for c in chunks}), len(chunks))
            self.assertTrue(all(len((title + '\n' + content).encode('utf-8')) <= MAX_INPUT_BYTES for _, title, content in chunks))
