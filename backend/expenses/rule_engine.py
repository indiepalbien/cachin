"""
Intelligent categorization rule engine.

This module handles:
1. Sanitizing transaction descriptions
2. Generating categorization rules from user inputs
3. Finding and applying rules to transactions
4. Maintaining rule accuracy scores
"""

import re
from typing import List, Set, Tuple, Optional
from decimal import Decimal
from django.db import models
from django.db.models import Q
from .models import CategorizationRule, Transaction


# Generic words that don't provide useful categorization information
GENERIC_KEYWORDS = {
    # Payment processors
    'paypal', 'stripe', 'square', 'shopify', 'fastspring', '2checkout',
    # Banks
    'bank', 'banking', 'transfer', 'payment', 'deposit', 'withdrawal',
    # Generic actions
    'transaction', 'pago', 'compra', 'venta', 'order', 'purchase', 'sale',
    # Common words
    'the', 'a', 'an', 'to', 'from', 'and', 'or', 'of', 'in', 'on', 'at', 'by',
    'de', 'la', 'el', 'un', 'una', 'y', 'o', 'para', 'por', 'con', 'sin',
    # Separators and common patterns
    'ref', 'id', 'invoice', 'factura', 'ticket', 'trans', 'tx', 'via',
    # Merchant generics
    'merchant', 'vendor', 'store', 'shop', 'retail', 'online',
}

# Separators used to split description into tokens
TOKEN_SEPARATORS = r'[\s\-_*#@\.\,\(\)]+'


def sanitize_description(description: str) -> List[str]:
    """
    Sanitize a transaction description and extract meaningful tokens.
    
    Examples:
    - "Sole y Gian f*HANDY*" → ["sole", "gian"]
    - "PAYPAL *NAMECHEAP" → ["namecheap"]
    - "STARB ONLINE PAYMENT" → ["starb"]
    
    Args:
        description: Raw description from transaction
        
    Returns:
        List of sanitized, lowercase tokens
    """
    # Convert to lowercase and remove extra whitespace
    desc = description.lower().strip()
    
    # Split by separators
    tokens = re.split(TOKEN_SEPARATORS, desc)
    
    # Filter out empty strings, generic keywords, and short tokens
    filtered = [
        token for token in tokens
        if token and len(token) > 1 and token not in GENERIC_KEYWORDS
    ]
    
    return filtered


def get_rule_specificity_score(
    description_tokens: List[str],
    amount: Optional[Decimal] = None,
    currency: Optional[str] = None,
) -> float:
    """
    Calculate specificity score for a rule combination.
    
    More specific rules (with more tokens and exact amounts) score higher.
    This helps choose the best matching rule when multiple match.
    
    Args:
        description_tokens: Tokens from sanitized description
        amount: Transaction amount (if part of rule)
        currency: Currency code (if part of rule)
        
    Returns:
        Specificity score (0-1)
    """
    score = 0.0
    
    # Description tokens contribute base score
    if description_tokens:
        # More tokens = more specific
        score += min(0.5, len(description_tokens) * 0.15)
    
    # Amount adds specificity
    if amount:
        score += 0.25
    
    # Currency adds some specificity
    if currency:
        score += 0.15
    
    return min(1.0, score)


def generate_categorization_rules(
    user,
    description: str,
    amount: Decimal,
    currency: str,
    category=None,
    payee=None,
) -> List[CategorizationRule]:
    """
    Generate multiple rule variants for a categorized transaction.
    
    When a user categorizes a transaction, we create 4 rule variants:
    1. (description_tokens)
    2. (description_tokens, amount, currency)
    3. (description_tokens, currency)
    4. (description_tokens, amount)
    
    Each rule is stored separately so we can use the most specific match.
    
    Args:
        user: User who owns the rule
        description: Transaction description
        amount: Transaction amount
        currency: Currency code
        category: Assigned category
        payee: Assigned payee
        
    Returns:
        List of created CategorizationRule objects
    """
    tokens = sanitize_description(description)
    
    if not tokens:
        return []
    
    description_str = ' '.join(tokens)
    rules = []
    
    # Rule 1: Just description tokens
    rule1, _ = CategorizationRule.objects.get_or_create(
        user=user,
        description_tokens=description_str,
        amount=None,
        currency=None,
        category=category,
        payee=payee,
    )
    rules.append(rule1)
    
    # Rule 2: Description + amount + currency (most specific)
    rule2, _ = CategorizationRule.objects.get_or_create(
        user=user,
        description_tokens=description_str,
        amount=amount,
        currency=currency.upper(),
        category=category,
        payee=payee,
    )
    rules.append(rule2)
    
    # Rule 3: Description + currency
    rule3, _ = CategorizationRule.objects.get_or_create(
        user=user,
        description_tokens=description_str,
        amount=None,
        currency=currency.upper(),
        category=category,
        payee=payee,
    )
    rules.append(rule3)
    
    # Rule 4: Description + amount
    rule4, _ = CategorizationRule.objects.get_or_create(
        user=user,
        description_tokens=description_str,
        amount=amount,
        currency=None,
        category=category,
        payee=payee,
    )
    rules.append(rule4)
    
    return rules


