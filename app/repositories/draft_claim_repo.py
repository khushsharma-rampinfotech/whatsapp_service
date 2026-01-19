import os
import pyodbc
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

DRIVER = os.getenv("DRIVER")
SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_PORT = os.getenv("SQL_SERVER_PORT", "1433")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")

CONN_STR = (
    f"DRIVER={DRIVER};"
    f"SERVER={SQL_SERVER_HOST},{SQL_SERVER_PORT};"
    f"DATABASE={SQL_SERVER_DB};"
    f"UID={SQL_SERVER_USER};"
    f"PWD={SQL_SERVER_PASSWORD};"
    f"TrustServerCertificate=yes;"
)


def get_latest_drafted_claim(emp_id: int, schema: str) -> Optional[int]:
    """
    Returns latest drafted claim_no for employee.
    Returns None if no draft exists.
    """
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT TOP 1 claim_no
        FROM [{SQL_SERVER_DB}].[{schema}].[Claims]
        WHERE emp_id = ?
          AND (claim_status = 'Drafted' OR claim_status IS NULL)
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY created_on DESC
        """,
        emp_id,
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    return int(row.claim_no) if row else None
