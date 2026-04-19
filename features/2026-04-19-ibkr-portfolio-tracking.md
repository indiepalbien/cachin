# IBKR Portfolio Tracking Implementation Plan

## Overview

Extend the IBKR trade ingestion pipeline to model each trade as two paired transactions (double-entry style), treating IBKR as an account with sub-balances per currency/security (ibkr:USD, ibkr:EUR, ibkr:SUSW, ibkr:VWRA, etc.). Add a portfolio view showing current holdings.

## Current State Analysis

When `email_ingest.py:_process_ibkr_trade()` processes "BOUGHT 405 SUSW LSEETF @ $12.2947719":
- Creates one `Transaction`: amount=+4979.39, currency=USD, source="ibkr"
- Creates one `Stock`: symbol="SUSW LSEETF", amount=405, unitprice=12.2947719, linked to that TX
- No sub-source concept; no way to compute "how many SUSW shares I hold"

For forex trades like "BOUGHT 4958.53 EUR.USD @ $1.1697":
- Creates one `Transaction` and one `Stock(symbol="EUR USD")` — treating a currency pair as a stock (wrong)

The `currency` field on `Transaction` is `CharField(max_length=3)` — too short for security symbols.

## Desired End State

Each IBKR trade generates **two linked transactions**:

**Security buy: "BOUGHT 405 SUSW LSEETF @ $12.2947719"**
- Tx A: amount=+4979.39, currency=USD, source=ibkr:USD *(cash out leg)*
- Tx B: amount=-405, currency=SUSW, source=ibkr:SUSW, is_virtual=True, paired_transaction=Tx A *(shares in leg)*

**Forex: "BOUGHT 4958.53 EUR.USD @ $1.1697"**
- Tx A: amount=+5800.12, currency=USD, source=ibkr:USD *(USD out, = 4958.53 × 1.1697)*
- Tx B: amount=-4958.53, currency=EUR, source=ibkr:EUR, is_virtual=True, paired_transaction=Tx A *(EUR in)*
- No `Stock` record for forex trades

**Portfolio view** at `/portfolio/` shows, per ibkr sub-source:
- Currency sub-accounts (ibkr:USD, ibkr:EUR): net inflow/outflow (based on tracked trades only)
- Security holdings (ibkr:SUSW, ibkr:VWRA): current shares = -sum(amount) for that source

### Key Discoveries

- `email_ingest.py:211-240` — current atomic block creating Stock + Transaction
- `models.py:371-397` — `Stock` model; we keep it, but skip it for forex trades
- `models.py:241` — `currency = CharField(max_length=3)` needs extending to 20
- `email_parsers/ibkr.py:29` — regex preserves dots in symbols ("EUR.USD", "SUSW LSEETF")
- Forex detection heuristic: symbol matches `r'^[A-Z]{3}\.[A-Z]{3}$'`

## What We're NOT Doing

- Migrating existing Stock/Transaction records to the new paired format
- Tracking IBKR deposits/withdrawals (so USD balance = trades only, not actual account balance)
- Fetching live prices for portfolio valuation
- Changing the existing transaction list view or `Stock` admin

---

## Phase 1: Extend Transaction Model

### Overview
Add `is_virtual` and `paired_transaction` fields to `Transaction`, and extend `currency` to 20 chars.

### Changes Required

#### 1. `backend/expenses/models.py`

Add two fields to `Transaction` (after `is_reimbursable`):

```python
is_virtual = models.BooleanField(
    default=False,
    help_text="Virtual counter-leg of a trade (e.g., shares received). Not a real cash flow."
)
paired_transaction = models.ForeignKey(
    'self',
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name='pair',
    help_text="The other leg of a paired trade transaction."
)
```

Extend `currency`:
```python
currency = models.CharField(max_length=20)  # was 3; extended for security symbols
```

#### 2. Migration

```bash
python manage.py makemigrations expenses --name add_virtual_transaction_fields
python manage.py migrate
```

### Success Criteria

#### Automated Verification
- [ ] Migration applies cleanly: `python manage.py migrate --check` (after applying)
- [ ] `Transaction` has `is_virtual`, `paired_transaction`, `currency` max_length=20 in DB

---

## Phase 2: Update IBKR Email Ingestion

### Overview
Modify `_process_ibkr_trade()` to create two paired transactions per trade. Add forex detection. For forex: create two real transactions, no Stock record. For securities: create USD tx + virtual shares tx + Stock record (as before).

### Changes Required

#### 1. `backend/expenses/email_ingest.py`

**Helper: detect forex trade**
```python
import re as _re

_FOREX_PATTERN = _re.compile(r'^[A-Z]{3}\.[A-Z]{3}$')

def _is_forex(symbol: str) -> bool:
    """Return True if symbol is a currency pair like EUR.USD."""
    return bool(_FOREX_PATTERN.match(symbol))
```

