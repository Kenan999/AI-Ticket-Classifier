import unittest
from backend.rag.chat_category import customer_issue, detect_chat_category


class ChatCategoryTests(unittest.TestCase):
    def test_customer_only(self):
        self.assertEqual(customer_issue([{'sender':'customer','content':'Charged twice for my order'}, {'sender':'ai','content':'REFUND'}]), 'Charged twice for my order')

    def test_classifies_from_retrieval_and_llm(self):
        result = detect_chat_category([{'sender':'customer','content':'My card was charged twice'}],
            retriever=lambda issue, limit: [{'id':'BT-1','category':'PAYMENT','text':'Duplicate charge'}],
            classifier=lambda issue, examples: {'category':'PAYMENT','confidence':0.93})
        self.assertEqual(result['category'], 'PAYMENT')

    def test_uncertain_is_hidden(self):
        result = detect_chat_category([{'sender':'customer','content':'I have an issue with my order'}],
            retriever=lambda issue, limit: [{'id':'BT-1','category':'ORDER'}],
            classifier=lambda issue, examples: {'category':'ORDER','confidence':0.4})
        self.assertIsNone(result['category'])

    def test_no_message_no_model_call(self):
        result = detect_chat_category([], retriever=lambda *a, **k: self.fail(), classifier=lambda *a: self.fail())
        self.assertEqual(result['status'], 'insufficient_context')


if __name__ == '__main__': unittest.main()
