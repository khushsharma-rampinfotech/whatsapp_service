# app/services/grn_adapter.py

import requests
from pathlib import Path

GRN_API_URL = "http://161.97.142.50:50102/extract/grn"

def extract_grn(file_path: Path) -> dict:
    with file_path.open("rb") as f:
        resp = requests.post(
            GRN_API_URL,
            files={"file": (file_path.name, f)},
            timeout=(10, 900),  # ✅ 10s connect, 15 min read
        )

    resp.raise_for_status()
    return resp.json()
