"""
Image-based transaction ingestion using LlamaCloud API.
"""
import asyncio
import logging
from pathlib import Path
from typing import List
from decimal import Decimal
from datetime import date
from llama_cloud_services import LlamaExtract
from pydantic import BaseModel, Field
from django.conf import settings

logger = logging.getLogger(__name__)

extractor = LlamaExtract(api_key=settings.LLAMACLOUD_API_KEY)
agent = extractor.get_agent(name="cachin-transactions")

class ParsedTransaction(BaseModel):
    """Pydantic model for a transaction extracted from an image by LlamaCloud."""
    
    description: str = Field(..., description="Transaction description or merchant name")
    amount: float = Field(..., description="Transaction amount (positive for expenses)")
    currency: str = Field(..., description="Currency code (e.g., USD, PEN, UYU)")
    date: str = Field(..., description="Transaction date")


def process_image_with_llamacloud(image_paths: List[str]) -> List[List[ParsedTransaction]]:
    """
    Process one or more images with LlamaCloud API to extract transaction data.
    
    Args:
        image_paths: List of absolute file paths to receipt/transaction images
        
    Returns:
        List of lists of ParsedTransaction (one list per image)
    """
        # Process each image independently
    results_llamacloud = [agent.extract(path) for path in image_paths]
        
    results = []
    for result in results_llamacloud:
        transactions = [ParsedTransaction(**txn_data) for txn_data in result.data.get("transactions", [])]
        results.append(transactions)
    
    return results



def convert_parsed_to_transaction_dict(parsed: ParsedTransaction, user, source_name: str = "image_upload") -> dict:
    """
    Convert ParsedTransaction to dictionary suitable for Transaction creation.
    
    Args:
        parsed: ParsedTransaction from LlamaCloud
        user: Django User instance
        source_name: Source name for the transaction
        
    Returns:
        Dictionary with transaction fields ready for creation
    """
    return {
        "user": user,
        "date": parsed.date,
        "description": parsed.description,
        "amount": parsed.amount,
        "currency": parsed.currency.upper(),
        "source_name": source_name,
    }
