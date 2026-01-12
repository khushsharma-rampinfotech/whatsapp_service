# app/services/upload_adapter.py

import os
import requests
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

CLAIMIFY_API_BASE_URL = os.getenv("CLAIMIFY_API_BASE_URL")

UPLOAD_ENDPOINT = "/api/upload/server"


def upload_bill_files(
    session_id: str,
    claim_no: int,
    bill_no: int,
    file_paths: List[Path],
) -> dict:
    """
    Upload invoice images/files to Claimify
    """

    if not CLAIMIFY_API_BASE_URL:
        raise RuntimeError("CLAIMIFY_API_BASE_URL not set")

    url = f"{CLAIMIFY_API_BASE_URL}{UPLOAD_ENDPOINT}"

    files = []
    for p in file_paths:
        files.append(
            (
                "files",
                (p.name, p.open("rb"), "application/octet-stream"),
            )
        )

    resp = requests.post(
        url,
        params={"sessionId": session_id},
        data={
            "claim_no": claim_no,
            "bill_no": bill_no,
        },
        files=files,
        timeout=30,
    )

    resp.raise_for_status()
    return resp.json()
