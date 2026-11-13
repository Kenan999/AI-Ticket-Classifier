"""Clean the ticket data and split it into train / validation / test files.

Run from the repository root:

    python backend/preprocessing.py

Steps (each one is a function below):

1. ``load_dataset``     read the raw CSV (ticket_id, text, label)   [data_loader.py]
2. ``check_data``       look at the data, nothing is changed
3. ``drop_labels``      leave out CANCEL and SUBSCRIPTION (9 labels remain)
4. ``remove_templates`` cut the ``{{placeholders}}`` out of the texts
5. ``remove_duplicates`` drop repeated tickets (compared by a simplified text key)
6. ``split_data``       balanced validation and test sets, the rest is train
7. ``check_split``      prove that the three parts are clean and separate
8. ``save_splits``      write data/processed/train.csv, validation.csv, test.csv

The raw file in ``data/raw/`` is never modified. The only change to a ticket text
is that its ``{{placeholders}}`` are cut out (step 4): a placeholder hints at the
label (most ORDER tickets contain one) and real customers never write one.
The simplified key of step 5 is only used to compare tickets.

Why a balanced split: the category sizes of Bitext are an artefact of how the
dataset is built (a category has 1 to 6 intents with about 1,000 tickets each),
not of real customer traffic. A proportional split would let the big categories
dominate the score, so validation and test get the same number of tickets per
label, and train keeps everything that is left.
"""

from pathlib import Path

import pandas as pd

from data_loader import load_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SEED = 42
# Labels that are left out completely (team decision): SUBSCRIPTION is only about
# a newsletter and CANCEL only about cancellation fees, neither is a ticket
# category of the shop.
DROP_LABELS = ("CANCEL", "SUBSCRIPTION")
# Placeholders of the Bitext texts, for example {{Order Number}}.
TEMPLATE_PATTERN = r"\s*\{\{[^}]*\}\}"  # with the space before it
# Tickets per label in validation and in test. Every kept label has more than
# 2 * 200 tickets after cleaning, so train always keeps the rest.
EVAL_PER_LABEL = 200


