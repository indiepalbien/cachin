"""Temporary: debug why rent shows $511 instead of $411."""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Debug rent category expense calculation"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=7)
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=4)

    def handle(self, *args, **options):
        from expenses.models import Category, Transaction

        user_id = options["user_id"]
        year = options["year"]
        month = options["month"]

        cat = Category.objects.get(user_id=user_id, name__iexact="rent")
        self.stdout.write(f"Category: {cat.name} (id={cat.id})\n")

        # ALL rent txs ever
        all_txs = Transaction.objects.filter(
            user_id=user_id, category=cat, is_virtual=False
        ).order_by("-date")
        self.stdout.write("\n=== ALL rent transactions ===\n")
        for t in all_txs:
            self.stdout.write(
                f"  id={t.id} date={t.date} amount={t.amount} "
                f"reimb={t.reimbursable} amort_months={t.amortize_months} "
                f"amort_start={t.amortize_start_date} "
                f"desc={t.description[:50]}\n"
            )

        # Simulate get_category_expenses for the month
        sel_first = datetime.date(year, month, 1)

        # Step A: in-month non-reimbursable
        in_month = Transaction.objects.filter(
            user_id=user_id, category=cat, is_virtual=False,
            date__year=year, date__month=month,
        ).exclude(is_reimbursable=True)

        self.stdout.write(f"\n=== Step A: in-month {year}-{month:02d} ===\n")
        step_a = Decimal("0")
        for t in in_month:
            if t.amortize_months:
                eff = (t.amount / t.amortize_months).quantize(Decimal("0.01"))
            else:
                eff = t.amount
            step_a += eff
            self.stdout.write(
                f"  id={t.id} amount={t.amount} amort={t.amortize_months} "
                f"effective={eff}\n"
            )
        self.stdout.write(f"  Step A subtotal: {step_a}\n")

        # Step B: cross-month amortized covering this month
        cross = Transaction.objects.filter(
            user_id=user_id, category=cat, is_virtual=False,
            is_reimbursable=False,
        ).exclude(
            amortize_months__isnull=True
        ).exclude(
            date__year=year, date__month=month
        )

        self.stdout.write(f"\n=== Step B: cross-month amortized ===\n")
        step_b = Decimal("0")
        for t in cross:
            start = (t.amortize_start_date or t.date).replace(day=1)
            total_m = (start.year * 12 + start.month) + t.amortize_months
            ey, em = divmod(total_m - 1, 12)
            end_first = datetime.date(ey, em + 1, 1)
            covers = sel_first >= start and sel_first < end_first
            eff = (t.amount / t.amortize_months).quantize(Decimal("0.01")) if covers else Decimal("0")
            if covers:
                step_b += eff
            self.stdout.write(
                f"  id={t.id} date={t.date} amount={t.amount} "
                f"amort={t.amortize_months} start={start} end={end_first} "
                f"covers={covers} effective={eff}\n"
            )
        self.stdout.write(f"  Step B subtotal: {step_b}\n")

        self.stdout.write(f"\n=== GRAND TOTAL: {step_a + step_b} ===\n")

        # Also check: reimbursable txs in this category this month
        reimb = Transaction.objects.filter(
            user_id=user_id, category=cat, is_virtual=False,
            date__year=year, date__month=month,
            is_reimbursable=True,
        )
        self.stdout.write(f"\n=== Reimbursable txs (excluded) ===\n")
        for t in reimb:
            self.stdout.write(
                f"  id={t.id} date={t.date} amount={t.amount} "
                f"desc={t.description[:50]}\n"
            )
