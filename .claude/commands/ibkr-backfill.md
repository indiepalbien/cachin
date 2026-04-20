---
description: Audit and backfill IBKR portfolio data — trades, deposits, exchange rates, and virtual transaction legs
---

# IBKR Backfill

Run after adding new IBKR activity statement data or when the portfolio looks wrong.
All commands support `--dry-run`. Always dry-run first.

## SSH prefix
```bash
railway ssh --service web --environment production -- python backend/manage.py
```

## Step-by-step audit + fix sequence

### 1. Check current state
```bash
# Show all IBKR emails and stocks
railway ssh --service web --environment production -- python backend/manage.py ibkr_status

# Show ibkr:USD balance ledger
railway ssh --service web --environment production -- python backend/manage.py ibkr_usd_balance
```

### 2. Reprocess any failed IBKR emails
```bash
railway ssh --service web --environment production -- python backend/manage.py ibkr_status --reprocess
```
Only retries emails with `processing_error` set.

### 3. Backfill exchange rates from forex trades
```bash
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_rates --dry-run
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_rates
```
Extracts EUR→USD rates from virtual EUR.USD transactions (e.g. 1.1697 from "BUY 4958.53 EUR.USD @ $1.1697").

### 4. Fix / create virtual legs for all historical trades
```bash
railway ssh --service web --environment production -- python backend/manage.py fix_ibkr_primary_txs --dry-run
railway ssh --service web --environment production -- python backend/manage.py fix_ibkr_primary_txs
```
Idempotent. Skips already-correct txs. Creates asset-leg + cash-leg for each trade.

### 5. Fill any missing cash legs
```bash
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_cash_legs --dry-run
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_cash_legs
```

### 6. Add missing deposit/withdrawal entries
Edit `backfill_ibkr_deposits.py` with new data, then:
```bash
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_deposits --dry-run
railway ssh --service web --environment production -- python backend/manage.py backfill_ibkr_deposits
```

## Adding a full year of historical data
Create a new command `backfill_ibkr_YYYY.py` modelled on `backfill_ibkr_2025.py`.
Required data from IBKR activity statement: Trades table + Deposits & Withdrawals table.

## Symbol → settlement currency mappings
Managed at `/manage/ibkr-symbol-currencies/` in the web UI, or seed for all users:
```bash
railway ssh --service web --environment production -- python backend/manage.py seed_ibkr_symbol_currencies
```
Current defaults: SUSW→EUR, VWRA→USD, VWRA.L→USD.

## Sign convention
- Positive amount = outflow from that sub-account (expense / purchase)
- Negative amount = inflow to that sub-account (income / deposit)

| Event | ibkr:SYMBOL | ibkr:SETTLE_CURRENCY |
|-------|-------------|----------------------|
| BUY   | −qty        | +proceeds            |
| SELL  | +qty        | −proceeds            |
| Deposit to IBKR | — | −amount |
| Withdrawal from IBKR | — | +amount |
