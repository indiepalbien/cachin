# App Finanzas — Email Automation

## Email automation (fetching messages)

We introduced two models:
- `expenses.models.UserEmailConfig`: per-user alias like `<random>.automation@cachinapp.com` auto-created on user signup.
- `expenses.models.UserEmailMessage`: stores raw EML and basic metadata for matched emails.

### Run locally

```
uv run python backend/manage.py fetch_emails --username $EMAIL_USER --password $EMAIL_PASS
```

Environment/config settings used:
- `EMAIL_FETCH_IMAP_HOST` (default `imap.cachinapp.com`)
- `EMAIL_FETCH_IMAP_PORT` (default `993`)
- `EMAIL_FETCH_IMAP_SSL` (default `True`)
- Optionally `EMAIL_FETCH_USER` / `EMAIL_FETCH_PASS` in settings/env if not passing CLI args.

### Configure app-level mailbox (recommended)

Set the following environment variables (locally via `.env`, on Railway via Variables):

```
EMAIL_FETCH_USER=automation@cachinapp.com
EMAIL_FETCH_PASS=<secure-password>
EMAIL_FETCH_IMAP_HOST=imap.cachinapp.com
EMAIL_FETCH_IMAP_PORT=993
EMAIL_FETCH_IMAP_SSL=True
```

Then run without CLI flags:

```
uv run python backend/manage.py fetch_emails
```

### Load `.env` automatically (local)

We added `python-dotenv`. If a `.env` file exists at the repo root, settings will load it automatically. Create one from the example:

```
cp .env.example .env
```

Now you can run the app and commands without exporting variables manually.

### What the command does

- Connects to IMAP, searches `UNSEEN` emails.
- For each email, matches any recipient address to a user alias (`UserEmailConfig.full_address`).
- If matched, stores the raw EML and metadata in `UserEmailMessage`.
- Marks stored messages as `\\Seen`.

### Future work

- Filter which emails to ingest.
- Parse EML into transactions.
- Background scheduling via Celery and Redis on Railway.
