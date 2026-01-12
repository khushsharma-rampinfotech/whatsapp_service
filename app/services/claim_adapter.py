# app/services/claim_adapter.py
import os
import requests
from typing import Dict, Any

CLAIMIFY_API_BASE_URL = os.getenv("CLAIMIFY_API_BASE_URL")


class ClaimAdapter:
    @staticmethod
    def upsert_whatsapp_claim(payload: Dict[str, Any]):
        url = f"{CLAIMIFY_API_BASE_URL}/api/whatsapp/claim/upsert"

        resp = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        resp.raise_for_status()
        return resp.json()
