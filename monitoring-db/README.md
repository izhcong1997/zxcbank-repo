# ZXCBank release control room

A read-only page for the release meeting. Bots write labels and comments on GitHub. `fetch_data.py` reads them into `data.json`. `index.html` only displays that file.

## Live mode

Use a fine-grained token that can read this repository only. Do not commit it.

```bash
export GITHUB_TOKEN=...
export GITHUB_REPOSITORY=izhcong1997/zxcbank-repo
cd monitoring-db
./serve.sh
```

Open http://localhost:8080. The fetch runs every 20 seconds. The page reloads `data.json` every 30 seconds. Ctrl+C stops both processes.

If `data.json` is missing, the page shows `sample_data.json` and a Sample data badge.

## GitHub Pages

`.github/workflows/release-control-room.yml` rebuilds `data.json` and deploys this folder to GitHub Pages. It runs when a pull request is opened, reopened, closed, labeled, unlabeled, or updated, when a comment is created, every 15 minutes, and on manual dispatch. It does not commit to the repository.

## Labels

`security:blocked`, `security:ok`, `fix:requested`, `fix:in-progress`, `signoff:requested`, `signoff:approved`, `report:sent`.

## Marker

Bots add this hidden comment. The dashboard reads it and never writes one.

```html
<!-- zxc-bot {"bot":"security-analyst","step":4,"status":"done","summary":"Report v1 blocked","report_id":"R1","at":"2026-10-23T09:40:00Z"} -->
```

`bot` is `security-analyst`, `fixer`, `business-reporter`, or `release-captain`. `status` is `done`, `working`, or `failed`.

A fix pull request has a branch starting with `cursor/`, or a body that says `Fixes #123`. It stays on the same row as the original pull request.

## Steps

1. Code pushed.
2. Pull request opened to main.
3. Checks run: tests, CodeQL, AI Scan, Dependabot, Copilot Autofix.
4. Security Analyst writes report v1.
5. Fixer is called.
6. Cursor Cloud Agent writes the fix.
7. Fix pull request is opened.
8. Security Analyst re-checks and writes report v2.
9. Release Captain prepares the sign-off pack and waits for a human.
10. A human approves and the pull request merges.

Business Reporter emails Sean, first Blocked and then Ready. That comes from `report:sent` and the reporter marker. It is not one of the ten steps.

Dots: grey not started, blue in progress, green done, red blocked or failed, amber waiting on a human.

## Production

The Production panel shows the latest successful deployment to the `production` environment, when that status was created, and every open issue labelled `incident` with its labels and age. A missing deployment says "Nothing deployed yet". A 403 or 404 says "Not available".

## Token

Fine-grained, this repository only, all read: Contents, Deployments, Pull requests, Issues, Actions, Checks, Code scanning alerts. A 403 or 404 on one endpoint shows "not available" and does not stop the page.
