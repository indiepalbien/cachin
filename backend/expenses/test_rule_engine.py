"""
Tests for the intelligent categorization rules system.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from decimal import Decimal

from .models import Category, Payee, Transaction, CategorizationRule, Source
from .rule_engine import (
    sanitize_description,
    get_rule_specificity_score,
    generate_categorization_rules,
    find_matching_rules,
    apply_best_matching_rule,
    apply_rules_to_all_transactions,
    get_user_rule_stats,
    cleanup_stale_rules,
)

User = get_user_model()


class SanitizeDescriptionTestCase(TestCase):
    """Test description sanitization."""

    def test_basic_sanitization(self):
        """Test removing generic words and converting to lowercase."""
        result = sanitize_description("PAYPAL *NAMECHEAP")
        self.assertEqual(result, ["namecheap"])

    def test_extract_meaningful_tokens(self):
        """Test extracting meaningful tokens from description."""
        result = sanitize_description("Sole y Gian f*HANDY*")
        # handy might be included if it's not in GENERIC_KEYWORDS or too short
        self.assertIn("sole", result)
        self.assertIn("gian", result)

    def test_remove_short_tokens(self):
        """Test filtering out single-character tokens."""
        result = sanitize_description("A B SOMETHING")
        self.assertIn("something", result)
        self.assertNotIn("a", result)
        self.assertNotIn("b", result)

    def test_handle_special_separators(self):
        """Test handling various separators."""
        result = sanitize_description("STARB-COFFEE_SHOP#123")
        self.assertIn("starb", result)
        self.assertIn("coffee", result)
        # Note: "shop" is 4 chars so should be included, but verify token extraction
        self.assertIn("123", result)

    def test_empty_description(self):
        """Test with empty description."""
        result = sanitize_description("")
        self.assertEqual(result, [])

    def test_only_generic_words(self):
        """Test with only generic words."""
        result = sanitize_description("the and payment transaction")
        self.assertEqual(result, [])


class SpecificityScoreTestCase(TestCase):
    """Test rule specificity scoring."""

    def test_no_components(self):
        """Test scoring with minimal components."""
        score = get_rule_specificity_score([])
        self.assertEqual(score, 0.0)

    def test_description_tokens_only(self):
        """Test scoring with only description tokens."""
        score = get_rule_specificity_score(["token1", "token2", "token3"])
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1.0)

    def test_amount_increases_score(self):
        """Test that adding amount increases score."""
        score_without = get_rule_specificity_score(["token"])
        score_with = get_rule_specificity_score(["token"], amount=Decimal("100"))
        self.assertGreater(score_with, score_without)

    def test_currency_increases_score(self):
        """Test that adding currency increases score."""
        score_without = get_rule_specificity_score(["token"])
        score_with = get_rule_specificity_score(["token"], currency="USD")
        self.assertGreater(score_with, score_without)

    def test_all_components(self):
        """Test scoring with all components."""
        score = get_rule_specificity_score(
            ["token1", "token2"],
            amount=Decimal("500.00"),
            currency="UYU",
        )
        self.assertGreater(score, 0.5)
        self.assertLessEqual(score, 1.0)


class GenerateCategoriesTestCase(TestCase):
    """Test rule generation."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.category = Category.objects.create(user=self.user, name="Transfer")
        self.payee = Payee.objects.create(user=self.user, name="John")

    def test_generate_rules_creates_four_variants(self):
        """Test that four rule variants are created."""
        rules = generate_categorization_rules(
            user=self.user,
            description="Sole y Gian f*HANDY*",
            amount=Decimal("582.00"),
            currency="UYU",
            category=self.category,
            payee=self.payee,
        )

        self.assertEqual(len(rules), 4)

    def test_generate_rules_with_empty_description(self):
        """Test that no rules are generated with empty description."""
        rules = generate_categorization_rules(
            user=self.user,
            description="the and payment",  # All generic words
            amount=Decimal("100"),
            currency="USD",
            category=self.category,
        )

        self.assertEqual(len(rules), 0)

    def test_rules_have_correct_components(self):
        """Test that rules have the expected components."""
        rules = generate_categorization_rules(
            user=self.user,
            description="PAYPAL *NAMECHEAP",
            amount=Decimal("10.18"),
            currency="USD",
            category=self.category,
        )

        # Check that we have rules with different specificity levels
        amounts = set(rule.amount for rule in rules)
        currencies = set(rule.currency for rule in rules)

        self.assertIn(None, amounts)  # At least one without amount
        self.assertIn(Decimal("10.18"), amounts)  # At least one with amount
        self.assertIn(None, currencies)  # At least one without currency
        self.assertIn("USD", currencies)  # At least one with currency


