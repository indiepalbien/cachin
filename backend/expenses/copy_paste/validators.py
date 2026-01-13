"""Validation for parsed transactions."""

from typing import List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime


class TransactionValidator:
    """Validate parsed transactions."""
    
    @staticmethod
    def validate_transaction(txn: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate a single transaction.
        
        Args:
            txn: Transaction dictionary
        
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors = []
        
        # Check required fields
        if not txn.get("date"):
            errors.append("Missing date")
        
        if not txn.get("description"):
            errors.append("Missing description")
        
        if txn.get("amount") is None:
            errors.append("Missing amount")
        
        if not txn.get("currency"):
            errors.append("Missing currency")
        
        # Validate date format
        if txn.get("date"):
            try:
                datetime.strptime(txn["date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                errors.append(f"Invalid date format: {txn['date']}")
        
        # Validate amount is numeric
        if txn.get("amount") is not None:
            try:
                if not isinstance(txn["amount"], (int, float, Decimal)):
                    Decimal(str(txn["amount"]))
            except (ValueError, TypeError):
                errors.append(f"Invalid amount: {txn['amount']}")
        
        # Validate currency is 3-letter code
        if txn.get("currency"):
            if not isinstance(txn["currency"], str):
                errors.append(f"Invalid currency type: {type(txn['currency'])}")
            elif len(txn["currency"]) != 3:
                errors.append(f"Currency must be 3 letters: {txn['currency']}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def check_duplicate_in_batch(
        txn: Dict[str, Any],
        batch: List[Dict[str, Any]]
    ) -> bool:
        """
        Check if transaction is duplicate within the batch.
        
        Duplicates are identified by: date + description + amount + currency
        """
        for existing in batch:
            if (txn["date"] == existing["date"] and
                txn["description"] == existing["description"] and
                txn["amount"] == existing["amount"] and
                txn["currency"] == existing["currency"]):
                return True
        return False
    
    @staticmethod
    def check_duplicate_in_db(
        txn: Dict[str, Any],
        user_id: int,
        from_django: bool = False
    ) -> bool:
        """
        Check if transaction already exists in database.
        
        This requires access to Django ORM, so it's done separately
        in the view layer.
        
        Args:
            txn: Transaction to check
            user_id: User ID
            from_django: If True, imports Transaction model (called from views)
        
        Returns:
            True if duplicate exists
        """
        if not from_django:
            return False
        
        from ..models import Transaction
        from decimal import Decimal
        
        # Check for exact match
        existing = Transaction.objects.filter(
            user_id=user_id,
            date=txn["date"],
            description=txn["description"],
            amount=Decimal(str(txn["amount"])),
            currency=txn["currency"]
        ).exists()
        
        return existing
