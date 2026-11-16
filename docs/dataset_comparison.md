# Dataset: Bitext Customer Support

All numbers come from real runs of our scripts (`backend/preprocessing.py`, last run on 13.11.2026). Nothing is estimated. Sections 1 and 2 describe the raw file (11 labels); sections 3 and 4 describe the cleaned data (9 labels, see section 3).

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

- **Class balance is uneven, and the reason is the dataset construction:** every intent has about 1,000 tickets, and a label has between 1 and 6 intents. ACCOUNT has about 6.3 times more tickets than CANCEL (about 3 times more than the smallest of the 9 kept labels, SHIPPING). The label sizes therefore do not reflect real customer traffic. This is why validation and test are balanced (see section 3).
- **Placeholders in the texts:** 6,670 of 26,872 texts (24.8 %) contain a placeholder such as `{{Order Number}}`. There are 9 kinds. They are spread very unevenly over the labels: ORDER 72.9 %, INVOICE 44.8 %, ACCOUNT 30.6 %, REFUND 20.9 %, DELIVERY 20.6 %, and 0 % for the other six labels. A placeholder can therefore hint at the label, and real customer tickets will not contain them. For this reason the placeholders are cut out of the texts in section 3.
- **Same wording, different spelling:** many texts differ only by case or punctuation (for example `are charges for services reimbursable?` and `are charges for services reimbursable`). These are removed in section 3 so that they cannot land in different parts of the split.
- **Paraphrases:** the dataset contains many reformulations of the same request. We did not measure how similar the parts of the split still are, so the test score may be somewhat optimistic.

## 3. Cleaning and split

Cleaning runs in this order (all steps are functions in `backend/preprocessing.py`):

| Step | Function | Tickets after the step |
|---|---|---|
| Raw file | | 26,872 |
| 1. Leave out two labels | `drop_labels` | 24,923 (1,949 dropped) |
| 2. Cut out the placeholders | `remove_templates` | 24,923 (6,670 texts changed) |
| 3. Remove repeated tickets | `remove_duplicates` | **21,891** (3,032 dropped) |

Details:

- **Dropped labels (team decision).** CANCEL (950 raw tickets) contains only questions about cancellation fees and SUBSCRIPTION (999) only about a newsletter. Neither is a ticket category of the shop, so both are left out completely, not merged into another label. Unclear or off-topic messages have no label of their own in this data; how the system should treat them is open for the team and is not measured by this dataset.
- **Placeholders are cut out of the texts.** A placeholder such as `{{Order Number}}` is removed together with the space before it: `wanna see order {{Order Number}} status help me` becomes `wanna see order status help me`. This is the only change to a ticket text; all other texts keep their exact wording. Reason: a placeholder hints at the label (72.9 % of the raw ORDER tickets contain one, see section 2) and real customers do not write one. Tickets with a placeholder are not deleted, because the ORDER topics cancel, change and track order almost always contain an order number; deleting them would leave only about 25 tickets per topic. A few texts are a little unnatural (`a account`, `invoice from`, `cancel order ?`); this does not change what they are about.
- **Repeats are removed last.** Cutting out the placeholders makes different tickets identical (for example `a {{Account Type}} account` and `a {{Account Category}} account`). Tickets are compared by a simplified copy of the text (lower case, punctuation replaced by a space, repeated spaces reduced to one). Of every group of identical copies, the first ticket is kept. If a text has two different labels, the script stops with an error (this does not happen in our data).
- Columns kept: `ticket_id`, `text`, `label`. `intent`, `response` and `flags` are dropped: the MVP only classifies tickets, and RAG is out of scope in the technical handbook v5.
- `ticket_id` (for example `BT-00001`) is the row number of the raw file, so every ticket can be traced back to its raw row.

Split (`split_data`):

- **Balanced validation and test:** 200 tickets per label in `validation.csv` and 200 per label in `test.csv`, chosen randomly with the fixed seed 42. Every label counts equally in the evaluation, so the results can be compared between labels. The label sizes of Bitext are an artefact of the dataset (see section 2); a proportional split would let ACCOUNT (23 % of the tickets) dominate the score. With 9 balanced labels, a model that always answers the same label reaches about 11 %.
- **Train:** all remaining tickets go to `train.csv`. It keeps the natural, uneven label sizes (for example class weights can compensate) and is only needed if a model is trained.
- The smallest label (DELIVERY) has 1,618 tickets, so 200 + 200 are possible and 1,218 remain for `train.csv`. Results should be reported per label.

| File | Tickets |
|---|---|
| `data/processed/train.csv` | 18,291 |
| `data/processed/validation.csv` | 1,800 |
| `data/processed/test.csv` | 1,800 |

Tickets per label (after cleaning and split):

| Label | Train | Validation | Test | Total |
|---|---|---|---|---|
| ACCOUNT | 4,668 | 200 | 200 | 5,068 |
| ORDER | 2,600 | 200 | 200 | 3,000 |
| REFUND | 2,159 | 200 | 200 | 2,559 |
| FEEDBACK | 1,589 | 200 | 200 | 1,989 |
| PAYMENT | 1,580 | 200 | 200 | 1,980 |
| SHIPPING | 1,548 | 200 | 200 | 1,948 |
| CONTACT | 1,544 | 200 | 200 | 1,944 |
| INVOICE | 1,385 | 200 | 200 | 1,785 |
| DELIVERY | 1,218 | 200 | 200 | 1,618 |

No text contains a placeholder (0 in train, validation and test; the script checks this).

Rules for using the files: `test.csv` is not used for training, prompt tuning or model selection, only for the final evaluation. `validation.csv` is used for development decisions.

## 4. Test results

| Test | Result |
|---|---|
| `load_dataset()` reads `train.csv`, `validation.csv` and `test.csv` | yes: (18291, 3), (1800, 3), (1800, 3), columns `ticket_id`, `text`, `label`, all 9 labels in each |
| Same `ticket_id` in two parts | 0 (train/validation, train/test, validation/test) |
| Same simplified text in two parts | 0 (train/validation, train/test, validation/test) |
| `ticket_id` unique within each part | yes |
| Validation and test have exactly 200 tickets per label | yes |
| Texts that contain a placeholder | 0 |
| Reproducible | yes: two runs gave identical files (SHA-256 below) |

SHA-256 of the files (seed 42, 200 per label):

- `train.csv`: `cd3331c0c4d80a595edd254f5116890f9a6e82114e2d0a045a7fbf27fc8610b3`
- `validation.csv`: `c584d55070cc8ae42ccec4ad17450035cc2e9b3d2c3e99aee12bbcd51a839a0d`
- `test.csv`: `c1222c8704f11004d8bea3c012a18910743f3767e71bb548deee4094c62ebd23`

The checksums were produced with the library versions in `requirements.txt` (pandas 3.1.1). With other versions, the random shuffle may differ.

How to reproduce:

```sh
python backend/download_data.py
python backend/preprocessing.py
```
