# Cachin — Project Guide

Personal finance tracker. Django backend, deployed on Railway.

## Project layout
```
backend/              Django app (manage.py here)
  expenses/           Main app: models, views, email parsers, management commands
  cachin/             Django project settings
  templates/          Base templates
.venv/                Virtualenv (use for all local python calls)
```

## Common commands
```bash
# Run tests
cd backend && /Users/rebelde/workspace/cachin/.venv/bin/python manage.py test expenses.tests --verbosity=2

# Make/apply migrations locally
cd backend && /Users/rebelde/workspace/cachin/.venv/bin/python manage.py makemigrations
cd backend && /Users/rebelde/workspace/cachin/.venv/bin/python manage.py migrate

# Run on Railway via SSH
railway ssh --service web --environment production -- python backend/manage.py <command>
```
Use `/migrate`, `/deploy`, `/test`, `/railway-watch`, `/railway-status` for common flows.

## Railway
- Token: `~/.railway/config.json` → `user.token`  (NOT `~/.config/railway/`)
- Web service ID: `c67ee567-b38b-4b81-a371-02ac7b2bef94`
- Auto-deploys on push to `main`; startup runs `migrate` + `collectstatic` + `gunicorn`

## Key models (backend/expenses/models.py)
- `Transaction` — core record; `is_virtual=True` for internal movements; `paired_transaction` FK (self)
- `Source` — funding source / sub-account (e.g. `ibkr:USD`, `ibkr:SUSW`)
- `Stock` — links a trade to its asset-leg `Transaction`
- `IBKRSymbolCurrency` — maps symbol → settlement currency (e.g. SUSW→EUR, VWRA→USD)
- `Exchange` — user-specific FX rates
- `Category`, `Payee`, `Project`, `Budget`, `BudgetGroup`, `SourceBankMapping`

## IBKR portfolio tracking
All IBKR trade legs are `is_virtual=True`. Only the bank-side deposit (BILL PAYMENT) is a real expense.

**Sub-accounts**: `ibkr:USD`, `ibkr:EUR`, `ibkr:SUSW`, `ibkr:VWRA`, `ibkr:VWRA.L` — auto-created `Source` objects.

**Per-trade schema:**
- Security trade: virtual asset-leg (`ibkr:SYMBOL ±qty`) + virtual cash-leg (`ibkr:SETTLE_CURRENCY ±amount`)
- Forex trade (EUR.USD): two virtual legs — `ibkr:USD` debit + `ibkr:BASE` credit
- BILL PAYMENT deposit: real bank tx + auto-created virtual `ibkr:USD` credit leg

**Settlement currency**: `IBKRSymbolCurrency` table. Seeded defaults: SUSW→EUR, VWRA→USD, VWRA.L→USD.

**Exchange rates**: auto-extracted from forex virtual txs via `backfill_ibkr_rates`.

**Virtual tx exclusions**: category / project / budget expense views filter `is_virtual=False`. Source expenses keep virtual txs visible (to show sub-account balances); non-ISO currencies (SUSW) handled without "missing rate" warnings.

**Sign convention** (positive = outflow from account, negative = inflow):
- BUY VWRA: `ibkr:VWRA` = −qty, `ibkr:USD` = +proceeds
- SELL VWRA: `ibkr:VWRA` = +qty, `ibkr:USD` = −proceeds
- Deposit to IBKR: `ibkr:USD` = −amount
- Withdrawal from IBKR: `ibkr:USD` = +amount

## IBKR management commands (all in backend/expenses/management/commands/)
| Command | Purpose |
|---------|---------|
| `ibkr_status [--reprocess]` | Show all IBKR emails/stocks; retry failed emails |
| `ibkr_usd_balance` | Audit ibkr:USD txs with running total |
| `backfill_ibkr_rates` | Extract EUR→USD rates from virtual forex txs |
| `fix_ibkr_primary_txs [--dry-run]` | Fix/create virtual legs for all historical trades (idempotent) |
| `backfill_ibkr_cash_legs [--dry-run]` | Add missing cash legs to existing asset-leg virtual txs |
| `backfill_ibkr_deposits [--dry-run]` | Add missing deposit/withdrawal ibkr:USD entries |
| `backfill_ibkr_2025 [--dry-run]` | Backfill all 2025 VWRA/VWRA.L trades + deposits from statement |
| `seed_ibkr_symbol_currencies` | Seed SUSW→EUR, VWRA→USD, VWRA.L→USD for all users |

## Email ingestion (backend/expenses/email_ingest.py)
Processes forwarded emails → `Transaction` records:
- Chase: BILL PAYMENT (IBKR deposits auto-get ibkr:USD counterpart), DIRECT DEPOSIT
- IBKR: trade confirmations → virtual asset+cash legs
- VISA, Alignet, Midinero parsers

## Useful production queries
```bash
# Check ibkr:USD balance
railway ssh --service web --environment production -- python backend/manage.py ibkr_usd_balance

# Show all IBKR emails and stocks
railway ssh --service web --environment production -- python backend/manage.py ibkr_status
```
