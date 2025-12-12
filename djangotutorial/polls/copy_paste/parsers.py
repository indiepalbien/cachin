"""Parser for bulk transaction import.

Detects and parses different bank statement formats.
"""

from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
import re
from .cleaners import AmountCleaner, DateCleaner, SourceCleaner, CurrencyCleaner, extract_amount_and_currency
from .utils import load_yaml_config


class TransactionParser:
    """Parse raw text into transaction dictionaries."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize parser with bank configs."""
        self.config = config
    
    def parse(
        self,
        raw_text: str,
        bank: str,
        currency: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Parse raw text into transactions.
        
        Args:
            raw_text: Text pasted from bank
            bank: Bank code (e.g., "itau_debito")
            currency: Currency code (e.g., "UYU", "USD") - required for some banks
        
        Returns:
            Tuple of (transactions: List[Dict], errors: List[str])
        """
        if bank not in self.config["banks"]:
            return [], [f"Bank '{bank}' not found in config"]
        
        bank_config = self.config["banks"][bank]
        
        # Check if currency is required
        if bank_config.get("requires_currency") and not currency:
            return [], ["Currency is required for this bank"]
        
        # Split lines
        lines = self._split_lines(raw_text, bank_config)
        
        if not lines:
            return [], ["No data lines found"]
        
        transactions = []
        errors = []
        
        for line_num, line in enumerate(lines, 1):
            try:
                txn = self._parse_line(line, bank_config, currency)
                if txn:
                    transactions.append(txn)
            except Exception as e:
                errors.append(f"Line {line_num}: {str(e)}")
        
        return transactions, errors
    
    def _split_lines(self, raw_text: str, bank_config: Dict[str, Any]) -> List[str]:
        """Split raw text into lines, filtering empty ones."""
        lines = raw_text.strip().split("\n")
        lines = [line.strip() for line in lines if line.strip()]
        return lines
    
    def _parse_line(
        self,
        line: str,
        bank_config: Dict[str, Any],
        currency: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a single line into a transaction.
        
        Returns None if line should be skipped, raises exception on error.
        """
        delimiter = bank_config.get("delimiter", "\t")
        columns = bank_config.get("columns", [])
        
        # Split line by delimiter
        parts = line.split(delimiter)
        
        if len(parts) < len(columns):
            raise ValueError(f"Expected {len(columns)} columns, got {len(parts)}")
        
        # Parse each column
        row = {}
        for col_config in columns:
            col_index = col_config.get("index")
            col_name = col_config.get("name")
            col_type = col_config.get("type")
            
            if col_index >= len(parts):
                raise ValueError(f"Column index {col_index} out of range")
            
            value = parts[col_index].strip()
            
            # Skip ignore columns
            if col_type == "ignore":
                continue
            
            # Parse by type
            if col_type == "date":
                date_format = col_config.get("format")
                parsed = DateCleaner.normalize_date(value, date_format)
                if parsed:
                    row[col_name] = parsed.strftime("%Y-%m-%d")
                else:
                    raise ValueError(f"Invalid date: {value}")
            
            elif col_type == "amount":
                parsed = AmountCleaner.parse_amount(value)
                if parsed is None and value:  # Allow empty amounts
                    raise ValueError(f"Invalid amount: {value}")
                row[col_name] = parsed
            
            elif col_type == "currency":
                # Currency can be explicit in config or from data
                if "value" in col_config:
                    row[col_name] = col_config["value"]
                else:
                    row[col_name] = CurrencyCleaner.normalize_currency(value) if value else None
            
            elif col_type == "string":
                row[col_name] = value if value else None
            
            else:
                row[col_name] = value
        
        # Special calculations for amounts
        amount_calculation = bank_config.get("amount_calculation")
        
        if amount_calculation == "debito - credito":
            # Itau débito: amount = debito - credito
            debito = row.get("debito") or Decimal('0')
            credito = row.get("credito") or Decimal('0')
            row["amount"] = debito - credito
        
        elif amount_calculation == "use_non_zero":
            # Scotia, BBVA: use the amount that's != 0
            pass  # Handled in extract_amount_and_currency
        
        # Extract final amount and currency
        if "amount_currency_pairs" in bank_config:
            amount, curr = extract_amount_and_currency(row, bank_config)
            row["amount"] = amount
            row["currency"] = curr
        else:
            # Add default currency if needed
            if "currency" not in row and currency:
                row["currency"] = currency
        
        # Clean source
        if "tarjeta" in row:
            source_value = row.pop("tarjeta")
            source_prefix = bank_config.get("source_prefix", "")
            row["source"] = SourceCleaner.clean_source(source_value, source_prefix.replace(":", ""))
        
        # Build final transaction dict
        txn = {
            "date": row.get("fecha"),
            "description": row.get("description"),
            "amount": row.get("amount"),
            "currency": row.get("currency"),
            "source": row.get("source"),
        }
        
        return txn


class FormatDetector:
    """Detect which bank format matches given text."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize detector with bank configs."""
        self.config = config
    
    def find_best_match(
        self,
        raw_text: str,
        bank: Optional[str] = None
    ) -> Tuple[Optional[str], float]:
        """
        Find the best matching bank format.
        
        Args:
            raw_text: Text to analyze
            bank: If specified, only match formats for this bank
        
        Returns:
            Tuple of (bank_code: str, confidence: float) or (None, 0.0)
        """
        lines = raw_text.strip().split("\n")
        lines = [line.strip() for line in lines if line.strip()]
        
        if not lines:
            return None, 0.0
        
        best_match = None
        best_score = 0.0
        
        # Get banks to test
        banks_to_test = [bank] if bank else self.config["banks"].keys()
        
        for bank_code in banks_to_test:
            if bank_code not in self.config["banks"]:
                continue
            
            score = self.match_score(lines, bank_code)
            if score > best_score:
                best_score = score
                best_match = bank_code
        
        return best_match, best_score
    
    def match_score(self, lines: List[str], bank: str) -> float:
        """
        Score how well the text matches a bank format.
        
        Returns score 0.0 to 1.0
        """
        if bank not in self.config["banks"]:
            return 0.0
        
        bank_config = self.config["banks"][bank]
        
        # Try to parse the first few lines
        successful_parses = 0
        total_lines = min(len(lines), 5)  # Test first 5 lines
        
        delimiter = bank_config.get("delimiter", "\t")
        columns = bank_config.get("columns", [])
        expected_col_count = len(columns)
        
        for line in lines[:total_lines]:
            parts = line.split(delimiter)
            if len(parts) >= expected_col_count:
                successful_parses += 1
        
        # Score based on successful parses
        score = successful_parses / total_lines if total_lines > 0 else 0.0
        
        return score
