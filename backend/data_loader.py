"""Read ticket data from a CSV file and return it with unified fields.

The loader works with two kinds of files:

* the raw Bitext file in ``data/raw/`` (never modified, only read);
* the split files in ``data/processed/`` (``train.csv``, ``validation.csv``,
  ``test.csv``), which already have the project columns.

Every result has the same three fields:

Raw column  -> Project column
-----------------------------
(row number) -> ticket_id   e.g. "BT-00001" (the raw file has no ID of its own)
instruction  -> text        the customer message
category     -> label       one of 11 ticket categories

All other raw columns (``intent``, ``response``, ``flags``) are not needed for
classification and are not returned.

Because ``ticket_id`` is the row number of the original file, any ticket can
always be traced back to its row in the raw data.

The raw file is not stored in Git (see ``download_data.py`` for why). Download
it with ``python backend/download_data.py``, as described in
``backend/README.md`` ("Data" section). It is saved to ``data/raw/``.
"""

from pathlib import Path

import pandas as pd

# Paths are built from this file's location, so the script works from any folder.
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_FILE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)

COLUMNS = ["ticket_id", "text", "label"]


def load_dataset(path=RAW_FILE):
    """Return the tickets of a CSV file as a DataFrame with the columns in ``COLUMNS``.

    Args:
        path: Location of a CSV file. Defaults to the raw file in ``data/raw/``.
            Either the raw Bitext file or a split file from ``data/processed/``.

    Returns:
        A DataFrame with one row per ticket, in the same order as the file.

    Raises:
        FileNotFoundError: If the CSV does not exist (for the raw file: it has
            not been downloaded yet).
        ValueError: If the file does not have the expected columns.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Data file not found: {path}\n"
            "The raw file is downloaded with: python backend/download_data.py "
            "(see backend/README.md, Data section)."
        )

    data = pd.read_csv(path)

    if {"instruction", "category"}.issubset(data.columns):
        # Raw Bitext file: rename the columns and create the ticket_id.
        data = pd.DataFrame(
            {
                "ticket_id": [f"BT-{i:05d}" for i in range(1, len(data) + 1)],
                "text": data["instruction"],
                "label": data["category"],
            }
        )

    missing = [column for column in COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"{path} is missing the columns: {missing}")

    return data[COLUMNS]


if __name__ == "__main__":
    tickets = load_dataset()
    print(tickets.shape)
    print(tickets.head())
    print(tickets["label"].nunique(), "labels")