def find_matching_rules(
    user,
    description: str,
    amount: Decimal,
    currency: str,
    threshold: float = 0.5,
) -> List[Tuple[CategorizationRule, float]]:
    """
    Find all rules that match a transaction.
    
    Returns rules ordered by specificity and usage (better rules first).
    Only returns rules with accuracy >= threshold.
    
    Args:
        user: User who owns the rules
        description: Transaction description
        amount: Transaction amount
        currency: Currency code
        threshold: Minimum accuracy score (0-1)
        
    Returns:
        List of (rule, match_score) tuples, ordered by match quality
    """
    tokens = sanitize_description(description)
    
    if not tokens:
        return []
    
    matches = []
    
    # Get all rules for this user with acceptable accuracy
    all_rules = CategorizationRule.objects.filter(
        user=user,
        accuracy__gte=threshold,
    )
    
    for rule in all_rules:
        # Normalize to lowercase for comparison
        rule_tokens = set(t.lower() for t in rule.description_tokens.split())
        transaction_tokens = set(t.lower() for t in tokens)
        
        # Must have at least one token in common
        if not (rule_tokens & transaction_tokens):
            continue
        
        # Check if amount and currency match (if specified in rule)
        amount_matches = rule.amount is None or rule.amount == amount
        currency_matches = rule.currency is None or rule.currency.upper() == currency.upper()
        
        if not (amount_matches and currency_matches):
            continue
        
        # Calculate match score based on specificity and usage
        specificity = get_rule_specificity_score(
            rule.description_tokens.split(),
            rule.amount,
            rule.currency,
        )
        
        # Usage count as a tiebreaker (recent frequent usage = higher score)
        usage_bonus = min(0.2, rule.usage_count * 0.01)
        match_score = specificity + usage_bonus
        
        matches.append((rule, match_score))
    
    # Sort by match score (highest first), then by accuracy
    matches.sort(key=lambda x: (-x[1], -x[0].accuracy))
    
    return matches


def apply_best_matching_rule(
    transaction: Transaction,
    threshold: float = 0.5,
) -> Optional[CategorizationRule]:
    """
    Find and apply the best matching rule to a transaction.
    
    If a rule matches:
    - Updates transaction's category and/or payee
    - Increments rule usage counter
    - Returns the applied rule
    
    Args:
        transaction: Transaction to categorize
        threshold: Minimum accuracy score
        
    Returns:
        The CategorizationRule that was applied, or None if no match found
    """
    if not transaction.description:
        return None
    
    matches = find_matching_rules(
        transaction.user,
        transaction.description,
        transaction.amount,
        transaction.currency,
        threshold=threshold,
    )
    
    if not matches:
        return None
    
    # Use the best match
    best_rule, score = matches[0]
    
    # Apply with lower minimum score (0.1) - we trust accuracy filtering more
    if score >= 0.1:  # Very lenient minimum score
        if best_rule.category and not transaction.category:
            transaction.category = best_rule.category
        
        if best_rule.payee and not transaction.payee:
            transaction.payee = best_rule.payee
        
        transaction.save()
        best_rule.increment_usage()
        
        return best_rule
    
    return None


def apply_rules_to_all_transactions(user, max_transactions: int = None) -> Tuple[int, int]:
    """
    Apply categorization rules to all uncategorized transactions for a user.
    
    Useful for batch processing or after new rules are created.
    
    Args:
        user: User whose transactions to process
        max_transactions: Maximum number to process (for testing)
        
    Returns:
        Tuple of (updated_count, total_uncategorized)
    """
    # Get uncategorized transactions
    uncategorized = Transaction.objects.filter(
        user=user,
        category__isnull=True,
    ).select_related('category', 'payee')
    
    if max_transactions:
        uncategorized = uncategorized[:max_transactions]
    
    total = uncategorized.count()
    updated = 0
    
    for transaction in uncategorized:
        if apply_best_matching_rule(transaction):
            updated += 1
    
    return updated, total


def get_user_rule_stats(user) -> dict:
    """
    Get statistics about a user's categorization rules.
    
    Args:
        user: User to get stats for
        
    Returns:
        Dictionary with rule statistics
    """
    rules = CategorizationRule.objects.filter(user=user)
    
    return {
        'total_rules': rules.count(),
        'avg_usage': rules.aggregate(avg=models.Avg('usage_count'))['avg'] or 0,
        'avg_accuracy': rules.aggregate(avg=models.Avg('accuracy'))['avg'] or 0,
        'total_applications': rules.aggregate(total=models.Sum('usage_count'))['total'] or 0,
    }


def cleanup_stale_rules(user, min_usage: int = 0) -> int:
    """
    Remove rules that haven't been used and have low accuracy.
    
    This helps keep the rule database manageable.
    
    Args:
        user: User whose rules to clean
        min_usage: Delete rules with usage count below this
        
    Returns:
        Number of rules deleted
    """
    to_delete = CategorizationRule.objects.filter(
        user=user,
        usage_count__lte=min_usage,
        accuracy__lt=0.5,
    )
    
    count = to_delete.count()
    to_delete.delete()
    
    return count
