"""Real localhost HTTP smoke test without writing into the live review file."""

import csv
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent.parent


def request_json(base_url, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 200
        return json.load(response)


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    with tempfile.TemporaryDirectory() as temp:
        review_csv = Path(temp) / "reviews.csv"
        env = os.environ.copy()
        env["BACKEND_PORT"] = str(port)
        env["REVIEW_CSV_PATH"] = str(review_csv)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "backend" / "app.py")],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = "http://127.0.0.1:{}".format(port)
        try:
            for attempt in range(50):
                if process.poll() is not None:
                    raise RuntimeError("Backend server exited before becoming ready")
                try:
                    if request_json(base_url, "/health")["status"] == "ok":
                        break
                except (OSError, ValueError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Backend server did not start")

            classified = request_json(
                base_url, "/classify", {"text": "My order arrived damaged."}
            )
            assert classified["category"] == "Returns"
            assert classified["status"] == "classified"
            assert 0 <= classified["confidence"] <= 1
            assert classified["reply_confirmed"] is False

            uncertain = request_json(
                base_url, "/classify", {"text": "I need help with something"}
            )
            assert uncertain["status"] == "human_review"
            assert uncertain["review_required"] is True
            assert uncertain["reply_confirmed"] is False

            reviewed = request_json(base_url, "/review", {
                "ticket_id": uncertain["ticket_id"],
                "decision": "correct",
                "reviewer": "HTTP test",
                "final_category": "Technical",
                "customer_reply": "A support agent will investigate.",
            })
            assert reviewed["status"] == "reviewed"
            assert reviewed["final_category"] == "Technical"
            assert reviewed["reply_confirmed"] is True
            case = request_json(base_url, "/case/" + uncertain["ticket_id"])
            assert case["reply_confirmed"] is True

            try:
                request_json(base_url, "/classify", {"text": ""})
                raise AssertionError("Invalid text was accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                assert "error" in json.loads(exc.read().decode("utf-8"))

            with review_csv.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 1
            assert rows[0]["final_label"] == "Technical"
            print("HTTP smoke test OK: /health, /classify, /review, /case, validation and CSV")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
