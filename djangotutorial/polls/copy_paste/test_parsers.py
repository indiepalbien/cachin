#!/usr/bin/env python
"""
Test script for bulk import functionality.
Run from project root: python djangotutorial/polls/copy_paste/test_parsers.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from djangotutorial.polls.copy_paste.parsers import TransactionParser
from djangotutorial.polls.copy_paste.validators import TransactionValidator
from djangotutorial.polls.copy_paste.utils import load_yaml_config


def test_itau_debito():
    """Test ITAU Débito format."""
    print("\n" + "="*50)
    print("Testing ITAU Débito")
    print("="*50)
    
    raw_text = """05-12-25\tDEB. CAMBIOSCOMI..174735\t10,00\t\t6.079,21
05-12-25\tCRE. CAMBIOSOP....174735\t\t1.100,00\t7.179,21
08-12-25\tDEB. VARIOS TARJ. VISA\t833,73\t\t6.345,48"""
    
    config = load_yaml_config()
    parser = TransactionParser(config)
    transactions, errors = parser.parse(raw_text, "itau_debito", "UYU")
    
    print(f"Parsed: {len(transactions)} transactions")
    print(f"Errors: {errors}")
    
    for i, txn in enumerate(transactions, 1):
        is_valid, val_errors = TransactionValidator.validate_transaction(txn)
        print(f"\nTransaction {i}: {'✓' if is_valid else '✗'}")
        print(f"  Date: {txn.get('date')}")
        print(f"  Description: {txn.get('description')}")
        print(f"  Amount: {txn.get('amount')} {txn.get('currency')}")
        if not is_valid:
            print(f"  Errors: {val_errors}")


def test_itau_credito():
    """Test ITAU Crédito format."""
    print("\n" + "="*50)
    print("Testing ITAU Crédito")
    print("="*50)
    
    raw_text = """**** 7654\tTECHSTORE.COM\tComun\t27/11/25\tDólares\t2,99
**** 7654\tMETRO PHARMACY\tComun\t29/11/25\tPesos\t1.372,00
**** 7654\tCOCO MINIMARKET\tComun\t29/11/25\tPesos\t115,00"""
    
    config = load_yaml_config()
    parser = TransactionParser(config)
    transactions, errors = parser.parse(raw_text, "itau_credito")
    
    print(f"Parsed: {len(transactions)} transactions")
    print(f"Errors: {errors}")
    
    for i, txn in enumerate(transactions, 1):
        is_valid, val_errors = TransactionValidator.validate_transaction(txn)
        print(f"\nTransaction {i}: {'✓' if is_valid else '✗'}")
        print(f"  Date: {txn.get('date')}")
        print(f"  Description: {txn.get('description')}")
        print(f"  Amount: {txn.get('amount')} {txn.get('currency')}")
        print(f"  Source: {txn.get('source')}")
        if not is_valid:
            print(f"  Errors: {val_errors}")


def test_scotia_credito():
    """Test Scotia Crédito format."""
    print("\n" + "="*50)
    print("Testing Scotia Crédito")
    print("="*50)
    
    raw_text = """28/11/2025\tSKY AIRLINE / MONTEVIDEO\tUYU 0,00\tUSD 140,50
28/11/2025\tSKY AIRLINE / MONTEVIDEO\tUYU 0,00\tUSD 140,50
01/12/2025\tPAYPAL *MCDONALS / 4029357733\tUYU 0,00\tUSD 50,00"""
    
    config = load_yaml_config()
    parser = TransactionParser(config)
    transactions, errors = parser.parse(raw_text, "scotia_credito")
    
    print(f"Parsed: {len(transactions)} transactions")
    print(f"Errors: {errors}")
    
    for i, txn in enumerate(transactions, 1):
        is_valid, val_errors = TransactionValidator.validate_transaction(txn)
        print(f"\nTransaction {i}: {'✓' if is_valid else '✗'}")
        print(f"  Date: {txn.get('date')}")
        print(f"  Description: {txn.get('description')}")
        print(f"  Amount: {txn.get('amount')} {txn.get('currency')}")
        if not is_valid:
            print(f"  Errors: {val_errors}")


def test_bbva_credito():
    """Test BBVA Crédito format."""
    print("\n" + "="*50)
    print("Testing BBVA Crédito")
    print("="*50)
    
    raw_text = """19/11/2025\t5500321487659234\tMETRO SUPPLIES\t734,00\t\tNOVIEMBRE / 2025
13/11/2025\t5500321487659234\tMETRO SUPPLIES\t1.035,00\t\tNOVIEMBRE / 2025
11/11/2025\t5500321487659234\tMETRO SUPPLIES\t\t315,00\tNOVIEMBRE / 2025"""
    
    config = load_yaml_config()
    parser = TransactionParser(config)
    transactions, errors = parser.parse(raw_text, "bbva_credito")
    
    print(f"Parsed: {len(transactions)} transactions")
    print(f"Errors: {errors}")
    
    for i, txn in enumerate(transactions, 1):
        is_valid, val_errors = TransactionValidator.validate_transaction(txn)
        print(f"\nTransaction {i}: {'✓' if is_valid else '✗'}")
        print(f"  Date: {txn.get('date')}")
        print(f"  Description: {txn.get('description')}")
        print(f"  Amount: {txn.get('amount')} {txn.get('currency')}")
        print(f"  Source: {txn.get('source')}")
        if not is_valid:
            print(f"  Errors: {val_errors}")


if __name__ == "__main__":
    print("\n" + "="*50)
    print("BULK IMPORT PARSER TESTS")
    print("="*50)
    
    test_itau_debito()
    test_itau_credito()
    test_scotia_credito()
    test_bbva_credito()
    
    print("\n" + "="*50)
    print("All tests completed!")
    print("="*50 + "\n")
