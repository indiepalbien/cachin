"""Tests for the expenses app."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from .models import Budget, BudgetGroup, Category, Transaction, UserProfile
from .views import _amortization_covers_month, get_category_expenses

User = get_user_model()


class AmortizationCoverageTests(TestCase):
    """Unit tests for _amortization_covers_month helper."""

    def _covers(self, start, months, year, month):
        return _amortization_covers_month(
            datetime.date.fromisoformat(start), months, year, month
        )

    def test_covers_first_month(self):
        self.assertTrue(self._covers("2026-04-01", 3, 2026, 4))

    def test_covers_middle_month(self):
        self.assertTrue(self._covers("2026-04-01", 3, 2026, 5))

    def test_covers_last_month(self):
        self.assertTrue(self._covers("2026-04-01", 3, 2026, 6))

    def test_does_not_cover_month_after_window(self):
        self.assertFalse(self._covers("2026-04-01", 3, 2026, 7))

    def test_does_not_cover_month_before_window(self):
        self.assertFalse(self._covers("2026-04-01", 3, 2026, 3))

    def test_single_month_window(self):
        self.assertTrue(self._covers("2026-04-15", 1, 2026, 4))
        self.assertFalse(self._covers("2026-04-15", 1, 2026, 5))

    def test_crosses_year_boundary(self):
        # 10 months from April 2026 → April-Jan, ends Feb 2027 (exclusive)
        self.assertTrue(self._covers("2026-04-01", 10, 2026, 4))
        self.assertTrue(self._covers("2026-04-01", 10, 2027, 1))
        self.assertFalse(self._covers("2026-04-01", 10, 2027, 2))

    def test_start_date_mid_month_is_normalized(self):
        # Start date on day 15 should normalize to first of that month
        self.assertTrue(self._covers("2026-04-15", 2, 2026, 4))
        self.assertTrue(self._covers("2026-04-15", 2, 2026, 5))
        self.assertFalse(self._covers("2026-04-15", 2, 2026, 6))


class GetCategoryExpensesTests(TestCase):
    """Integration tests for get_category_expenses with amortization."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.cat = Category.objects.create(user=self.user, name="Alquiler", counts_to_total=True)

    def _make_tx(self, amount, date, amortize_months=None, amortize_start_date=None, category=None, is_reimbursable=False):
        return Transaction.objects.create(
            user=self.user,
            date=datetime.date.fromisoformat(date),
            description="Test",
            amount=Decimal(str(amount)),
            currency="USD",
            category=category or self.cat,
            amortize_months=amortize_months,
            amortize_start_date=datetime.date.fromisoformat(amortize_start_date) if amortize_start_date else None,
            is_reimbursable=is_reimbursable,
        )

    def _month_qs(self, year, month):
        first = datetime.date(year, month, 1)
        ny = year + (month // 12)
        nm = (month % 12) + 1
        next_first = datetime.date(ny, nm, 1)
        return Transaction.objects.filter(
            user=self.user, date__gte=first, date__lt=next_first
        ).exclude(amount=0)

    # --- non-amortized transactions ---

    def test_non_amortized_uses_full_amount(self):
        self._make_tx(100, "2026-04-10")
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp[0]["total"], "100.00")
        self.assertEqual(subtotals["USD"], "100.00")

    # --- amortized: transaction dated in the viewed month ---

    def test_amortized_tx_in_same_month_shows_fraction(self):
        self._make_tx(1000, "2026-04-01", amortize_months=10, amortize_start_date="2026-04-01")
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp[0]["total"], "100.00")
        self.assertEqual(subtotals["USD"], "100.00")

    def test_amortized_tx_not_shown_outside_window(self):
        # 3-month window Apr-Jun; July should be 0
        self._make_tx(300, "2026-04-01", amortize_months=3, amortize_start_date="2026-04-01")
        qs = self._month_qs(2026, 7)  # July — outside window
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=7)
        self.assertEqual(cat_exp, [])
        self.assertEqual(subtotals, {})

    # --- amortized: transaction dated in a different month ---

    def test_amortized_tx_from_past_month_appears_in_later_month(self):
        # Paid $1000 in April, amortized over 10 months starting April
        # Should appear as $100 in September
        self._make_tx(1000, "2026-04-01", amortize_months=10, amortize_start_date="2026-04-01")
        qs = self._month_qs(2026, 9)  # September has no transactions dated in it
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=9)
        self.assertEqual(len(cat_exp), 1)
        self.assertEqual(cat_exp[0]["total"], "100.00")
        self.assertEqual(subtotals["USD"], "100.00")

    def test_amortized_tx_from_past_month_not_shown_after_window(self):
        # 3-month window Apr-Jun; July gets nothing from this transaction
        self._make_tx(300, "2026-04-01", amortize_months=3, amortize_start_date="2026-04-01")
        qs = self._month_qs(2026, 7)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=7)
        self.assertEqual(cat_exp, [])

    def test_amortized_tx_not_double_counted_in_origin_month(self):
        # Transaction dated in April, amortized starting April
        # April month_qs already has it; extra_qs should not add it again
        self._make_tx(600, "2026-04-01", amortize_months=3, amortize_start_date="2026-04-01")
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp[0]["total"], "200.00")  # 600/3, not 400

    # --- amortize_start_date later than transaction date ---

    def test_amortized_tx_with_future_start_date_not_shown_in_origin_month(self):
        # Pay in April, but amortize starting May — April should show 0
        self._make_tx(500, "2026-04-01", amortize_months=5, amortize_start_date="2026-05-01")
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp, [])

    def test_amortized_tx_with_future_start_date_shown_from_start_month(self):
        self._make_tx(500, "2026-04-01", amortize_months=5, amortize_start_date="2026-05-01")
        qs = self._month_qs(2026, 5)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=5)
        self.assertEqual(cat_exp[0]["total"], "100.00")

    # --- multiple amortized transactions ---

    def test_multiple_amortized_transactions_accumulate(self):
        # Two amortized transactions, both covering June
        self._make_tx(600, "2026-04-01", amortize_months=6, amortize_start_date="2026-04-01")  # 100/mo
        self._make_tx(300, "2026-05-01", amortize_months=3, amortize_start_date="2026-05-01")  # 100/mo
        qs = self._month_qs(2026, 6)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=6)
        self.assertEqual(cat_exp[0]["total"], "200.00")
        self.assertEqual(subtotals["USD"], "200.00")

    # --- no sel_year/sel_month (backward compatibility) ---

    def test_no_sel_year_month_still_divides_amortized(self):
        # Without sel_year/sel_month, the window check is skipped but division still applies
        self._make_tx(1000, "2026-04-01", amortize_months=10)
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs)
        self.assertEqual(cat_exp[0]["total"], "100.00")

    # --- reimbursable transactions ---

    def test_reimbursable_excluded_from_category_totals(self):
        self._make_tx(500, "2026-04-01", is_reimbursable=True)
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp, [])
        self.assertEqual(subtotals, {})

    def test_reimbursable_excluded_from_subtotals_even_with_normal_tx(self):
        self._make_tx(100, "2026-04-01")
        self._make_tx(500, "2026-04-01", is_reimbursable=True)
        qs = self._month_qs(2026, 4)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=4)
        self.assertEqual(cat_exp[0]["total"], "100.00")
        self.assertEqual(subtotals["USD"], "100.00")

    def test_reimbursable_amortized_from_past_month_excluded(self):
        # An amortized reimbursable tx from April should not appear in September
        self._make_tx(1000, "2026-04-01", amortize_months=10, amortize_start_date="2026-04-01", is_reimbursable=True)
        qs = self._month_qs(2026, 9)
        cat_exp, _, subtotals = get_category_expenses(self.user, qs, sel_year=2026, sel_month=9)
        self.assertEqual(cat_exp, [])


