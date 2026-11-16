# AI Ticket Classifier — Frontend

The frontend source on this branch is in `public/`.

## Downloaded development starter

When using the shared backend during frontend development, keep the downloaded
`developer_client.py` in the project root. Git ignores that local file; do not
force-add it or commit access tokens. Follow the team setup guide for the local
connection workflow. Updating this ignore rule does not change the backend or
deploy the frontend.

## Test the frontend with the deployed backend

Keep your normal startup command unchanged. For shared-backend testing, download
the latest starter from the ticket system into this project root, then run:

```sh
python3 developer_client.py --frontend public --port 8015
```

Paste your own one-hour token at the hidden prompt and open the printed address.
The starter supplies `runtime-config.js` dynamically so API calls use its proxy.
Normal serving uses the checked-in config and retains the existing local backend
address. No source-file edits or tokens in the browser are needed. You can choose
another port with `--port`; the API connection follows automatically.

Requests use shared live cases. Stop the starter with Control-C when finished.
