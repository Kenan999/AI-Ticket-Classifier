"""Focused tests for the intentionally simple baseline adapter."""

import unittest

from backend.classifier import MODEL_VERSION, predict_ticket, suggest_customer_reply


class BaselineClassifierTests(unittest.TestCase):
    def test_english_and_german_examples(self):
        self.assertEqual(predict_ticket("My item was damaged").category, "Returns")
        self.assertEqual(predict_ticket("Meine Rechnung ist falsch").category, "Billing")
        self.assertEqual(predict_ticket("I forgot my password").category, "Account")

    def test_unknown_and_ambiguous_inputs_are_low_confidence(self):
        self.assertLess(predict_ticket("Hello, I have a question").confidence, 0.75)
        self.assertLess(
            predict_ticket("A refund and a password reset").confidence, 0.75
        )

    def test_model_version_and_score_bounds(self):
        for text in ("The package is late", "Where is my order?", "Hello"):
            prediction = predict_ticket(text)
            self.assertEqual(prediction.model_version, MODEL_VERSION)
            self.assertGreaterEqual(prediction.confidence, 0.0)
            self.assertLessEqual(prediction.confidence, 1.0)
            self.assertTrue(suggest_customer_reply(prediction.category))

    def test_invalid_direct_input(self):
        with self.assertRaises(ValueError):
            predict_ticket(" ")


if __name__ == "__main__":
    unittest.main()