class BudgetExpensesTests(TestCase):
    """Tests for budget spent calculation with amortization and reimbursable."""

    def setUp(self):
        self.user = User.objects.create_user(username="budgetuser", password="pass")
        self.cat = Category.objects.create(user=self.user, name="Living", counts_to_total=True)
        self.group = BudgetGroup.objects.create(user=self.user, name="mensual", currency="USD")
        self.budget = Budget.objects.create(
            user=self.user,
            group=self.group,
            effective_date=datetime.date(2026, 1, 1),
            amount=Decimal("1000.00"),
        )
        self.budget.categories.add(self.cat)

    def _make_tx(self, amount, date, amortize_months=None, amortize_start_date=None, is_reimbursable=False):
        return Transaction.objects.create(
            user=self.user,
            date=datetime.date.fromisoformat(date),
            description="Test",
            amount=Decimal(str(amount)),
            currency="USD",
            amount_usd=Decimal(str(amount)),
            category=self.cat,
            amortize_months=amortize_months,
            amortize_start_date=datetime.date.fromisoformat(amortize_start_date) if amortize_start_date else None,
            is_reimbursable=is_reimbursable,
        )

    def _call_api(self, year, month):
        from django.test import RequestFactory
        from .views import api_budget_expenses
        import django_htmx  # may not be available; use plain request
        factory = RequestFactory()
        request = factory.get(f"/api/budget-expenses/?m={year:04d}-{month:02d}")
        request.user = self.user
        request.htmx = False
        response = api_budget_expenses(request)
        import json
        return json.loads(response.content)

    def test_normal_tx_counted_in_budget(self):
        self._make_tx(200, "2026-04-10")
        data = self._call_api(2026, 4)
        row = data["budget_rows"][0]
        self.assertEqual(row["spent"], "200.00")

    def test_amortized_tx_uses_fraction_in_budget(self):
        self._make_tx(1000, "2026-04-01", amortize_months=10, amortize_start_date="2026-04-01")
        data = self._call_api(2026, 4)
        self.assertEqual(data["budget_rows"][0]["spent"], "100.00")

    def test_amortized_tx_from_past_month_appears_in_budget(self):
        self._make_tx(1000, "2026-04-01", amortize_months=10, amortize_start_date="2026-04-01")
        data = self._call_api(2026, 9)
        self.assertEqual(data["budget_rows"][0]["spent"], "100.00")

    def test_amortized_tx_not_counted_after_window(self):
        # 3-month window Apr-Jun; July should show 0
        self._make_tx(300, "2026-04-01", amortize_months=3, amortize_start_date="2026-04-01")
        data = self._call_api(2026, 7)
        self.assertEqual(data["budget_rows"][0]["spent"], "0.00")

    def test_reimbursable_excluded_from_budget(self):
        self._make_tx(500, "2026-04-01", is_reimbursable=True)
        data = self._call_api(2026, 4)
        self.assertEqual(data["budget_rows"][0]["spent"], "0.00")

    def test_reimbursable_excluded_budget_alongside_normal(self):
        self._make_tx(200, "2026-04-01")
        self._make_tx(500, "2026-04-01", is_reimbursable=True)
        data = self._call_api(2026, 4)
        self.assertEqual(data["budget_rows"][0]["spent"], "200.00")