**Helper: get symbol short name for sub-source**
```python
def _symbol_key(symbol: str) -> str:
    """Extract the primary ticker for use as a sub-source key.
    
    'SUSW LSEETF' -> 'SUSW'
    'EUR.USD'     -> 'EUR'  (base currency)
    'AAPL'        -> 'AAPL'
    """
    if '.' in symbol:
        return symbol.split('.')[0]
    return symbol.split()[0]
```

**Modified `_process_ibkr_trade()`** — replace the atomic block at lines 211-240:

```python
with transaction.atomic():
    tx_date = msg.date.date() if msg.date else date.today()
    action = "BUY" if parsed["bought"] else "SELL"
    cash_amount = parsed["total_value"] if parsed["bought"] else -parsed["total_value"]
    description = f"{action} {parsed['amount']} {parsed['symbol']} @ ${parsed['unitprice']}"

    forex = _is_forex(parsed["symbol"])

    # --- Primary transaction: cash leg (USD out/in) ---
    tx = Tx.objects.create(
        user=msg.user,
        date=tx_date,
        description=description,
        amount=cash_amount,
        currency="USD",
        source=_get_or_create_source(msg.user, "ibkr:USD"),
        external_id=external_id,
        status="confirmed",
    )

    # --- Paired transaction: asset leg ---
    if forex:
        # e.g. EUR.USD: base=EUR, quote=USD
        base_currency = parsed["symbol"].split(".")[0]   # "EUR"
        # shares_amount = units of base currency received (negative = received)
        paired_amount = -parsed["amount"] if parsed["bought"] else parsed["amount"]
        paired_currency = base_currency
        paired_source_name = f"ibkr:{base_currency}"
    else:
        symbol_key = _symbol_key(parsed["symbol"])       # "SUSW"
        paired_amount = -parsed["amount"] if parsed["bought"] else parsed["amount"]
        paired_currency = symbol_key
        paired_source_name = f"ibkr:{symbol_key}"

    virtual_tx = Tx.objects.create(
        user=msg.user,
        date=tx_date,
        description=description,
        amount=paired_amount,
        currency=paired_currency,
        source=_get_or_create_source(msg.user, paired_source_name),
        external_id=external_id + ":pair" if external_id else None,
        status="confirmed",
        is_virtual=True,
        paired_transaction=tx,
    )

    # --- Stock record (securities only, not forex) ---
    if not forex:
        stock = Stock.objects.create(
            user=msg.user,
            date=tx_date,
            symbol=parsed["symbol"],
            bought=parsed["bought"],
            amount=parsed["amount"],
            unitprice=parsed["unitprice"],
            external_id=external_id,
            transaction=tx,
        )
```

Update the `exists` duplicate-check at line 196 to also block on virtual_tx external_id:
```python
# existing check on Stock is sufficient for securities
# for forex trades there's no Stock, so also check Transaction external_id
exists = (
    Stock.objects.filter(user=msg.user, external_id=external_id).exists()
    or Tx.objects.filter(user=msg.user, external_id=external_id, is_virtual=False).exists()
) if external_id else False
```

### Success Criteria

#### Automated Verification
- [ ] Existing IBKR tests still pass: `python manage.py test expenses.tests`
- [ ] A test for a security buy produces 2 transactions + 1 stock record
- [ ] A test for a forex buy produces 2 transactions + 0 stock records
- [ ] Duplicate detection still works (second identical email → PendingTransaction)

#### Manual Verification
- [ ] Process a real IBKR security-buy email → verify two transactions appear in transaction list with correct sources
- [ ] Process a real IBKR forex email → verify two transactions, no erroneous Stock record
- [ ] Both transactions have the same description; virtual one has `is_virtual=True`

---

## Phase 3: Portfolio View

### Overview
New page at `/portfolio/` showing current IBKR holdings grouped by sub-source.

### Changes Required

#### 1. `backend/expenses/views.py` — add view function

```python
def portfolio_view(request):
    """Show current holdings per IBKR sub-source."""
    from django.db.models import Sum
    
    ibkr_sources = Source.objects.filter(
        user=request.user,
        name__startswith="ibkr:"
    ).order_by("name")
    
    holdings = []
    for source in ibkr_sources:
        symbol = source.name[len("ibkr:"):]  # strip "ibkr:" prefix
        net = Transaction.objects.filter(
            user=request.user,
            source=source,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        
        # Convention: negative net = you hold that much (received more than sent)
        # For display we negate so "holdings" are positive
        holdings.append({
            "symbol": symbol,
            "source": source,
            "net_amount": -net,   # positive = you hold/received
            "is_currency": len(symbol) <= 3,  # EUR, USD vs SUSW, VWRA
        })
    
    return render(request, "expenses/portfolio.html", {"holdings": holdings})
```

#### 2. `backend/expenses/urls.py` — add URL

```python
path("portfolio/", views.portfolio_view, name="portfolio"),
```

#### 3. `backend/expenses/templates/expenses/portfolio.html` — new template

Simple table showing:
- Symbol / sub-account name
- Net holding (shares or currency amount)
- Type label (Security / Currency)
- Link to transactions for that source

