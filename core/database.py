import os
import psycopg2
from psycopg2.extras import DictCursor
from typing import List, Dict, Any
import streamlit as st
from core.config import settings

@st.cache_resource
def initialize_database():
    """
    Connects to the database and creates tables if they don't exist.
    This function is cached and will only run once per Streamlit process.
    """
    setup_database()

def get_connection():
    """Establishes a connection to the database."""
    return psycopg2.connect(settings.DATABASE_URL)

def setup_database():
    """Creates the necessary tables if they don't exist and applies lightweight migrations."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            budget NUMERIC NOT NULL
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            merchant TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            date DATE NOT NULL,
            category TEXT NOT NULL
        );
    """)

    # --- Lightweight migration: add identifier column and unique index ---
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='expenses' AND column_name='identifier'
            ) THEN
                ALTER TABLE expenses ADD COLUMN identifier TEXT;
            END IF;
        END$$;
    """)

    # Backfill identifier for existing rows where null (merchant|date|amount)
    cur.execute("""
        UPDATE expenses
        SET identifier = lower(trim(merchant)) || '|' || to_char(date, 'YYYY-MM-DD') || '|' || to_char(amount, 'FM999999990.00')
        WHERE identifier IS NULL;
    """)

    # Ensure unique index on identifier
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS unique_expenses_identifier ON expenses(identifier);
    """)

    # Optionally enforce NOT NULL now that we've backfilled
    try:
        cur.execute("ALTER TABLE expenses ALTER COLUMN identifier SET NOT NULL;")
    except Exception:
        conn.rollback()
        cur = conn.cursor()

    # Seed initial categories if the table is empty
    cur.execute("SELECT COUNT(*) FROM categories")
    if cur.fetchone()[0] == 0:
        initial_categories = {
            "Coffee": 700, "Restaurants": 700, "Supermarket & Groceries": 1000,
            "Pharmacy": 300, "Clothing": 200, "Car Gas": 700, "Car Expenses": 100,
            "TV & Communication": 300, "Taxi & Bus": 100, "Uncategorized": 2000,
        }
        for name, budget in initial_categories.items():
            cur.execute("INSERT INTO categories (name, budget) VALUES (%s, %s)", (name, budget))

    conn.commit()
    cur.close()
    conn.close()

# --- Helper ---

def _normalize_amount(amount: float) -> str:
    """Format amount to a consistent string with 2 decimal places for identifier."""
    try:
        return f"{float(amount):.2f}"
    except Exception:
        return "0.00"

def _compute_identifier(merchant: str, date: str, amount: float) -> str:
    """Compute a stable identifier from merchant, date (YYYY-MM-DD), and amount."""
    normalized_merchant = (merchant or "").strip().lower()
    amount_str = _normalize_amount(amount)
    return f"{normalized_merchant}|{date}|{amount_str}"

# --- Categories CRUD ---

def get_categories() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, name, budget FROM categories ORDER BY name")
    categories = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return categories

def add_category(name: str, budget: float):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name, budget) VALUES (%s, %s)", (name, budget))
    conn.commit()
    cur.close()
    conn.close()

def update_category_budget(category_id: int, new_budget: float):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE categories SET budget = %s WHERE id = %s", (new_budget, category_id))
    conn.commit()
    cur.close()
    conn.close()

# --- Expenses CRUD ---

def get_expenses() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        """
        SELECT id, merchant, amount, date, category
        FROM expenses
        ORDER BY date DESC
        """
    )
    expenses = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return expenses

def transaction_exists(merchant: str, amount: float, date: str) -> bool:
    """Checks if a transaction with the same identifier (merchant+date+amount) already exists."""
    return transaction_exists_by_identifier(merchant, amount, date)

def transaction_exists_by_identifier(merchant: str, amount: float, date: str) -> bool:
    """Checks if a transaction with the same identifier already exists."""
    conn = get_connection()
    cur = conn.cursor()
    identifier = _compute_identifier(merchant, date, amount)
    query = "SELECT 1 FROM expenses WHERE identifier = %s LIMIT 1;"
    cur.execute(query, (identifier,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None

def add_expense(merchant: str, amount: float, date: str, category_name: str):
    conn = get_connection()
    cur = conn.cursor()
    identifier = _compute_identifier(merchant, date, amount)
    try:
        cur.execute(
            """
            INSERT INTO expenses (merchant, amount, date, category, identifier)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (identifier) DO NOTHING
            """,
            (merchant, amount, date, category_name, identifier)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return True

def update_expense(expense_id: int, merchant: str, amount: float, date: str, category: str):
    conn = get_connection()
    cur = conn.cursor()
    # Do not update identifier; keep it stable from original insertion
    cur.execute(
        """
        UPDATE expenses
        SET merchant = %s, amount = %s, date = %s, category = %s
        WHERE id = %s
        """,
        (merchant, amount, date, category, expense_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def delete_expense(expense_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_category_by_merchant(merchant_name: str) -> str | None:
    """Finds the most recent category for a given merchant from the expenses table."""
    conn = get_connection()
    cur = conn.cursor()
    query = """
        SELECT category
        FROM expenses
        WHERE merchant = %s
        ORDER BY date DESC, id DESC
        LIMIT 1;
    """
    cur.execute(query, (merchant_name,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        return result[0]
    return None