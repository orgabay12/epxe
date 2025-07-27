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
    """Creates the necessary tables if they don't exist."""
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
    cur.execute("""
        SELECT id, merchant, amount, date, category
        FROM expenses
        ORDER BY date DESC
    """)
    expenses = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return expenses

def transaction_exists(merchant: str, amount: float, date: str) -> bool:
    """Checks if a transaction with the same merchant, amount, and date already exists."""
    conn = get_connection()
    cur = conn.cursor()
    query = """
        SELECT id
        FROM expenses
        WHERE merchant = %s AND amount = %s AND date = %s;
    """
    # Ensure amount is a float for the query
    cur.execute(query, (merchant, float(amount), date))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None

def add_expense(merchant: str, amount: float, date: str, category_name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (merchant, amount, date, category) VALUES (%s, %s, %s, %s)",
        (merchant, amount, date, category_name)
    )
    conn.commit()
    cur.close()
    conn.close()
    return True

def update_expense(expense_id: int, merchant: str, amount: float, date: str, category: str):
    conn = get_connection()
    cur = conn.cursor()
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