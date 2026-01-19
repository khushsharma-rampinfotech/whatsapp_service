# app/services/claim_adapter.py

import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import date

import requests

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
CLAIMIFY_API_BASE = os.getenv("CLAIMIFY_API_BASE")
REQUEST_TIMEOUT = 15

if not CLAIMIFY_API_BASE:
    raise RuntimeError("❌ CLAIMIFY_API_BASE not set in environment")

# --------------------------------------------------
# DEFAULTS (IMPORTANT)
# --------------------------------------------------
DEFAULT_EXPENSE_TYPE_ID = 1        # ✅ SAME as Claimify UI default
DEFAULT_EXPENSE_SUB_TYPE_ID = 1    # ✅ SAFE default

# --------------------------------------------------
# INTERNAL EXCEPTION
# --------------------------------------------------
class SessionExpiredError(Exception):
    pass


# --------------------------------------------------
# AUTH
# --------------------------------------------------
def login_with_phone(phone: str) -> Dict:
    resp = requests.post(
        f"{CLAIMIFY_API_BASE}/api/login",
        params={"phone": phone},
        json={"email": "", "password": ""},
        timeout=REQUEST_TIMEOUT,
    )

    resp.raise_for_status()
    data = resp.json()

    if "sessionId" not in data:
        raise RuntimeError("Login failed: sessionId missing")

    return {
        "session_id": data["sessionId"],
        "user": data.get("user"),
    }


# --------------------------------------------------
# PAYLOAD NORMALIZER (CRITICAL)
# --------------------------------------------------
def normalize_bill_payload(raw: Dict) -> Dict:
    """
    Converts OCR output → Claimify-safe Bill payload
    """

    today = date.today().isoformat()

    return {
        "expense_type_id": DEFAULT_EXPENSE_TYPE_ID,
        "expense_sub_type_id": DEFAULT_EXPENSE_SUB_TYPE_ID,

        "from_date": raw.get("invoice_date") or today,
        "to_date": raw.get("invoice_date") or today,

        "bill_amount": float(raw.get("total_amount") or 0),

        # Optional but safe
        "vat_amount": float(raw.get("vat_amount") or 0),
        "merchant_name": raw.get("merchant_name"),
        "invoice_number": raw.get("invoice_number"),
    }


# --------------------------------------------------
# CLAIM CREATE / UPDATE
# --------------------------------------------------
def create_or_update_claim(
    *,
    session_id: str,
    mode: str,              # "new" | "existing"
    emp_id: int,
    entity_id: str,
    bill_payload: Dict,
    existing_claim_no: Optional[int] = None,
) -> Dict:

    bill = normalize_bill_payload(bill_payload)

    payload = {
        "claim": {
            "claim_title": "WhatsApp Claim",
            "claim_description": "Created via WhatsApp OCR",
            "emp_id": emp_id,
            "entity_id": entity_id,
            "total_claim_amount": bill["bill_amount"],
            "claim_status": "Drafted",
        },
        "bills": [bill],
    }

    headers = {
        "X-Session-Id": session_id,
        "Content-Type": "application/json",
    }

    # UPDATE
    if mode == "existing" and existing_claim_no:
        resp = requests.put(
            f"{CLAIMIFY_API_BASE}/api/claims/{existing_claim_no}",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    else:
        resp = requests.post(
            f"{CLAIMIFY_API_BASE}/api/claims",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    if resp.status_code == 401:
        raise SessionExpiredError("Claimify session expired")

    resp.raise_for_status()
    data = resp.json()

    return {
        "claim_no": data["claim_no"],
        "bill_nos": [b["bill_no"] for b in data.get("bills", [])],
    }


# --------------------------------------------------
# ATTACH BILL FILES
# --------------------------------------------------
def upload_bill_attachments(
    *,
    session_id: str,
    claim_no: int,
    bill_no: int,
    files: List[Path],
) -> Dict:

    multipart_files = []
    open_files = []

    try:
        for f in files:
            fh = f.open("rb")
            open_files.append(fh)
            multipart_files.append(
                ("files", (f.name, fh, "application/octet-stream"))
            )

        resp = requests.post(
            f"{CLAIMIFY_API_BASE}/api/upload/server",
            params={"sessionId": session_id},
            data={
                "claim_no": claim_no,
                "bill_no": bill_no,
            },
            files=multipart_files,
            timeout=REQUEST_TIMEOUT,
        )

        if resp.status_code == 401:
            raise SessionExpiredError("Claimify session expired")

        resp.raise_for_status()
        return resp.json()

    finally:
        for fh in open_files:
            fh.close()
