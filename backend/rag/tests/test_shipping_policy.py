import json
import unittest
from pathlib import Path
from backend.rag.chat_context import policy_context

ROOT = Path(__file__).resolve().parents[1]

class ShippingPolicyTests(unittest.TestCase):
    def test_policy_documents(self):
        self.assertEqual(len(list((ROOT/'knowledge'/'shipping').glob('*.md'))), 7)
    def test_question_bank(self):
        questions=json.loads((ROOT/'tests'/'shipping-policy-questions.json').read_text())
        self.assertGreaterEqual(len(questions), 100)
        for item in questions:
            self.assertIn(item['expected_policy_id'], {'SHIP-%02d'%i for i in range(1,8)})
    def test_unrelated_message_skips_retrieval(self):
        self.assertEqual(policy_context('Hello, how are you?'), {'context':'', 'sources':[]})

if __name__=='__main__': unittest.main()
