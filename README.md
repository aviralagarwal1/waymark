# Waymark

Make your job hunt easier. Waymark tracks your target roles, maps their hiring cycles, and notifies you the moment they open.

**Self-hosted · Accounts · Python + React · MIT**

This is an early release. Historical coverage varies by employer, and missing dates stay unknown. Automatic monitoring supports Greenhouse, Lever, Ashby, and pages with `JobPosting` structured data; other sites need manual research or a new connector.

## What it does

- An editable watchlist of companies and roles, with intended start dates kept separate from the window in which to watch for applications.
- Evidence-backed research of prior postings. Each historical date records its precision and what it means: original posting, last publication, archive observation, announced month, or unknown.
- Current careers sources stored separately from old posting links, and monitored only after you approve them.
- CSV/XLSX import with a preview, and exports with stable IDs. XLSX exports include an Evidence sheet.
- Scheduled checks; immediate, per-scan, daily, or weekly email; reminders; quiet hours; and a daily email cap.
- Applied, dismissed, snoozed, and paused states that control follow-ups.
- An Activity view of worker health, source errors, tasks, and email previews.

Data lives in a local SQLite database, or in Postgres when `DATABASE_URL` is set. Exports are snapshots, not live sync. Importing targets never enables monitoring on its own, and reimporting existing IDs requires a merge preview with matching row versions. An archive capture shows a page existed by a date; it does not prove when a role opened.

## Try the demo

Install Docker with Compose, clone this repository, then run:

```sh
docker compose up --build -d
```

Open **http://localhost:8000** and choose **Create account**. In demo mode a new account is confirmed and filled with synthetic examples straight away, and email stays as previews. It needs no API credentials, sends no email, and needs no external services once the image is built. Stopping the containers keeps the database:

```sh
docker compose down
```

## Use your own targets

1. Copy `.env.example` to `.env.local`. Set `APP_MODE=live` and a `DATA_DIR` different from the demo's; a data directory belongs to one mode.
2. Add an Anthropic API key if you want automatic research. Manual sources and monitoring work without one.
3. Keep `EMAIL_TRANSPORT=preview` while setting up. Switch to `resend` or `smtp` once previews in Activity look right.
4. Start with your configuration, and pass the same `--env-file` to every Compose command:

   ```sh
   docker compose --env-file .env.local up --build -d
   ```

5. Create an account (in demo mode it is confirmed and filled with examples straight away), then in Preferences set your defaults and timezone. Add targets or import a spreadsheet (the import dialog offers a template), research them, review the evidence, then approve monitoring.

**Keep the host running.** A sleeping laptop cannot check sources. Activity shows the worker heartbeat and the last successful checks.

AI research is billed by your provider. Research has search and token limits and a monthly budget, and its reported cost is an estimate. When research is enabled, target details and fetched page text are sent to Anthropic. The app has no telemetry.

### Configuration

