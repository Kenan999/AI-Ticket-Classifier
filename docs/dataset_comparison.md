# Dataset: Bitext Customer Support

All numbers come from real runs of our scripts (`backend/preprocessing.py`, run on 10.11.2026). Nothing is estimated.

## 1. Source and version

- Dataset: Bitext Customer Support LLM Chatbot Training Dataset (provider: Bitext)
- Source: https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset
- File: `Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv`
- Version (Hugging Face commit): `430d1a89bd93bd1fa23c16f29dd53e73f0087443`, last modified 18.07.2024
- SHA-256: `6f81102b0100b97b8468eb04368033a23206bf1fde9d53500d5806ec1001a434` (matches Hugging Face, checked 10.11.2026)
- Licence: CDLA-Sharing-1.0 (https://cdla.dev/sharing-1-0/)
- Stored unchanged in `data/raw/`, not in Git. The licence allows redistribution only under conditions (same licence, credit to Bitext, mark changed files). To avoid these obligations, nobody commits the CSV files; everyone downloads the raw file with `python backend/download_data.py`.

## 2. Data checks

| Check | Result |
|---|---|
| Rows x columns | 26,872 x 5 (`flags`, `instruction`, `category`, `intent`, `response`) |
| Labels (`category`) | 11 |
| Missing values | 0 |
| Fully identical rows | 0 |
| Repeated customer texts (exact) | 2,237 |
| Repeated texts after ignoring case, punctuation and extra spaces | 2,799 |
| Same text with different labels (or intents) | 0 |

Tickets per label in the raw file, and how many intents each label has (27 intents in total, each with 950 to 1,000 tickets):

| Label | Intents | Tickets |
|---|---|---|
| ACCOUNT | 6 | 5,986 |
| ORDER | 4 | 3,988 |
| REFUND | 3 | 2,992 |
| INVOICE | 2 | 1,999 |
| CONTACT | 2 | 1,999 |
| PAYMENT | 2 | 1,998 |
| FEEDBACK | 2 | 1,997 |
| DELIVERY | 2 | 1,994 |
| SHIPPING | 2 | 1,970 |
| SUBSCRIPTION | 1 | 999 |
| CANCEL | 1 | 950 |

Observations:

- **Class balance is uneven, and the reason is the dataset construction:** every intent has about 1,000 tickets, and a label has between 1 and 6 intents. ACCOUNT has about 6.3 times more tickets than CANCEL. The label sizes therefore do not reflect real customer traffic. This is why validation and test are balanced (see section 3).
- **Placeholders in the texts:** 6,670 of 26,872 texts (24.8 %) contain a placeholder such as `{{Order Number}}`. There are 9 kinds. They are spread very unevenly over the labels: ORDER 72.9 %, INVOICE 44.8 %, ACCOUNT 30.6 %, REFUND 20.9 %, DELIVERY 20.6 %, and 0 % for the other six labels. A placeholder can therefore hint at the label, and real customer tickets will not contain them. We did not change the placeholders; whether to remove them is open for the modelling phase.
- **Same wording, different spelling:** many texts differ only by case or punctuation (for example `are charges for services reimbursable?` and `are charges for services reimbursable`). These are removed in section 3 so that they cannot land in different parts of the split.
- **Paraphrases:** the dataset contains many reformulations of the same request. We did not measure how similar the parts of the split still are, so the test score may be somewhat optimistic.

## 3. Cleaning and split

Cleaning (`remove_duplicates`):

- Tickets are compared by a simplified copy of the text (lower case, punctuation replaced by a space, repeated spaces reduced to one; placeholders are kept). Of every group of identical copies, the first ticket is kept.
- The wording of the kept tickets is not changed.
- Removed: 2,799 tickets. Kept: **24,073**. No removed text had a different label than the kept one.
- Columns kept: `ticket_id`, `text`, `label`. `intent`, `response` and `flags` are dropped: the MVP only classifies tickets, and RAG is out of scope in the technical handbook v5.
- `ticket_id` (for example `BT-00001`) is the row number of the raw file, so every ticket can be traced back to its raw row.

Split (`split_data`):

- **Balanced validation and test:** 200 tickets per label in `validation.csv` and 200 per label in `test.csv`, chosen randomly with the fixed seed 42. All remaining tickets go to `train.csv`.
- **This differs from the 70 / 15 / 15 proposal of the technical handbook v5.** The handbook calls it only a proposal and asks to document the real split. We chose a balanced split because the label sizes are an artefact of the dataset (see section 2): with a proportional split, ACCOUNT would count about 6 times more than CANCEL in the score. In a balanced test, a model that always answers one label reaches about 1/11 (9 %) instead of 22 % (the share of ACCOUNT).
- 200 per label is possible because the smallest label (CANCEL) has 929 tickets, so 529 remain for training. Results should still be reported per label.
- `train.csv` keeps the natural, uneven label sizes; this can be handled during training (for example with class weights).

| File | Tickets | Share of 24,073 |
|---|---|---|
| `data/processed/train.csv` | 19,673 | 81.7 % |
| `data/processed/validation.csv` | 2,200 | 9.1 % |
| `data/processed/test.csv` | 2,200 | 9.1 % |

Tickets per label (after cleaning and split):

| Label | Train | Validation | Test | Total |
|---|---|---|---|---|
| ACCOUNT | 4,912 | 200 | 200 | 5,312 |
| ORDER | 2,616 | 200 | 200 | 3,016 |
| REFUND | 2,160 | 200 | 200 | 2,560 |
| FEEDBACK | 1,589 | 200 | 200 | 1,989 |
| PAYMENT | 1,580 | 200 | 200 | 1,980 |
| SHIPPING | 1,548 | 200 | 200 | 1,948 |
| CONTACT | 1,544 | 200 | 200 | 1,944 |
| INVOICE | 1,385 | 200 | 200 | 1,785 |
| DELIVERY | 1,228 | 200 | 200 | 1,628 |
| SUBSCRIPTION | 582 | 200 | 200 | 982 |
| CANCEL | 529 | 200 | 200 | 929 |

Share of texts with a placeholder after cleaning: train 18.1 %, validation 13.5 %, test 13.5 %.

Rules for using the files: `test.csv` is not used for training, prompt tuning or model selection, only for the final evaluation. `validation.csv` is used for development decisions.

## 4. Test results

| Test | Result |
|---|---|
| `load_dataset()` reads `train.csv`, `validation.csv` and `test.csv` | yes: (19673, 3), (2200, 3), (2200, 3), columns `ticket_id`, `text`, `label`, all 11 labels in each |
| Same `ticket_id` in two parts | 0 (train/validation, train/test, validation/test) |
| Same simplified text in two parts | 0 (train/validation, train/test, validation/test) |
| `ticket_id` unique within each part | yes |
| Validation and test have exactly 200 tickets per label | yes |
| Reproducible | yes: two runs gave identical files (SHA-256 below) |

SHA-256 of the files (seed 42, 200 per label):

- `train.csv`: `41bccdb9ca2d79da7ec2a8c4cdf6b52505cce9e795b3d4afa4df0f54c7b7859b`
- `validation.csv`: `0c344ecd76f5cbf4bf0d4cc13e99acb7fd9b5962421f1843ba9e4f4cc6545edb`
- `test.csv`: `a70ddc40c79f172b1ba102118a557fc2cec8548d331601a27c1877330bb726ce`

The checksums were produced with the library versions in `requirements.txt` (pandas 3.1.1). With other versions, the random shuffle may differ.

How to reproduce:

```sh
python backend/download_data.py
python backend/preprocessing.py
```
