#!/usr/bin/env python
"""
Simple standalone test for infer_transaction_year function.
Tests empty date handling from llamacloud parsing.
"""
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import the function directly (without Django)
from datetime import datetime


def infer_transaction_year(date_str):
    """
    Infer the year for a transaction date in MM-DD format.

    Logic:
    - If month <= current month: use current year
    - If month > current month: use previous year (e.g., in Jan seeing Dec means last year)

    Args:
        date_str: Date string in format "MM-DD" or "YYYY-MM-DD"

    Returns:
        Date string in "YYYY-MM-DD" format, or None if date is empty/invalid
    """
    # Handle None explicitly
    if date_str is None:
        return None
    
    # Handle empty or whitespace-only strings
    if not date_str or not date_str.strip():
        return None

    # If already has year (YYYY-MM-DD format), return as-is
    if len(date_str.split('-')) == 3 and len(date_str.split('-')[0]) == 4:
        return date_str

    # Parse MM-DD format
    try:
        month, day = date_str.split('-')
        month = int(month)
        day = int(day)

        # Get current date
        now = datetime.now()
        current_year = now.year
        current_month = now.month

        # Infer year: if month > current month, use previous year
        if month > current_month:
            year = current_year - 1
        else:
            year = current_year

        return f"{year}-{month:02d}-{day:02d}"

    except (ValueError, AttributeError):
        # If parsing fails, return None for invalid dates
        return None


def test_empty_string():
    """Empty string should return None."""
    result = infer_transaction_year('')
    assert result is None, f"Expected None, got {result}"
    print("✓ Empty string test passed")


def test_none():
    """None should return None."""
    result = infer_transaction_year(None)
    assert result is None, f"Expected None, got {result}"
    print("✓ None test passed")


def test_whitespace():
    """Whitespace only should return None."""
    result = infer_transaction_year('   ')
    assert result is None, f"Expected None, got {result}"
    print("✓ Whitespace test passed")


def test_valid_full_date():
    """Valid YYYY-MM-DD format should be returned as-is."""
    result = infer_transaction_year('2024-12-25')
    assert result == '2024-12-25', f"Expected '2024-12-25', got {result}"
    print("✓ Valid full date test passed")


def test_valid_mm_dd():
    """Valid MM-DD format should infer year."""
    result = infer_transaction_year('12-25')
    assert result is not None, f"Expected a result, got None"
    # Should return a valid date string in YYYY-MM-DD format
    parts = result.split('-')
    assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}"
    year, month, day = parts
    assert len(year) == 4, f"Expected year length 4, got {len(year)}"
    assert month == '12', f"Expected month '12', got {month}"
    assert day == '25', f"Expected day '25', got {day}"
    print(f"✓ Valid MM-DD test passed (result: {result})")


def test_invalid_format():
    """Invalid format should return None."""
    result = infer_transaction_year('invalid-date')
    assert result is None, f"Expected None, got {result}"
    print("✓ Invalid format test passed")


def test_partial_invalid():
    """Partially valid format should return None."""
    result = infer_transaction_year('12-')
    assert result is None, f"Expected None, got {result}"
    print("✓ Partial invalid test passed")


if __name__ == '__main__':
    print("Running tests for infer_transaction_year...")
    print()
    
    tests = [
        test_empty_string,
        test_none,
        test_whitespace,
        test_valid_full_date,
        test_valid_mm_dd,
        test_invalid_format,
        test_partial_invalid,
    ]
    
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} errored: {e}")
            failed += 1
    
    print()
    if failed == 0:
        print(f"All {len(tests)} tests passed! ✓")
        sys.exit(0)
    else:
        print(f"{failed}/{len(tests)} tests failed")
        sys.exit(1)