```html
{% extends "base.html" %}
{% block content %}
<h1>Portfolio</h1>
<table>
  <thead>
    <tr><th>Asset</th><th>Holdings</th><th>Type</th></tr>
  </thead>
  <tbody>
    {% for h in holdings %}
    <tr>
      <td>{{ h.symbol }}</td>
      <td>{{ h.net_amount|floatformat:4 }}</td>
      <td>{% if h.is_currency %}Currency{% else %}Security{% endif %}</td>
    </tr>
    {% empty %}
    <tr><td colspan="3">No IBKR holdings tracked yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Add a link to the portfolio view in the navigation (in `base.html` or the manage nav).

### Success Criteria

#### Automated Verification
- [ ] URL resolves: `python manage.py check`
- [ ] Template renders without error with an empty holdings list

#### Manual Verification
- [ ] After processing a BUY for SUSW, portfolio shows SUSW with correct share count
- [ ] After processing a SELL for SUSW, share count decreases
- [ ] Currency conversions show in ibkr:EUR / ibkr:USD rows
- [ ] Page is linked from the main navigation

---

## Phase 4: Auto-create ibkr:USD Counterpart for Bank Transfer Emails

### Overview
Bank emails (e.g., Chase "BILL PAYMENT: INTERACTIVE BROKERS") are parsed into regular `Transaction` records. The ingestion pipeline should automatically detect IBKR deposits and create the paired virtual deposit into `ibkr:USD` — no manual action required.

Detection: if description contains "INTERACTIVE BROKERS" (case-insensitive), create the counterpart automatically in `_create_transaction()`.

### Changes Required

#### 1. `backend/expenses/email_ingest.py` — add helper + call from `_create_transaction()`

```python
_IBKR_DEPOSIT_MARKER = "interactive brokers"

def _maybe_create_ibkr_deposit_counterpart(user, tx: Tx) -> None:
    """If a bank transaction is an IBKR deposit, auto-create the ibkr:USD credit leg."""
    if _IBKR_DEPOSIT_MARKER not in tx.description.lower():
        return
    if tx.paired_transaction_id or tx.pair.exists():
        return  # already paired
    Tx.objects.create(
        user=user,
        date=tx.date,
        description=tx.description,
        amount=-tx.amount,   # opposite sign: money received into ibkr:USD
        currency=tx.currency,
        source=_get_or_create_source(user, "ibkr:USD"),
        status="confirmed",
        is_virtual=True,
        paired_transaction=tx,
        comments=f"Auto-created IBKR deposit counterpart for tx #{tx.pk}",
    )
    logger.info("✅ Created ibkr:USD deposit counterpart for tx id=%s", tx.pk)
```

Call it at the end of `_create_transaction()`, after `tx` is saved.

### Success Criteria

#### Automated Verification
- [ ] A "BILL PAYMENT: INTERACTIVE BROKERS" email produces 2 transactions: the bank tx + a virtual ibkr:USD credit
- [ ] A normal bank email (non-IBKR) produces only 1 transaction

#### Manual Verification
- [ ] Process the IBKR bill payment email → portfolio ibkr:USD row shows the deposited amount

---

## Testing Strategy

### Unit Tests (add to `expenses/tests/`)
- `test_ibkr_security_buy_creates_paired_transactions` — assert 2 transactions, 1 stock, sources = ibkr:USD + ibkr:SUSW
- `test_ibkr_forex_buy_creates_paired_transactions_no_stock` — assert 2 transactions, 0 stocks
- `test_ibkr_sell_signs_are_correct` — cash in (negative USD tx), shares out (positive SUSW tx)
- `test_portfolio_view_returns_200` — smoke test authenticated access
- `test_portfolio_net_holdings_correct` — buy then sell, verify net
- `test_ibkr_bank_deposit_creates_counterpart` — bank email with "INTERACTIVE BROKERS" → 2 transactions
- `test_non_ibkr_bank_email_no_counterpart` — normal bank email → 1 transaction only

### Manual Testing Steps
1. Trigger IBKR email for a security purchase → check `/transactions/` and `/portfolio/`
2. Trigger IBKR email for a forex trade → verify no Stock record in admin
3. Send duplicate email → verify goes to PendingTransaction, no double-counting in portfolio
4. Process bank "BILL PAYMENT: INTERACTIVE BROKERS" email → verify ibkr:USD counterpart created automatically

## Migration Notes

Existing `Transaction` records keep `is_virtual=False` (default), `paired_transaction=NULL`. Existing `Stock` records remain linked to their original single transaction. The portfolio view will only show holdings from transactions created after this change goes live, until a manual backfill is run later.

## References

- `backend/expenses/email_ingest.py:176` — `_process_ibkr_trade()`
- `backend/expenses/email_parsers/ibkr.py` — parser (preserves dots in symbols)
- `backend/expenses/models.py:237` — `Transaction` model
- `backend/expenses/models.py:371` — `Stock` model
