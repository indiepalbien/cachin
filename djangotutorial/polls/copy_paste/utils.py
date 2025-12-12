"""Utility functions for copy-paste import."""

import yaml
from pathlib import Path
from typing import Dict, Any
import os


def load_yaml_config() -> Dict[str, Any]:
    """
    Load and parse the bank configurations from YAML.
    
    Returns:
        Dictionary with bank configurations
    """
    # Find config file relative to this module
    config_path = Path(__file__).parent / "configs.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    if not config:
        raise ValueError("Config file is empty")
    
    return config


def get_available_banks() -> Dict[str, str]:
    """
    Get list of available banks from config.
    
    Returns:
        Dictionary of {bank_code: bank_name}
    """
    config = load_yaml_config()
    return {
        code: bank_config.get("name", code)
        for code, bank_config in config.get("banks", {}).items()
    }


def get_bank_config(bank: str) -> Dict[str, Any]:
    """
    Get specific bank configuration.
    
    Args:
        bank: Bank code
    
    Returns:
        Bank configuration dictionary
    """
    config = load_yaml_config()
    banks = config.get("banks", {})
    
    if bank not in banks:
        raise ValueError(f"Unknown bank: {bank}")
    
    return banks[bank]


def format_transaction_for_display(txn: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format transaction for frontend display.
    
    Args:
        txn: Transaction dictionary from parser
    
    Returns:
        Formatted transaction dictionary
    """
    formatted = {
        "date": txn.get("date"),
        "description": txn.get("description"),
        "amount": str(txn.get("amount", "")),
        "currency": txn.get("currency"),
        "source": txn.get("source"),
    }
    
    # Include duplicate flag if present
    if txn.get("is_duplicate"):
        formatted["is_duplicate"] = True
    
    return formatted