All configuration comes from environment variables; the app does not read `.env` files itself. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_MODE` | `demo` | `demo` or `live` |
| `DATA_DIR` | `./data` | Host directory for the SQLite database |
| `DATABASE_URL` | | A Postgres URL (such as Neon's `postgresql://…`) to use instead of SQLite |
| `APP_BASE_URL` | `http://localhost:8000` | Public origin, used in email links; `https://` makes session cookies secure-only |
| `ANTHROPIC_API_KEY` | | Enables automatic research |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Research model |
| `EMAIL_TRANSPORT` | `preview` | `preview`, `resend`, or `smtp`; demo mode requires `preview` |
| `EMAIL_FROM` | | Sender address for every email, such as `waymark@your-domain.com` |
| `RESEND_API_KEY` | | Resend delivery |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_SSL` | | SMTP delivery |
| `WORKER_STALE_MINUTES` | `5` | How old the worker's heartbeat may be before the app reports it stopped. Raise it when the worker runs on a schedule instead of continuously |
| `TRUSTED_PROXY_HOPS` | `0` | Number of proxies in front of the app that append to `X-Forwarded-For`, so sign-in rate limits see each visitor's address instead of the proxy's. Leave at `0` unless a proxy is there |

## Running it safely

- Everyone signs in with an email and password; each account sees only its own data. Passwords are stored as Argon2id hashes, and sessions and email links as SHA-256 digests. Sign-up asks people to confirm their email before they can sign in, except in demo mode.
- It binds to localhost. For remote access, terminate TLS in front of it, preserve the public `Host` header, and set `APP_BASE_URL` to the public `https://` origin so email links point there and cookies are secure-only. If the proxy appends to `X-Forwarded-For`, set `TRUSTED_PROXY_HOPS` to the number of such proxies; setting it with no proxy in front would let visitors pick the address their rate limit counts against.
- Anyone can delete their account from Preferences after entering their password again. It deletes their targets, research, openings, email history, and preferences at once.
- With `EMAIL_TRANSPORT=preview`, nothing is sent; account emails, including their links, are printed to the worker log so you can follow them locally.
- Keep API, Resend, and SMTP secrets in environment configuration only.
- With SQLite, run one web process and one worker on the same host, and keep the database off network filesystems. With Postgres, the web process and worker can run anywhere that reaches it, and the worker can run as a single pass on a schedule with `python -m waymark.worker --once`.
- If the process stops after an SMTP server accepts a message, that email is marked uncertain for you to check rather than resent. Resend sends are retried a few times under one idempotency key, so a retry cannot duplicate an email.
- Source failures never count as empty boards and never close jobs.
- The app fetches only the public careers pages you configure and never runs their scripts. Respect each site's terms and rate limits.

### Backup and restore

Stop both processes, then copy the database from your `DATA_DIR`, along with any `-wal` and `-shm` files that remain:

```sh
docker compose down
cp data/waymark.db backups/waymark-$(date +%Y%m%d).db
docker compose up -d
```

Restore by copying a backup back to `data/waymark.db` while stopped. Back up before every upgrade, then rebuild with `docker compose up --build -d` and check Activity for the worker heartbeat.

## Development

Requires Python 3.12+ and Node 22+.

```sh
python -m venv .venv
# Activate .venv with your shell's usual command.
python -m pip install -e ".[dev]"
npm --prefix web ci
npm --prefix web run build
python -m uvicorn waymark.api:app --host 127.0.0.1 --port 8000
```

In a second terminal, with the virtual environment active, run the worker with `python -m waymark.worker` (add `--once` for a single pass). For frontend work, `npm --prefix web run dev` starts Vite and proxies API requests to port 8000. The API schema is at `/docs`.

Checks, which CI also runs:

```sh
python -m pytest
python -m ruff check waymark tests evaluations
npm --prefix web run build
python -m evaluations.run_discovery
```

To run the tests against Postgres instead of SQLite, set `TEST_DATABASE_URL` to an empty database you can discard; the tests empty its tables.

The discovery evaluation runs 40 synthetic cases through source validation and matching, with no network or paid calls. It does not measure how well research finds real employers, and its pass rate is not a coverage claim.

### Layout

- `waymark/`: the API, worker, persistence, and email. `waymark/discovery/` holds connectors, safe fetching, matching, and AI research.
- `web/`: the React frontend.
- `migrations/`: Alembic.
- `tests/` and `evaluations/`: regression tests and the synthetic discovery harness.

## Contributing

Issues and pull requests are welcome. Keep changes focused, match the existing style, add or update tests for behavior changes, and run the checks above. Never commit credentials, databases, or exports.

New source connectors live in `waymark/discovery/connectors.py`. A connector needs tests with recorded response shapes in `tests/test_discovery_connectors.py`, covering partial and failed fetches as well as success. Keep the source's date semantics honest: an update time is not a publication date, and a missing date stays unknown. Workday, LinkedIn, and browser scraping are out of scope.

## Scope

No billing, automatic applications, resume generation, universal scraping, or guaranteed historical recovery.

Licensed under [MIT](LICENSE). Employer content and trademarks belong to their owners.
