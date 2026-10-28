import sqlite3


def find_customer(username, connection=None):
    owns_connection = connection is None
    if owns_connection:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE customers (username TEXT, balance REAL)")
    try:
        return connection.execute(
            "SELECT balance FROM customers WHERE username = ?",
            (username,),
        ).fetchall()
    finally:
        if owns_connection:
            connection.close()
