"""Focused tests for the deterministic nine-label baseline."""

import unittest

from backend.keyword_classifier import (
    DATASET_CATEGORIES, MODEL_VERSION, dataset_label_for, predict_ticket,
    suggest_customer_reply,
)


class BaselineClassifierTests(unittest.TestCase):
    def test_every_dataset_category_is_produced(self):
        examples = {
            "ACCOUNT": "I forgot my password.",
            "ORDER": "Please cancel my order.",
            "INVOICE": "Please send me an invoice copy.",
            "CONTACT": "Can I contact a human support agent?",
            "PAYMENT": "My credit card was charged twice.",
            "FEEDBACK": "I have feedback and a suggestion.",
            "REFUND": "The item is damaged and I need a refund.",
            "DELIVERY": "My parcel has not arrived and tracking is stuck.",
            "SHIPPING": "What are your international shipping costs?",
        }
        self.assertEqual(tuple(examples), DATASET_CATEGORIES)
        for expected, text in examples.items():
            with self.subTest(expected=expected):
                prediction = predict_ticket(text)
                self.assertEqual(prediction.category, expected)
                self.assertEqual(dataset_label_for(prediction.category), expected)
                self.assertTrue(suggest_customer_reply(expected))

    def test_english_and_german_examples(self):
        self.assertEqual(predict_ticket("My item was damaged").category, "REFUND")
        self.assertEqual(predict_ticket("Meine Rechnung ist falsch").category, "INVOICE")
        self.assertEqual(predict_ticket("I forgot my password").category, "ACCOUNT")

    def test_unknown_and_ambiguous_inputs_require_review(self):
        for text in ("Hello, I have a question", "A support agent and a refund"):
            with self.subTest(text=text):
                result = predict_ticket(text)
                self.assertIn(result.category, DATASET_CATEGORIES)
                self.assertLess(result.confidence, 0.75)
        self.assertEqual(predict_ticket("Hello, I have a question").category, "CONTACT")

    def test_model_version_and_score_bounds(self):
        for text in ("The package is late", "Where is my order?", "Hello"):
            prediction = predict_ticket(text)
            self.assertEqual(prediction.model_version, MODEL_VERSION)
            self.assertGreaterEqual(prediction.confidence, 0.0)
            self.assertLessEqual(prediction.confidence, 1.0)

    def test_order_specific_requests(self):
        for message in (
            "Please cancel my order.", "I want to change my order.",
            "What is my order status?", "I placed an order yesterday.",
            "Ich möchte meine Bestellung stornieren.", "Wie ist mein Bestellstatus?",
        ):
            with self.subTest(message=message):
                result = predict_ticket(message)
                self.assertEqual(result.category, "ORDER")
                self.assertGreaterEqual(result.confidence, 0.75)

    def test_delivery_distinct_from_shipping(self):
        self.assertEqual(
            predict_ticket("Where is my delivery? My order has not arrived.").category,
            "DELIVERY",
        )
        self.assertEqual(
            predict_ticket("What shipping methods can I choose?").category,
            "SHIPPING",
        )

    def test_historical_category_does_not_map_ambiguously(self):
        self.assertIsNone(dataset_label_for("Billing"))
        self.assertIsNone(dataset_label_for("General"))

    def test_invalid_direct_input(self):
        with self.assertRaises(ValueError):
            predict_ticket(" ")


if __name__ == "__main__":
    unittest.main()
