from typing import List, TypedDict
from pydantic import BaseModel, Field

# --- Pydantic Models for Structured Output ---

class Transaction(BaseModel):
    """Represents a single financial transaction."""
    merchant: str = Field(description="The name of the business or person from whom the purchase was made.")
    amount: float = Field(description="The total amount of the transaction.")
    date: str = Field(description="The date of the transaction in YYYY-MM-DD format.")

class Transactions(BaseModel):
    """A list of financial transactions."""
    transactions: List[Transaction]

class CategorizedTransaction(BaseModel):
    """Represents a transaction that has been assigned a category."""
    category: str = Field(description="The category for the transaction.")
    merchant: str = Field(description="The name of the business or person from whom the purchase was made.")
    amount: float = Field(description="The total amount of the transaction.")
    date: str = Field(description="The date of the transaction in YYYY-MM-DD format.")

# --- Graph State ---

class GraphState(TypedDict):
    image_bytes: bytes
    text_data: str
    input_type: str  # "image" or "text" or "web"
    categories: List[str]
    transactions: List[Transaction]
    categorized_transactions: List[CategorizedTransaction] 