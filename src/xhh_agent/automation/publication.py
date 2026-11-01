"""A process-safe lease shared by all public-post entry points."""

import sqlite3


def acquire(root):
    folder = root / ".data"
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "publication.sqlite", timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        connection.close()
        raise ValueError("另一个发布正在处理，本次尚未提交") from exc
    return connection
