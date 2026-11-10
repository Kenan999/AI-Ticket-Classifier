"""Download the raw Bitext dataset into ``data/raw/``.

The dataset is not stored in Git. Its licence (CDLA-Sharing-1.0) allows
redistribution, but only with conditions (attribution, licence text, no extra
restrictions). Keeping the CSV out of the repository avoids those obligations
and keeps the repo small, so every team member runs this script once after
cloning:

    python backend/download_data.py

What it does:
1. Downloads one fixed version (a pinned Hugging Face commit) of the CSV.
2. Checks the SHA-256 checksum, so everyone has an identical file.
3. Saves it to ``data/raw/``. If a correct file is already there, it does nothing.

It uses the standard library plus ``certifi`` (in requirements.txt), which gives
Python up-to-date HTTPS certificates. Without it, Python from python.org on macOS
often fails with "CERTIFICATE_VERIFY_FAILED".

Dataset: Bitext Customer Support LLM Chatbot Training Dataset (Bitext)
Source:  https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset
Licence: CDLA-Sharing-1.0 (https://cdla.dev/sharing-1-0/)
"""

import hashlib
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST_DIR = REPO_ROOT / "data" / "raw"

FILE_NAME = "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
COMMIT = "430d1a89bd93bd1fa23c16f29dd53e73f0087443"
URL = (
    "https://huggingface.co/datasets/bitext/"
    f"Bitext-customer-support-llm-chatbot-training-dataset/resolve/{COMMIT}/{FILE_NAME}"
)
SHA256 = "6f81102b0100b97b8468eb04368033a23206bf1fde9d53500d5806ec1001a434"


def sha256_of(path):
    """Return the SHA-256 checksum of a file as a hex string."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(dest_dir=DEFAULT_DEST_DIR):
    """Download the CSV into ``dest_dir`` and verify its checksum.

    Returns:
        The path of the verified file.

    Raises:
        ValueError: If the downloaded file does not match the expected checksum.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / FILE_NAME

    if target.exists() and sha256_of(target) == SHA256:
        print(f"Already downloaded and verified: {target}")
        return target

    print(f"Downloading {FILE_NAME} ...")
    partial = target.with_suffix(".part")
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(URL, context=context) as response, open(
        partial, "wb"
    ) as out:
        shutil.copyfileobj(response, out)

    if sha256_of(partial) != SHA256:
        partial.unlink()
        raise ValueError(
            "Checksum mismatch: the downloaded file is not the expected version. "
            "It was deleted."
        )

    partial.replace(target)
    print(f"Saved and verified: {target}")
    return target


if __name__ == "__main__":
    # Optional: python backend/download_data.py <other folder>
    download(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DEST_DIR)