class TransactionListAmortizationTests(TestCase):
    """Tests that TransactionListView includes amortized transactions from other months."""

    def setUp(self):
        self.user = User.objects.create_user(username="txlistuser", password="pass")
        UserProfile.objects.update_or_create(user=self.user, defaults={"onboarding_step": 0})
        self.client = Client()
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.cat = Category.objects.create(user=self.user, name="rent", counts_to_total=True)

    def _make_tx(self, amount, date_str, **kwargs):
        asd = kwargs.pop("amortize_start_date", None)
        if asd:
            asd = datetime.date.fromisoformat(asd)
        return Transaction.objects.create(
            user=self.user,
            amount=Decimal(str(amount)),
            currency="USD",
            date=datetime.date.fromisoformat(date_str),
            description="test",
            category=self.cat,
            amortize_start_date=asd,
            **kwargs,
        )

    def _get_ids(self, month_str):
        url = reverse("expenses:manage_transactions")
        resp = self.client.get(url, {"month": month_str})
        self.assertEqual(resp.status_code, 200)
        return {tx.id for tx in resp.context["page_obj"]}

    def test_amortized_tx_from_other_month_appears(self):
        tx = self._make_tx(1200, "2026-01-15", amortize_months=12, amortize_start_date="2026-01-01")
        ids = self._get_ids("2026-05")
        self.assertIn(tx.id, ids)

    def test_amortized_tx_not_shown_after_window(self):
        tx = self._make_tx(300, "2026-01-01", amortize_months=3, amortize_start_date="2026-01-01")
        ids = self._get_ids("2026-05")
        self.assertNotIn(tx.id, ids)

    def test_normal_tx_still_shows_in_its_month(self):
        tx = self._make_tx(100, "2026-05-10")
        ids = self._get_ids("2026-05")
        self.assertIn(tx.id, ids)

    def test_display_amount_is_fraction_for_amortized(self):
        self._make_tx(1200, "2026-01-15", amortize_months=12, amortize_start_date="2026-01-01")
        url = reverse("expenses:manage_transactions")
        resp = self.client.get(url, {"month": "2026-05"})
        tx = list(resp.context["page_obj"])[0]
        self.assertEqual(tx.display_amount, Decimal("100.00"))
        self.assertEqual(tx.amortize_info, "1/12")

    def test_display_amount_is_full_for_normal(self):
        self._make_tx(500, "2026-05-10")
        url = reverse("expenses:manage_transactions")
        resp = self.client.get(url, {"month": "2026-05"})
        tx = list(resp.context["page_obj"])[0]
        self.assertEqual(tx.display_amount, Decimal("500"))
        self.assertEqual(tx.amortize_info, "")
