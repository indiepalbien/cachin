"""
Test for source totals calculation with USD conversion and exclude categories.

This test verifies the per-source totals calculation respects the
counts_to_total flag and properly converts currencies to USD.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from decimal import Decimal
import datetime

from .models import Category, Source, Transaction, DefaultExchangeRate, UserPreferences
from .views import api_source_expenses

User = get_user_model()


class SourceTotalsWithUSDConversionTestCase(TestCase):
    """Test source totals calculation with USD conversion and category exclusion."""

    def setUp(self):
        """Create test data with multiple categories and currencies."""
        self.user = User.objects.create_user(username="testuser", password="pass")

        # Set user preference to convert to USD
        UserPreferences.objects.create(
            user=self.user,
            convert_expenses_to_usd=True
        )

        # Create default exchange rates
        DefaultExchangeRate.objects.create(currency="USD", rate=Decimal("1.00"))
        DefaultExchangeRate.objects.create(currency="EUR", rate=Decimal("1.10"))  # 1 EUR = 1.10 USD
        DefaultExchangeRate.objects.create(currency="UYU", rate=Decimal("0.025"))  # 1 UYU = 0.025 USD

        # Create a source
        self.source = Source.objects.create(user=self.user, name="Credit Card")

        # Create 3 categories
        self.cat_food = Category.objects.create(
            user=self.user,
            name="Food",
            counts_to_total=True  # Should be included
        )

        self.cat_shopping = Category.objects.create(
            user=self.user,
            name="Shopping",
            counts_to_total=True  # Should be included
        )

        self.cat_transfer = Category.objects.create(
            user=self.user,
            name="Transfer",
            counts_to_total=False  # Should NOT be included in source totals
        )

        # Create transactions for current month (December 2024)
        # Food: 100 EUR (should convert to ~110 USD)
        Transaction.objects.create(
            user=self.user,
            date=datetime.date(2024, 12, 10),
            description="Restaurant",
            amount=Decimal("100.00"),
            currency="EUR",
            source=self.source,
            category=self.cat_food,
        )

        # Shopping: 2000 UYU (should convert to ~50 USD)
        Transaction.objects.create(
            user=self.user,
            date=datetime.date(2024, 12, 12),
            description="Clothes",
            amount=Decimal("2000.00"),
            currency="UYU",
            source=self.source,
            category=self.cat_shopping,
        )

        # Transfer: 500 USD (should NOT be included because counts_to_total=False)
        Transaction.objects.create(
            user=self.user,
            date=datetime.date(2024, 12, 15),
            description="Transfer to savings",
            amount=Decimal("500.00"),
            currency="USD",
            source=self.source,
            category=self.cat_transfer,
        )

    def test_source_totals_with_usd_conversion_and_exclude(self):
        """
        Test that source totals:
        1. Convert all amounts to USD
        2. Exclude categories where counts_to_total=False
        3. Sum correctly

        Expected calculation:
        - Food: 100 EUR → 110 USD (included)
        - Shopping: 2000 UYU → 50 USD (included)
        - Transfer: 500 USD (EXCLUDED due to counts_to_total=False)
        - Total: 110 + 50 = 160 USD
        """
        factory = RequestFactory()
        request = factory.get('/api/source-expenses/?m=2024-12')
        request.user = self.user
        request.htmx = False

        response = api_source_expenses(request)
        import json
        data = json.loads(response.content)

        # Verify we got results
        self.assertIn('src_expenses', data)
        self.assertEqual(len(data['src_expenses']), 1, "Should have 1 source")

        src_data = data['src_expenses'][0]
        self.assertEqual(src_data['source'], 'Credit Card')
        self.assertEqual(src_data['currency'], 'USD')

        actual_total = Decimal(src_data['total'])

        # Expected calculation:
        # Food: 100 EUR * 1.10 = 110 USD
        # Shopping: 2000 UYU * 0.025 = 50 USD
        # Transfer: 500 USD (EXCLUDED)
        # Total: 110 + 50 = 160 USD
        expected_total = Decimal('160.00')

        print(f"\n=== SOURCE TOTALS TEST ===")
        print(f"Transactions:")
        print(f"  1. Food: 100 EUR → ~110 USD (counts_to_total=True) ✓")
        print(f"  2. Shopping: 2000 UYU → ~50 USD (counts_to_total=True) ✓")
        print(f"  3. Transfer: 500 USD (counts_to_total=False) ✗ EXCLUDED")
        print(f"\nExpected total: {expected_total} USD")
        print(f"Actual total:   {actual_total} USD")
        print(f"Match: {actual_total == expected_total}")

        if actual_total != expected_total:
            print(f"\n⚠️  BUG DETECTED!")
            print(f"   Difference: {actual_total - expected_total} USD")
            if abs(actual_total - Decimal('660.00')) < Decimal('1.00'):
                print("   → Likely including Transfer (500 USD) when it shouldn't")
            elif abs(actual_total - expected_total) > Decimal('400.00'):
                print("   → Calculation appears significantly off")

        self.assertEqual(
            actual_total,
            expected_total,
            f"Source total should be 160 USD (excluding Transfer category), but got {actual_total} USD"
        )

    def test_source_totals_with_positive_and_negative_amounts(self):
        """
        Test that source totals correctly handle positive expenses and negative income/refunds.

        This verifies whether the code uses net calculation (keeps signs) or
        absolute values (sums all absolute amounts) as the old comments claimed.

        Expected behavior (based on category expenses implementation):
        - Keeps signs: positive for expenses, negative for income
        - Net calculation: $100 + (-$30) = $70
        """
        # Create new test user to avoid conflicts
        user2 = User.objects.create_user(username="testuser2", password="pass")
        UserPreferences.objects.create(user=user2, convert_expenses_to_usd=True)

        # Create source and category for this test
        source2 = Source.objects.create(user=user2, name="Test Card")
        cat2 = Category.objects.create(user=user2, name="Shopping", counts_to_total=True)

        # Add expense and refund in same source
        Transaction.objects.create(
            user=user2,
            date=datetime.date(2024, 12, 10),
            description="Purchase",
            amount=Decimal("100.00"),  # Positive = expense
            currency="USD",
            source=source2,
            category=cat2,
        )

        Transaction.objects.create(
            user=user2,
            date=datetime.date(2024, 12, 15),
            description="Refund",
            amount=Decimal("-30.00"),  # Negative = income/refund
            currency="USD",
            source=source2,
            category=cat2,
        )

        factory = RequestFactory()
        request = factory.get('/api/source-expenses/?m=2024-12')
        request.user = user2
        request.htmx = False

        response = api_source_expenses(request)
        import json
        data = json.loads(response.content)

        src_data = data['src_expenses'][0]
        actual_total = Decimal(src_data['total'])

        # Expected: net calculation (keeps signs)
        expected_net = Decimal('70.00')  # $100 + (-$30) = $70

        # If code used absolute values (as old comments claimed)
        expected_absolute = Decimal('130.00')  # |$100| + |-$30| = $130

        print(f"\n=== SIGN BEHAVIOR TEST ===")
        print(f"Transactions: +$100 (expense), -$30 (refund)")
        print(f"Actual total: ${actual_total}")
        print(f"Expected (net): ${expected_net}")
        print(f"Expected (absolute per old comments): ${expected_absolute}")
        print(f"Uses net calculation: {actual_total == expected_net}")
        print(f"Uses absolute values: {actual_total == expected_absolute}")

        if actual_total == expected_net:
            print(f"\n✓ CORRECT: Code keeps signs (net calculation)")
            print(f"  Old misleading comments have been fixed")
        elif actual_total == expected_absolute:
            print(f"\n✗ UNEXPECTED: Code uses absolute values (doesn't match category behavior)")
        else:
            print(f"\n✗ UNEXPECTED: Total is neither net nor absolute")

        # Assert expected behavior (should use net calculation like category expenses)
        self.assertEqual(
            actual_total,
            expected_net,
            f"Source totals should use net calculation (keeps signs), got {actual_total} instead of {expected_net}"
        )
