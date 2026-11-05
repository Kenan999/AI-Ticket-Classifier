# IHK-Projekt

Team project for “Generative AI Expert (IHK)”. The current project name is unchanged.

## Overview

[Public project website](https://ihk-projekt.kali.sarl)

The website currently displays only the project title. Project content will be added as the team develops it.

## Requirements and technical scope

The frontend is a single static HTML file, `public/index.html`, with embedded CSS. It requires no Node.js, npm, framework, package installation, environment variables, database or build step. You can open the file directly in a browser.

For local HTTP development, install Git and Python 3. The commands below have been checked with Python 3.12.3. No additional Python packages are required. No application backend has been implemented; the static production web server is not an application backend. Private operations and ticket-system files are separate from this team repository.

## Clone the repository

The repository is public: reading and cloning do not require a GitHub account. Pushing changes still requires an authorized GitHub account and configured Git authentication. Never put credentials in files or clone URLs.

```sh
git clone https://github.com/Kenan999/IHK-Projekt.git
cd IHK-Projekt
```

## Run locally

From the repository directory:

```sh
python3 --version
python3 -m http.server 8000 --bind 127.0.0.1 --directory public
```

Open `http://127.0.0.1:8000/` in your browser. Stop the server with `Ctrl+C`. If port 8000 is busy, use another available port and update the browser address. Serve only `public/`; do not expose the repository root as a web directory.

## Check changes

There is currently no automated test suite for the static team website in this repository. Open the development page in a browser and check its content, readability, narrow and wide layouts, and any links. With the local server running, check HTTP availability using:

```sh
python3 -c "import urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/'); print(r.status); assert r.status == 200"
```

An HTTP check confirms availability, not visual correctness. Private ticket-system tests do not validate the team website.

## Collaboration and publishing

The intended workflow is **branch → push → pull request → tests and review → merge**.

1. Start a working branch from an up-to-date `main`, for example `git switch -c team/topic`.
2. Develop and check the change in your own clone. Update this README to match the resulting project state.
3. Review `git diff` and `git status`, then stage and commit only the intended team files. Never include private files or secrets.
4. Publish your working branch with `git push -u origin team/topic` and open a pull request targeting `main`.
5. Complete the available checks and team review before merging.

`Frontend` and `Backend` are development branches in the same repository, not separate applications or a substitute for a future directory structure. `Frontend` contains the current static page under `public/`. `Backend` is a starting point for future application work; its architecture, dependencies and interfaces have not yet been agreed or implemented.

A push to a development branch does not update the live website. Merging into `main` authorizes automatic publication of a valid static website. Review is currently a team workflow agreement, not a claim that GitHub branch protection enforces it.

A separate development clone is available. A separately accessible development preview, a GitHub CI pipeline and GitHub branch protection have not been verified as configured.

## Automatic publication from main

A server-side timer checks GitHub `main` approximately every 30 seconds. Fetching and validation take additional time; immediate or precisely timed publication is not guaranteed. No GitHub Actions workflow is required for this mechanism.

Only `public/` from the fetched commit is published. The deployment process does not execute repository code, install packages, run builds or deploy an application backend. Feature branches are not published.

A release must contain a complete static `public/index.html`. Supported file extensions are `.html`, `.css`, `.js`, `.json`, `.svg`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.ico`, `.woff`, `.woff2`, `.ttf`, `.txt` and `.webmanifest`. Hidden files, symbolic links and executable files are rejected. Limits are 2,000 files, 50 MiB in total and 2 MiB for the HTML entry point. The entry point must contain an HTML document. These checks are not a complete HTML, security or functionality test suite.

The clean deployment cache and live releases are separate from development clones and private data. Fetch failures or an invalid or missing entry point leave the current website unchanged. A validated release is activated atomically, then an HTTP check compares the served homepage with the commit content. A failed HTTP check restores the previous release. Concurrent deployment attempts are serialized.

The server operator can pause polling and restore an earlier retained release using the private operations instructions. A later push to `main` can publish again. Old releases are not automatically deleted, so disk use must be monitored.

Controlled server-side tests have covered valid releases, ignored feature branches, invalid pages, exclusion of private files, serialization and HTTP rollback. The initial real GitHub-to-live publication has also been verified. These HTTP checks do not establish visual browser correctness.

## Development and live files

Develop only in your own development clone. In the publication project, `public/` points to the active validated release. Deployment management, its fetch cache and retained releases are all kept inside that publication project in a nonpublic operations area. Website changes reach live through GitHub `main` and the poller, never by directly editing live files. Keeping deployment files within the publication project does not change the polling interval, validation or rollback behavior.

## Keep this README current

After each change to the actual IHK team project, update the prerequisites, dependencies, installation, configuration without secrets, local start, checks and development/deployment workflow as needed. Work limited to the private ticket system is excluded. The published instructions should let another contributor clone the repository and develop independently.