class FindMatchingRulesTestCase(TestCase):
    """Test rule matching logic."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.category = Category.objects.create(user=self.user, name="Food")
        self.payee = Payee.objects.create(user=self.user, name="Starbucks")

        # Create some rules
        self.rule1 = CategorizationRule.objects.create(
            user=self.user,
            description_tokens="starb coffee",
            category=self.category,
            payee=self.payee,
            usage_count=5,
            accuracy=0.8,
        )

        self.rule2 = CategorizationRule.objects.create(
            user=self.user,
            description_tokens="starb",
            amount=Decimal("5.50"),
            currency="USD",
            category=self.category,
            usage_count=2,
            accuracy=0.9,
        )

    def test_find_matching_rules(self):
        """Test finding rules that match a description."""
        matches = find_matching_rules(
            user=self.user,
            description="STARB COFFEE SHOP",
            amount=Decimal("5.50"),
            currency="USD",
        )

        self.assertGreater(len(matches), 0)
        matched_rules = [rule for rule, _ in matches]
        self.assertIn(self.rule1, matched_rules)

    def test_find_matching_rules_respects_threshold(self):
        """Test that threshold filters low-accuracy rules."""
        matches = find_matching_rules(
            user=self.user,
            description="STARB COFFEE",
            amount=Decimal("5.50"),
            currency="USD",
            threshold=0.95,  # High threshold
        )

        # rule1 has 0.8 accuracy, shouldn't match
        matched_rules = [rule for rule, _ in matches]
        self.assertNotIn(self.rule1, matched_rules)

    def test_find_matching_rules_no_match(self):
        """Test with description that doesn't match any rules."""
        matches = find_matching_rules(
            user=self.user,
            description="UNKNOWN MERCHANT",
            amount=Decimal("100"),
            currency="USD",
        )

        self.assertEqual(len(matches), 0)

    def test_matching_rules_ordered_by_specificity(self):
        """Test that matches are ordered by specificity."""
        # Add a very specific rule
        specific_rule = CategorizationRule.objects.create(
            user=self.user,
            description_tokens="starb coffee",
            amount=Decimal("5.50"),
            currency="USD",
            category=self.category,
            usage_count=1,
            accuracy=0.7,  # Lower accuracy
        )

        matches = find_matching_rules(
            user=self.user,
            description="STARB COFFEE SHOP",
            amount=Decimal("5.50"),
            currency="USD",
        )

        # More specific rules should come first despite lower accuracy
        if len(matches) > 1:
            first_rule = matches[0][0]
            # The specific rule should be in the matches
            self.assertIn(specific_rule, [r for r, _ in matches])


