# Cachin (App Finanzas) — Copilot Instructions

**Project**: Multi-currency personal expense tracker with email automation, bulk import, and intelligent categorization.

## Architecture Overview

### Core Stack
- **Backend**: Django 4.2 + PostgreSQL (production) / SQLite (dev)
- **Task Queue**: Celery + Redis (for async email fetching, exchange rate updates)
- **Frontend**: Django templates + HTMX + Bootstrap
- **Deployment**: Railway (web, worker, beat processes via Procfile)
- **Python**: 3.9+, managed with `uv`

### Key Modules

| Module | Purpose |
|--------|---------|
| `expenses.models` | Core domain: Transaction, Category, Payee, Exchange rates, Email configs |
| `expenses.email_ingest` | Parse 3 email types (Chase, IBKR, Visa) → detect/create transactions |
| `expenses.copy_paste` | YAML-driven bulk import parser for 4 bank formats (ITAU, Scotia, BBVA) |
| `expenses.rule_engine` | Smart categorization: sanitize descriptions, extract tokens, apply rules |
| `expenses.tasks` | Celery tasks: `fetch_emails_task`, `sync_splitwise_for_user`, `update_exchange_rates` |

### Data Flow: Email → Transaction
1. **Fetch**: `fetch_emails` CLI/Celery task reads IMAP, stores raw EML in `UserEmailMessage`
2. **Parse**: `process_new_messages()` routes by sender (Chase/IBKR/Visa) → broker-specific parser
3. **Create or Queue**: If new, create `Transaction`; if duplicate, queue in `PendingTransaction`
4. **Categorize**: `CategorizationRule` auto-applies if description matches learned patterns

### Multi-Currency Architecture
- **Exchange**: User-specific rates, can override defaults (keyed by source→target currency + date)
- **DefaultExchangeRate**: Global rates from openexchangerates.org API (updated weekly via Celery)
- **amount_usd**: Cached on Transaction, calculated via closest historical rate (or inverse lookup)

## Development Workflows

### Setup & Running Locally
```bash
cd backend
uv sync                    # Install dependencies
python manage.py migrate   # Create DB schema
python manage.py runserver # Start Django dev server
```

### Email Processing Commands
```bash
# Fetch + parse + create transactions (full pipeline)
uv run python manage.py shell -c "from expenses.tasks import fetch_emails_task; fetch_emails_task.delay()"

# Fetch IMAP only (stores raw EML)
uv run python manage.py fetch_emails

# Parse stored messages to transactions/pending
uv run python manage.py ingest_emails

# Reset email state (for retrying)
uv run python manage.py clear_useremails

# View raw EML by ID
uv run python manage.py download_eml <id>
```

### Async Task Workers (Local with Redis)
```bash
redis-server                              # Start Redis
uv run celery -A misfinanzas worker -l info    # Worker
uv run celery -A misfinanzas beat -l info      # Scheduler (every 5 min)
```

### Testing & Validation
```bash
uv run python manage.py check       # Django system checks
uv run python manage.py collectstatic --noinput
python -m pytest backend/expenses/   # Run tests
```

## Project-Specific Patterns

### Email Parsers
Located in `expenses/email_parsers/`:
- **Chase**: Direct deposit / bill payment alerts → `parse_chase_alert()`
- **IBKR**: Stock trades → `parse_ibkr_trade()`
- **Visa**: Purchase alerts → `parse_visa_alert()`
- **Gmail Forwarding**: Confirmation links → `parse_gmail_forwarding_email()`

Each returns: `(description, amount, currency, external_id)` or None if parsing fails.

### Copy-Paste Bulk Import
**Config**: `expenses/copy_paste/configs.yaml` defines regex per bank/currency.
**Usage**: Form at `/polls/bulk-add/` → validate → preview → import selected rows.
**Supported Banks**: ITAU (debit/credit), Scotia (credit), BBVA (credit).

### Smart Categorization Rules
1. **Sanitization**: Strip generic words (paypal, bank, transaction), extract meaningful tokens
2. **Storage**: `CategorizationRule` stores `description_tokens`, `amount_range`, `category_id`
3. **Matching**: When categorizing manually, rule is auto-generated; applied to future similar transactions
4. **Accuracy**: Rules track hits/misses for prioritization

### User Onboarding
- `UserProfile.onboarding_step`: 0 = done, 1-5 = active steps
- Middleware enforces step progression; views advance via `_advance_onboarding()`
- Context passed to templates: `is_onboarding`, `onboarding_step`, `onboarding_total_steps`

## Critical Integration Points

### Email Configuration
- **UserEmailConfig**: Per-user alias (e.g., `automation.xyz123@cachinapp.com`)
- Auto-created on signup; used for filtering incoming emails
- Optional: per-user mailbox credentials OR shared ingest mailbox + app-level credentials
- **Env vars**: `EMAIL_FETCH_USER`, `EMAIL_FETCH_PASS`, `EMAIL_FETCH_IMAP_HOST`, `EMAIL_FETCH_IMAP_PORT`, `EMAIL_FETCH_IMAP_SSL`

### Splitwise Integration
- `SplitwiseAccount`: OAuth1 tokens stored per user
- `sync_splitwise_for_user()` task syncs expenses (manual or scheduled)
- Requires: `SPLITWISE_CONSUMER_KEY`, `SPLITWISE_CONSUMER_SECRET`

### External APIs
- **openexchangerates.org**: Fetches rates for COMMON_CURRENCIES every week (Celery scheduled)
- **IMAP**: User's email provider (configurable host/port)

## Testing & Debugging Tips

1. **Email parsing failures**: Check `UserEmailMessage.processing_error` field for root cause
2. **Exchange rate gaps**: Verify `DefaultExchangeRate` has entries; Transaction.amount_usd can be None if no rate found
3. **Duplicate detection**: `PendingTransaction` queue shows rejected imports; inspect `payload` field
4. **Categorization debug**: Test `rule_engine.sanitize_description()` with raw description strings
5. **Local IMAP**: Use `python manage.py fetch_emails` without Celery to test synchronously

## Files to Review for Major Changes

- **Models**: [expenses/models.py](../backend/expenses/models.py#L189) (Transaction, PendingTransaction, CategorizationRule)
- **Email Flow**: [expenses/email_ingest.py](../backend/expenses/email_ingest.py), [expenses/email_parsers/](../backend/expenses/email_parsers/)
- **Rules**: [expenses/rule_engine.py](../backend/expenses/rule_engine.py#L1)
- **Bulk Import**: [expenses/copy_paste/](../backend/expenses/copy_paste/) (configs.yaml, parsers.py)
- **Settings**: [misfinanzas/settings.py](../backend/misfinanzas/settings.py#L1), [misfinanzas/celery.py](../backend/misfinanzas/celery.py)
- **Views**: [expenses/views.py](../backend/expenses/views.py#L1) (1870 lines; key functions: exchange rate lookup, transaction creation, categorization)
