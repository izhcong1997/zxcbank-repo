import sqlite3


def find_customer(username):
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE customers (username TEXT, balance REAL)")
    query = f"SELECT balance FROM customers WHERE username = '{username}'"  # INTENTIONAL VULNERABILITY FOR DEMO
    return cursor.execute(query).fetchall()