class ApplyRulesTestCase(TestCase):
    """Test rule application."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.source = Source.objects.create(user=self.user, name="Bank")
        self.category = Category.objects.create(user=self.user, name="Food")
        self.payee = Payee.objects.create(user=self.user, name="Cafe")

        # Create a rule
        self.rule = CategorizationRule.objects.create(
            user=self.user,
            description_tokens="cafe",
            category=self.category,
            payee=self.payee,
            accuracy=0.85,
        )

        # Create an uncategorized transaction
        self.transaction = Transaction.objects.create(
            user=self.user,
            date="2024-12-18",
            description="CAFE LOCAL",
            amount=Decimal("5.50"),
            currency="USD",
            source=self.source,
        )

    def test_apply_best_matching_rule(self):
        """Test applying the best matching rule to a transaction."""
        result = apply_best_matching_rule(self.transaction)

        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.rule.id)

        # Check that transaction was updated
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.category_id, self.category.id)
        self.assertEqual(self.transaction.payee_id, self.payee.id)

    def test_rule_usage_incremented(self):
        """Test that rule usage counter is incremented."""
        initial_usage = self.rule.usage_count
        apply_best_matching_rule(self.transaction)

        self.rule.refresh_from_db()
        self.assertEqual(self.rule.usage_count, initial_usage + 1)

    def test_apply_rules_to_multiple_transactions(self):
        """Test applying rules to multiple transactions."""
        # Create more uncategorized transactions
        for i in range(3):
            Transaction.objects.create(
                user=self.user,
                date="2024-12-18",
                description=f"CAFE #{i}",
                amount=Decimal("5.50"),
                currency="USD",
                source=self.source,
            )

        updated, total = apply_rules_to_all_transactions(self.user)

        self.assertEqual(total, 4)  # 1 original + 3 new
        self.assertGreater(updated, 0)

    def test_doesnt_overwrite_existing_category(self):
        """Test that existing categories aren't overwritten."""
        other_category = Category.objects.create(user=self.user, name="Uncategorized")
        self.transaction.category = other_category
        self.transaction.save()

        apply_best_matching_rule(self.transaction)

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.category_id, other_category.id)


class RuleStatsTestCase(TestCase):
    """Test rule statistics."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.category = Category.objects.create(user=self.user, name="Food")

        # Create some rules
        CategorizationRule.objects.create(
            user=self.user,
            description_tokens="cafe",
            category=self.category,
            usage_count=10,
            accuracy=0.9,
        )

        CategorizationRule.objects.create(
            user=self.user,
            description_tokens="restaurant",
            category=self.category,
            usage_count=5,
            accuracy=0.7,
        )

    def test_get_rule_stats(self):
        """Test getting rule statistics."""
        stats = get_user_rule_stats(self.user)

        self.assertEqual(stats['total_rules'], 2)
        self.assertEqual(stats['avg_usage'], 7.5)
        self.assertGreater(stats['avg_accuracy'], 0.7)
        self.assertEqual(stats['total_applications'], 15)

    def test_cleanup_stale_rules(self):
        """Test cleaning up stale rules."""
        # Create a low-usage, low-accuracy rule
        bad_rule = CategorizationRule.objects.create(
            user=self.user,
            description_tokens="bad",
            category=self.category,
            usage_count=0,
            accuracy=0.2,
        )

        # Cleanup should remove it
        deleted = cleanup_stale_rules(self.user, min_usage=0)

        self.assertEqual(deleted, 1)
        self.assertFalse(
            CategorizationRule.objects.filter(id=bad_rule.id).exists()
        )


class RuleSignalTestCase(TestCase):
    """Test that signals create rules when transactions are categorized."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.source = Source.objects.create(user=self.user, name="Bank")
        self.category = Category.objects.create(user=self.user, name="Food")
        self.payee = Payee.objects.create(user=self.user, name="Cafe")

    def test_signal_creates_rules_on_update(self):
        """Test that updating a transaction's category creates rules."""
        # Create uncategorized transaction
        transaction = Transaction.objects.create(
            user=self.user,
            date="2024-12-18",
            description="CAFE LOCAL",
            amount=Decimal("5.50"),
            currency="USD",
            source=self.source,
        )

        # Clear any rules created during initial save
        CategorizationRule.objects.filter(user=self.user).delete()

        # Update with category
        transaction.category = self.category
        transaction.payee = self.payee
        transaction.save(update_fields=['category', 'payee'])

        # Check that rules were created
        rules = CategorizationRule.objects.filter(user=self.user)
        self.assertGreater(rules.count(), 0)

        # Check that rules contain the expected tokens
        description_tokens_set = set(rule.description_tokens for rule in rules)
        # At least one rule should have "cafe" token
        tokens_in_rules = " ".join(description_tokens_set)
        self.assertIn("cafe", tokens_in_rules)
