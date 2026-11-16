"""Manual nine-category smoke check, not a measure of real-world accuracy.

Preview fictional tickets without making API calls:
    python -m backend.check_openai_categories

Run nine real OpenAI requests with credentials supplied by the process environment:
    python -m backend.check_openai_categories --live

No environment files are read. Cases use temporary storage deleted after the run.
The Flask test client exercises the backend route, not browser/network deployment.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from .config import openai_api_key
from .llm_classifier import configured_categories
from .openai_classifier import DEFAULT_OPENAI_MODEL


# Fixed expected labels: never derive the answers from the model's predictions.
EXAMPLES = (
    ("ACCOUNT", "I forgot my account password and cannot reset it."),
    ("ORDER", "Can I change the quantity in the order I placed yesterday?"),
    ("INVOICE", "Please send me a copy of the tax invoice for my purchase."),
    ("CONTACT", "How can I contact a human customer support agent by phone?"),
    ("PAYMENT", "My credit card was charged twice for one purchase."),
    ("FEEDBACK", "I would like to give feedback about your excellent service."),
    ("REFUND", "The item arrived defective, and I would like a refund."),
    ("DELIVERY", "My parcel has not arrived and delivery tracking has not updated."),
    ("SHIPPING", "How much is international shipping, and which shipping methods are available?"),
)


@dataclass(frozen=True)
class CheckResult:
    expected: str
    actual: str
    provider_ok: bool
    saved_ok: bool
    error: str = ""

    @property
    def passed(self):
        return (not self.error and self.expected == self.actual
                and self.provider_ok and self.saved_ok)


@contextmanager
def temporary_environment(values):
    """Restore the caller's settings even when a check raises an exception."""
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check_case(client, expected, text, model):
    response = client.post("/classify", json={"text": text})
    data = response.get_json(silent=True)
    if response.status_code != 200 or not isinstance(data, dict):
        return CheckResult(expected, "No result", False, False, "Classification request failed")
    category = data.get("category")
    # Only display an allowed label, never an arbitrary response or exception body.
    actual = category if category in {label for label, _ in EXAMPLES} else "Invalid category"
    provider_ok = data.get("model_version") == "openai:" + model
    ticket_id = data.get("ticket_id")
    saved_ok = False
    if isinstance(ticket_id, str) and ticket_id.startswith("T-"):
        stored = client.get("/case/" + ticket_id)
        saved_ok = stored.status_code == 200 and stored.get_json(silent=True) == data
    return CheckResult(expected, actual, provider_ok, saved_ok)


def run_checks():
    """Call the actual classification route nine times with isolated storage."""
    if not openai_api_key():
        raise ValueError("Supply OPENAI_API_KEY through the process environment; no key file is read.")
    expected_categories = {label for label, _ in EXAMPLES}
    if set(configured_categories()) != expected_categories:
        raise ValueError("Configured categories must match the nine examples before this check can run.")
    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    with tempfile.TemporaryDirectory(prefix="openai-category-check-") as directory:
        runtime = Path(directory)
        with temporary_environment({
            "LLM_PROVIDER": "openai",
            # Set before import: backend.app creates its default app on import.
            "REVIEW_CSV_PATH": str(runtime / "reviews.csv"),
        }):
            from .app import create_app

            app = create_app(review_path=runtime / "reviews.csv",
                             case_db_path=runtime / "cases.sqlite")
            client = app.test_client()
            return [check_case(client, category, text, model) for category, text in EXAMPLES]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="Make nine real API requests (may incur API charges).")
    args = parser.parse_args(argv)
    if not args.live:
        print("Preview only. No API calls or saved cases.")
        for category, text in EXAMPLES:
            print(f"{category}: {text}")
        print("\nUse --live with deployment-supplied environment settings to run the check.")
        return 0
    try:
        results = run_checks()
    except ValueError:
        print("Cannot run: check the environment key and nine-category configuration.")
        return 2

    print("Expected  | Actual           | OpenAI | Saved | Result")
    print("-" * 61)
    for result in results:
        print(f"{result.expected:<9} | {result.actual:<16} | "
              f"{'yes' if result.provider_ok else 'NO':<6} | "
              f"{'yes' if result.saved_ok else 'NO':<5} | "
              f"{'PASS' if result.passed else 'FAIL'}")
    passed = sum(result.passed for result in results)
    print(f"\n{passed}/{len(results)} passed. Temporary cases removed.")
    print("Nine synthetic examples only; this does not verify frontend or deployment.")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
