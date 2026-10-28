import sqlite3

from test import find_customer


def test_username_with_quote_is_plain_text_and_does_not_return_other_rows():
    username = "o'brien' OR '1'='1"
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE customers (username TEXT, balance REAL)")
    connection.executemany(
        "INSERT INTO customers (username, balance) VALUES (?, ?)",
        [
            ("alice", 10.0),
            ("bob", 25.5),
            (username, 99.0),
        ],
    )

    rows = find_customer(username, connection)

    assert rows == [(99.0,)]
    assert (10.0,) not in rows
    assert (25.5,) not in rows
    assert find_customer("alice", connection) == [(10.0,)]
    assert find_customer("bob", connection) == [(25.5,)]
