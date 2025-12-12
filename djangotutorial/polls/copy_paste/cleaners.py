"""Data cleaning functions for bulk transaction import.

Handles normalization of amounts, dates, and other fields.
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Tuple, Optional, Dict, Any


class AmountCleaner:
    """Clean and parse monetary amounts."""

    @staticmethod
    def normalize_amount(value: str) -> Optional[float]:
        """
        Normalize amount string to float.
        
        Examples:
            "1,200.44" -> 1200.44
            "1.200,44" -> 1200.44
            "1200.44" -> 1200.44
            "1,200" -> 1200.0
            "USD 140.50" -> 140.50
            "UYU 0,00" -> 0.0
        """
        if not value or not isinstance(value, str):
            return None
        
        value = value.strip()
        if not value:
            return None
        
        # Remove currency prefixes (e.g., "USD 140.50" -> "140.50")
        # Common currency codes are 3 letters followed by space
        import re
        value = re.sub(r'^[A-Z]{3}\s+', '', value)
        
        # Remove whitespace
        value = value.replace(" ", "")
        
        # Detect format: if comma is before period, it's thousands separator
        # (1,200.44 format - US/UK)
        # If period is before comma, comma is thousands separator (1.200,44 - EU)
        comma_pos = value.rfind(",")
        period_pos = value.rfind(".")
        
        if comma_pos == -1 and period_pos == -1:
            # No separators, just digits
            try:
                return float(value)
            except ValueError:
                return None
        
        if comma_pos == -1:
            # Only period (US format)
            try:
                return float(value)
            except ValueError:
                return None
        
        if period_pos == -1:
            # Only comma (EU format with , as decimal)
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return None
        
        # Both exist - determine which is decimal separator
        if comma_pos > period_pos:
            # Comma is decimal separator (EU: 1.200,44)
            clean_value = value.replace(".", "").replace(",", ".")
        else:
            # Period is decimal separator (US: 1,200.44)
            clean_value = value.replace(",", "")
        
        try:
            return float(clean_value)
        except ValueError:
            return None
    
    @staticmethod
    def parse_amount(value: str) -> Optional[Decimal]:
        """Parse amount to Decimal for database storage."""
        normalized = AmountCleaner.normalize_amount(value)
        if normalized is None:
            return None
        try:
            return Decimal(str(normalized)).quantize(Decimal('0.01'))
        except InvalidOperation:
            return None


class DateCleaner:
    """Clean and parse date strings."""
    
    # Common date formats
    COMMON_FORMATS = [
        "%d-%m-%y",   # 05-12-25
        "%d/%m/%y",   # 05/12/25
        "%d/%m/%Y",   # 05/12/2025
        "%d-%m-%Y",   # 05-12-2025
        "%Y-%m-%d",   # 2025-12-05
        "%d/%m/%y",   # 05/12/25
    ]
    
    @staticmethod
    def normalize_date(value: str, format_str: Optional[str] = None) -> Optional[datetime]:
        """
        Parse date string to datetime.
        
        Args:
            value: Date string to parse
            format_str: Expected format (e.g., "DD/MM/YY"). If None, tries common formats.
        
        Returns:
            datetime object or None if parsing fails
        """
        if not value or not isinstance(value, str):
            return None
        
        value = value.strip()
        if not value:
            return None
        
        # If format specified, try that first
        if format_str:
            try:
                return datetime.strptime(value, format_str)
            except ValueError:
                pass
        
        # Try common formats
        for fmt in DateCleaner.COMMON_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        
        return None


class CurrencyCleaner:
    """Clean and normalize currency codes."""
    
    # Mapping of common currency names to ISO codes
    CURRENCY_MAPPING = {
        'pesos': 'UYU',
        'peso': 'UYU',
        'dólares': 'USD',
        'dolares': 'USD',
        'dólar': 'USD',
        'dolar': 'USD',
        'dollars': 'USD',
        'dollar': 'USD',
        # Handle corrupted encodings
        'dï¿½lares': 'USD',
        'dï¿½lar': 'USD',
    }
    
    @staticmethod
    def normalize_currency(value: str) -> Optional[str]:
        """
        Normalize currency code to ISO 4217 format.
        
        Args:
            value: Currency string (e.g., "Pesos", "Dólares", "USD")
        
        Returns:
            ISO currency code (e.g., "UYU", "USD") or original if already valid
        """
        if not value or not isinstance(value, str):
            return None
        
        value = value.strip()
        if not value:
            return None
        
        # If already a 3-letter code, use it as-is
        if len(value) == 3 and value.isalpha():
            return value.upper()
        
        # Try to map from common names
        value_lower = value.lower()
        if value_lower in CurrencyCleaner.CURRENCY_MAPPING:
            return CurrencyCleaner.CURRENCY_MAPPING[value_lower]
        
        # Fuzzy matching for corrupted encodings
        # Check if it contains "dolar" or "peso" somewhere
        if 'dolar' in value_lower or 'dï¿½lar' in value_lower:
            return 'USD'
        if 'peso' in value_lower:
            return 'UYU'
        
        # Return as-is if no mapping found
        return value.upper()


class SourceCleaner:
    """Clean and format source identifiers."""
    
    @staticmethod
    def clean_source(value: str, bank: str) -> Optional[str]:
        """
        Clean source identifier and add bank prefix.
        
        Args:
            value: Raw source value (e.g., "7654" for Itau card)
            bank: Bank code (e.g., "itau", "scotia", "bbva")
        
        Returns:
            Formatted source string (e.g., "itau:7654")
        """
        if not value or not isinstance(value, str):
            return None
        
        value = value.strip()
        if not value:
            return None
        
        # Remove asterisks and extra padding (for Itau: "**** 7654" -> "7654")
        value = value.replace("*", "").strip()
        
        if not value:
            return None
        
        # Add bank prefix
        bank = bank.lower().strip()
        return f"{bank}:{value}"


def extract_amount_and_currency(
    row: Dict[str, Any],
    config: Dict[str, Any]
) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Extract amount and currency from a parsed row.
    
    Handles cases with:
    1. Single amount field
    2. Multiple amount fields with "use_non_zero" strategy
    
    Args:
        row: Parsed row dictionary from parser
        config: Bank config from YAML
    
    Returns:
        Tuple of (amount: Decimal, currency: str) or (None, None) if extraction fails
    """
    
    # Case 1: Multiple montos (Scotia, BBVA) - use the one that's != 0
    if "amount_currency_pairs" in config:
        for pair in config["amount_currency_pairs"]:
            amount_field = pair.get("amount_field")
            currency = pair.get("currency")
            
            if amount_field not in row:
                continue
            
            amount_value = row[amount_field]
            
            # Parse and check if non-zero
            if amount_value is not None:
                parsed = AmountCleaner.parse_amount(str(amount_value))
                if parsed is not None and parsed != Decimal('0'):
                    return (parsed, currency)
        
        # All are zero, return the first one
        if config["amount_currency_pairs"]:
            first_pair = config["amount_currency_pairs"][0]
            return (Decimal('0'), first_pair.get("currency"))
    
    # Case 2: Direct amount field
    if "amount" in row and "currency" in row:
        amount = AmountCleaner.parse_amount(str(row["amount"]))
        currency = row["currency"]
        return (amount, currency)
    
    return (None, None)
