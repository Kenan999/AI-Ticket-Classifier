"""Isolated API regression tests; never write to the live review CSV."""

import csv
from pathlib import Path
import tempfile
import unittest

from backend.app import create_app


class TicketApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.review_csv = Path(self.temp_dir.name) / "reviews.csv"
        self.app = create_app(review_path=self.review_csv)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def classify(self, text):
        response = self.client.post("/classify", json={"text": text})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_frontend_contract_for_clear_ticket(self):
        result = self.classify("My order arrived damaged.")
        self.assertTrue(result["ticket_id"].startswith("T-"))
        self.assertEqual(result["text"], "My order arrived damaged.")
        self.assertEqual(result["category"], "Returns")
        self.assertEqual(result["status"], "classified")
        self.assertGreaterEqual(result["confidence"], 0.75)
        self.assertLessEqual(result["confidence"], 1.0)
        self.assertTrue(result["customer_reply"])
        self.assertFalse(result["review_required"])
        self.assertFalse(result["reply_confirmed"])
        self.assertTrue(result["model_version"])
        self.assertFalse(self.review_csv.exists())

    def test_unsure_case_waits_for_review(self):
        result = self.classify("Could you please help?")
        self.assertEqual(result["category"], "General")
        self.assertEqual(result["status"], "human_review")
        self.assertTrue(result["review_required"])
        self.assertFalse(result["reply_confirmed"])
        fetched = self.client.get("/case/" + result["ticket_id"]).get_json()
        self.assertEqual(fetched["status"], "human_review")

    def test_conflicting_evidence_waits_for_review(self):
        result = self.classify("My password and payment are both not working.")
        self.assertEqual(result["status"], "human_review")

    def test_approve_is_explicit_and_recorded(self):
        result = self.classify("My package is missing.")
        response = self.client.post("/review", json={
            "ticket_id": result["ticket_id"],
            "decision": "approve",
            "reviewer": "Kenan",
            "comment": "Reviewed the ticket",
        })
        self.assertEqual(response.status_code, 200)
        reviewed = response.get_json()
        self.assertTrue(reviewed["reply_confirmed"])
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertEqual(reviewed["final_category"], result["category"])
        fetched = self.client.get("/case/" + result["ticket_id"]).get_json()
        self.assertEqual(fetched["status"], "reviewed")
        self.assertTrue(fetched["reply_confirmed"])
        with self.review_csv.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_id"], result["ticket_id"])
        self.assertEqual(rows[0]["decision"], "approve")
        self.assertEqual(rows[0]["model_version"], result["model_version"])

    def test_uncertain_case_can_be_corrected(self):
        result = self.classify("I need help with something.")
        response = self.client.post("/review", json={
            "ticket_id": result["ticket_id"],
            "decision": "correct",
            "reviewer": "Kristina",
            "final_category": "Technical",
            "customer_reply": "A support agent will review the technical problem.",
            "comment": "Human classification",
        })
        self.assertEqual(response.status_code, 200)
        reviewed = response.get_json()
        self.assertEqual(reviewed["final_category"], "Technical")
        self.assertEqual(reviewed["predicted_category"], "General")
        self.assertEqual(reviewed["decision"], "correct")
        self.assertTrue(reviewed["reply_confirmed"])
        with self.review_csv.open(newline="", encoding="utf-8") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["predicted_label"], "General")
        self.assertEqual(row["final_label"], "Technical")

    def test_correction_requires_human_reply(self):
        result = self.classify("An unclear issue")
        response = self.client.post("/review", json={
            "ticket_id": result["ticket_id"],
            "decision": "correct",
            "reviewer": "Kenan",
            "final_category": "Orders",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.review_csv.exists())
        case = self.client.get("/case/" + result["ticket_id"]).get_json()
        self.assertFalse(case["reply_confirmed"])

    def test_cannot_silently_change_label_when_approving(self):
        result = self.classify("My item is damaged")
        response = self.client.post("/review", json={
            "ticket_id": result["ticket_id"],
            "decision": "approve",
            "reviewer": "Kenan",
            "final_category": "Account",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.review_csv.exists())

    def test_duplicate_review_is_rejected(self):
        result = self.classify("My item is damaged")
        data = {
            "ticket_id": result["ticket_id"], "decision": "approve",
            "reviewer": "Kenan",
        }
        self.assertEqual(self.client.post("/review", json=data).status_code, 200)
        self.assertEqual(self.client.post("/review", json=data).status_code, 409)
        with self.review_csv.open(newline="", encoding="utf-8") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_unknown_case_cannot_be_reviewed(self):
        response = self.client.post("/review", json={
            "ticket_id": "T-MISSING", "decision": "approve", "reviewer": "Kenan",
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.review_csv.exists())

    def test_invalid_classify_payloads(self):
        cases = [
            {"text": ""},
            {"text": "  "},
            {"text": 12},
            {"other": "field"},
            {"text": "x" * 4001},
            [],
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:40]):
                response = self.client.post("/classify", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
        self.assertEqual(
            self.client.post("/classify", data="not json").status_code, 400
        )

    def test_local_frontend_cors_only(self):
        response = self.client.options(
            "/classify", headers={"Origin": "http://localhost:8000"}
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://localhost:8000",
        )
        response = self.client.options(
            "/classify", headers={"Origin": "https://untrusted.example"}
        )
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_case_survives_app_restart(self):
        created = self.classify("My package is missing.")
        restarted = create_app(review_path=self.review_csv)
        restarted.config["TESTING"] = True
        response = restarted.test_client().get("/case/" + created["ticket_id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["category"], created["category"])

    def test_cases_list_is_persisted_and_newest_first(self):
        first = self.classify("My package is missing.")
        second = self.classify("I forgot my password.")
        response = self.client.get("/cases")
        self.assertEqual(response.status_code, 200)
        cases = response.get_json()
        self.assertEqual([row["ticket_id"] for row in cases],
                         [second["ticket_id"], first["ticket_id"]])
        self.assertTrue(all({"ticket_id", "text", "category", "confidence",
                             "status", "review_required", "reply_confirmed"}
                            <= row.keys() for row in cases))
        restarted = create_app(review_path=self.review_csv)
        persisted = restarted.test_client().get("/cases").get_json()
        self.assertEqual([row["ticket_id"] for row in persisted],
                         [second["ticket_id"], first["ticket_id"]])

    def test_cases_list_reflects_review_correction(self):
        created = self.classify("Something is odd, I need help.")
        self.assertEqual(created["status"], "human_review")
        response = self.client.post("/review", json={
            "ticket_id": created["ticket_id"],
            "decision": "correct",
            "reviewer": "Kenan",
            "final_category": "Account",
            "customer_reply": "We will check your account.",
        })
        self.assertEqual(response.status_code, 200)
        listed = self.client.get("/cases").get_json()[0]
        self.assertEqual(listed["category"], "Account")
        self.assertEqual(listed["status"], "reviewed")
        self.assertTrue(listed["reply_confirmed"])
        restarted = create_app(review_path=self.review_csv)
        self.assertEqual(restarted.test_client().get("/cases").get_json()[0]["category"],
                         "Account")

    def test_cases_list_starts_empty(self):
        self.assertEqual(self.client.get("/cases").get_json(), [])

    def test_review_survives_app_restart(self):
        created = self.classify("My package is missing.")
        response = self.client.post("/review", json={
            "ticket_id": created["ticket_id"], "decision": "approve", "reviewer": "Kenan"
        })
        self.assertEqual(response.status_code, 200)
        restarted = create_app(review_path=self.review_csv)
        restarted.config["TESTING"] = True
        response = restarted.test_client().get("/case/" + created["ticket_id"])
        self.assertTrue(response.get_json()["reply_confirmed"])
        self.assertEqual(response.get_json()["status"], "reviewed")

    def test_dataset_label_adapter_preserves_ui_category(self):
        created = self.classify("I forgot my password")
        self.assertEqual(created["category"], "Account")
        self.assertEqual(created["dataset_label"], "ACCOUNT")
        ambiguous = self.classify("There is an error")
        self.assertEqual(ambiguous["category"], "Technical")
        self.assertIsNone(ambiguous["dataset_label"])

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
