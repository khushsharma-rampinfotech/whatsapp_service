import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

DRIVER = os.getenv("DRIVER")
SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_PORT = os.getenv("SQL_SERVER_PORT", "1433")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")  # Dev_ExpenseApp

CONN_STR = (
    f"DRIVER={DRIVER};"
    f"SERVER={SQL_SERVER_HOST},{SQL_SERVER_PORT};"
    f"DATABASE={SQL_SERVER_DB};"
    f"UID={SQL_SERVER_USER};"
    f"PWD={SQL_SERVER_PASSWORD};"
    f"TrustServerCertificate=yes;"
)

def get_services_for_phone(phone: str) -> list[str]:
    """
    Returns enabled services for a phone number.
    Possible returns:
      ['CLAIM']
      ['GRN']
      ['CLAIM', 'GRN']
      []
    """

    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT feature
        FROM [product].[WhatsappUser]
        WHERE phone_number = ?
          AND is_disabled = 0
        """,
        phone,
    )

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [row.feature.strip().upper() for row in rows]
