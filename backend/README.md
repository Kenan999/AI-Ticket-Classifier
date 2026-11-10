# Backend

Python part of the project. At the moment it contains the data pipeline (download and loading of the dataset). The application backend (API, classifier) has not been implemented yet; the framework, endpoints and configuration will be agreed before implementation.

The current deployment publishes only `frontend/`; running a backend requires a separate server service configuration.

## Setup

Run from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Activate the virtual environment (`source .venv/bin/activate`) in every new terminal before working on the backend.

## Data

The project uses the [Bitext Customer Support dataset](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset) (licence: [CDLA-Sharing-1.0](https://cdla.dev/sharing-1-0/)).

The CSV is not stored in Git. The licence allows redistribution only under conditions (attribution, licence text, no extra restrictions), so we keep the file out of the repository; `data/` is listed in `.gitignore`. Instead, every team member downloads the same file once:

```sh
python backend/download_data.py
```

The script creates `data/raw/` if needed, downloads a pinned version of the CSV and verifies its SHA-256 checksum, so everyone has an identical file. If a correct file is already there, it does nothing.

To check that the data loads:

```sh
python backend/data_loader.py
```

`backend/data_loader.py` (`load_dataset(path)`) returns the tickets as a table with the columns `ticket_id`, `text` and `label`. It reads the raw CSV as well as the split files in `data/processed/`. The raw CSV is never modified.

## Train / validation / test split

```sh
python backend/preprocessing.py
```

`backend/preprocessing.py` removes repeated tickets (compared by a simplified copy of the text; the wording of the tickets is not changed) and splits the data with seed 42: `validation.csv` and `test.csv` get 200 tickets per label each (balanced), `train.csv` gets everything else. It writes the three files to `data/processed/` with the columns `ticket_id`, `text` and `label`, and prints checks that no ticket is in two parts. The files are not stored in Git; everyone creates them with this command. Why the split is balanced and not 70 / 15 / 15 is explained in [docs/dataset_comparison.md](../docs/dataset_comparison.md).

`test.csv` is only used for the final evaluation, never for training or model selection. The numbers and checks are documented in [docs/dataset_comparison.md](../docs/dataset_comparison.md).

## Workflow

Develop and test on a working branch, update the documentation, and open a pull request for review.