def make_key(text):
    """Return a simplified copy of the texts, used only to compare tickets.

    Lower case, punctuation replaced by a space (placeholders such as
    ``{{Order Number}}`` are kept) and repeated spaces reduced to one.
    So "Can I pay ?" and "can i pay" get the same key.
    """
    return (
        text.str.lower()
        .str.replace(r"[^\w{}# ]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def check_data(data):
    """Print the state of the data. Nothing is changed. Returns the numbers."""
    key = make_key(data["text"])
    stats = {
        "rows": len(data),
        "labels": data["label"].nunique(),
        "missing_values": int(data.isnull().sum().sum()),
        "exact_repeated_texts": int(data["text"].duplicated().sum()),
        "repeated_by_key": int(key.duplicated().sum()),
        "texts_with_more_than_one_label": int(
            (data.assign(key=key).groupby("key")["label"].nunique() > 1).sum()
        ),
    }
    print("Data check")
    for name, value in stats.items():
        print(f"  {name}: {value}")
    print("  tickets per label:")
    print(data["label"].value_counts().to_string())
    return stats


def remove_duplicates(data):
    """Keep the first ticket of every simplified text, drop the repeats.

    The original wording of the kept tickets stays unchanged.

    Raises:
        ValueError: If one text occurs with different labels. Keeping only the
            first would silently decide the label, so we stop instead.
    """
    key = make_key(data["text"])
    if (data.assign(key=key).groupby("key")["label"].nunique() > 1).any():
        raise ValueError("The same text has different labels, check the data.")
    return data[~key.duplicated()]


def drop_labels(data, labels=DROP_LABELS):
    """Remove all tickets of the given labels. Other tickets stay unchanged."""
    return data[~data["label"].isin(labels)]


def remove_templates(data):
    """Cut the ``{{placeholders}}`` out of the texts.

    "wanna see order {{Order Number}} status" becomes "wanna see order status".
    Texts without a placeholder are not changed.
    """
    return data.assign(
        text=data["text"].str.replace(TEMPLATE_PATTERN, "", regex=True).str.strip()
    )


def split_data(data, per_label=EVAL_PER_LABEL, seed=SEED):
    """Split into train / validation / test with balanced validation and test.

    Every label is shuffled with the fixed seed. The first ``per_label`` tickets
    go to validation, the next ``per_label`` to test and all the others to
    train. The same input and seed always give the same three files.

    Raises:
        ValueError: If a label has too few tickets to fill validation and test.
    """
    parts = {"train": [], "validation": [], "test": []}
    for label, group in data.groupby("label"):
        if len(group) <= 2 * per_label:
            raise ValueError(
                f"Label {label} has only {len(group)} tickets, "
                f"not enough for {per_label} + {per_label} and a train part."
            )
        group = group.sample(frac=1, random_state=seed)
        parts["validation"].append(group.iloc[:per_label])
        parts["test"].append(group.iloc[per_label : 2 * per_label])
        parts["train"].append(group.iloc[2 * per_label :])

    # Sorting by ticket_id keeps every ticket easy to find in the raw data.
    return tuple(
        pd.concat(parts[name]).sort_values("ticket_id")
        for name in ("train", "validation", "test")
    )


def clean_and_split(data, per_label=EVAL_PER_LABEL, seed=SEED):
    """Clean the data and return the (train, validation, test) tables.

    Repeats are removed last, because cutting out the placeholders makes
    different tickets identical (for example "a {{Account Type}} account" and
    "a {{Account Category}} account").
    """
    data = remove_templates(drop_labels(data))
    return split_data(remove_duplicates(data), per_label, seed)


def check_split(train, validation, test, per_label=EVAL_PER_LABEL):
    """Check that the three parts are clean. Raises ValueError if not.

    Returns the numbers that are documented in docs/dataset_comparison.md.
    """
    parts = {"train": train, "validation": validation, "test": test}
    keys = {name: set(make_key(part["text"])) for name, part in parts.items()}
    ids = {name: set(part["ticket_id"]) for name, part in parts.items()}

    results = {}
    for first, second in (("train", "validation"), ("train", "test"), ("validation", "test")):
        results[f"same_ticket_in_{first}_and_{second}"] = len(ids[first] & ids[second])
        results[f"same_text_in_{first}_and_{second}"] = len(keys[first] & keys[second])
    results["ticket_ids_unique"] = all(
        part["ticket_id"].is_unique for part in parts.values()
    )
    results["validation_and_test_balanced"] = all(
        (part["label"].value_counts() == per_label).all()
        for part in (validation, test)
    )
    results["texts_with_placeholder"] = sum(
        int(part["text"].str.contains(TEMPLATE_PATTERN, regex=True).sum())
        for part in parts.values()
    )

    print("Split check")
    for name, value in results.items():
        print(f"  {name}: {value}")

    leaks = [v for k, v in results.items() if k.startswith("same_") and v != 0]
    if (
        leaks
        or not results["ticket_ids_unique"]
        or not results["validation_and_test_balanced"]
        or results["texts_with_placeholder"] != 0
    ):
        raise ValueError("The split is not clean, see the numbers above.")
    return results


def save_splits(train, validation, test, out_dir=PROCESSED_DIR):
    """Write the three split files to ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("validation", validation), ("test", test)):
        part.to_csv(out_dir / f"{name}.csv", index=False)
    print(f"Saved train.csv, validation.csv, test.csv to {out_dir}")


def main():
    data = load_dataset()
    check_data(data)

    train, validation, test = clean_and_split(data)
    total = len(train) + len(validation) + len(test)
    print(f"\nAfter removing repeats: {total} tickets")
    print(f"Split sizes: train {len(train)}, validation {len(validation)}, test {len(test)}")
    shares = pd.DataFrame(
        {
            "train": train["label"].value_counts(),
            "validation": validation["label"].value_counts(),
            "test": test["label"].value_counts(),
        }
    )
    print(shares.to_string())

    print()
    check_split(train, validation, test)
    save_splits(train, validation, test)


if __name__ == "__main__":
    main()
