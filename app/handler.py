# app/handler.py

import os
import threading
from datetime import datetime
from pathlib import Path
import json

import requests
from dotenv import load_dotenv

from utils.redis_client import redis_client
from app.router import get_services_for_phone
from app.constants import *
from app.services.grn_adapter import extract_grn

load_dotenv()

# --------------------------------------------------
# ENV
# --------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
BASE_URL = os.getenv("WHATSAPP_BASE_URL", "https://graph.facebook.com/v20.0")

# --------------------------------------------------
# STORAGE
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "uploads"
TMP_DIR = UPLOAD_DIR / "_tmp"

UPLOAD_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

# --------------------------------------------------
# REDIS HELPERS
# --------------------------------------------------
def rkey(phone: str, key: str) -> str:
    return f"wa:{phone}:{key}"


def clear_session(phone: str):
    for k in redis_client.scan_iter(f"wa:{phone}:*"):
        redis_client.delete(k)

# --------------------------------------------------
# WHATSAPP SENDER
# --------------------------------------------------
def send_whatsapp_reply(to: str, text: str, reply_to: str):
    resp = requests.post(
        f"{BASE_URL}/{PHONE_NUMBER_ID}/messages",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "context": {"message_id": reply_to},
            "text": {"body": text},
        },
        timeout=10,
    )

    if resp.status_code >= 400:
        print("❌ WhatsApp send error:", resp.status_code, resp.text)

# --------------------------------------------------
# GRN ASYNC PROCESSOR
# --------------------------------------------------
def process_grn_async(phone: str, file_path: Path, reply_to: str):
    try:
        print("Sending file to GRN API:", file_path)

        result = extract_grn(file_path)
        print("GRN RESULT RECEIVED")

        sharepoint_url = result.get("sharepoint_url")
        database_status = result.get("database_status")

        # ✅ SUCCESS CASE
        if sharepoint_url and database_status == "Success":
            send_whatsapp_reply(
                phone,
                "✅ *GRN processed successfully*\n\n"
                "• Document uploaded to system\n"
                "• Database updated successfully",
                reply_to,
            )
            return

        # ❌ PARTIAL / FAILED CASE
        send_whatsapp_reply(
            phone,
            "⚠️ GRN received but could not be fully processed.\n"
            "Please contact support if this persists.",
            reply_to,
        )

    except requests.exceptions.ReadTimeout:
        send_whatsapp_reply(
            phone,
            "⏳ GRN received successfully.\n"
            "Processing is taking longer than usual.\n"
            "You will be notified once completed.",
            reply_to,
        )

    except Exception as e:
        print("GRN ERROR:", str(e))
        send_whatsapp_reply(
            phone,
            "❌ Failed to process GRN.\nPlease try again later.",
            reply_to,
        )

    finally:
        clear_session(phone)


# --------------------------------------------------
# MAIN HANDLER
# --------------------------------------------------
def handle_whatsapp_incoming(data):
    msg = data["entry"][0]["changes"][0]["value"].get("messages", [None])[0]
    if not msg:
        return

    sender = msg["from"]
    msg_id = msg["id"]
    state = redis_client.get(rkey(sender, "state"))

    # =======================
    # TEXT
    # =======================
    if msg["type"] == "text":
        text = msg["text"]["body"].strip().lower()

        if text in ("hi", "start"):
            clear_session(sender)

            services = get_services_for_phone(sender)
            print("📞 Services for", sender, "=>", services)

            if not services:
                send_whatsapp_reply(
                    sender,
                    "❌ You are not enabled for any service.",
                    msg_id,
                )
                return

            if "CLAIM" in services and "GRN" in services:
                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_SERVICE,
                )
                send_whatsapp_reply(
                    sender,
                    "Which service do you want?\n"
                    "1️⃣ Claim Reimbursement\n"
                    "2️⃣ GRN",
                    msg_id,
                )
                return

            if "GRN" in services:
                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_GRN_UPLOAD,
                )
                send_whatsapp_reply(
                    sender,
                    "📎 Please send GRN image or PDF.",
                    msg_id,
                )
                return

            send_whatsapp_reply(
                sender,
                "❌ You are not enabled for GRN service.",
                msg_id,
            )
            return

        # ---- SERVICE SELECTION ----
        if state == STATE_WAITING_FOR_SERVICE:
            if text == "2":
                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_GRN_UPLOAD,
                )
                send_whatsapp_reply(
                    sender,
                    "📎 Please send GRN image or PDF.",
                    msg_id,
                )
                return

            if text == "1":
                send_whatsapp_reply(
                    sender,
                    "⚠️ Claim Reimbursement is temporarily unavailable.",
                    msg_id,
                )
                clear_session(sender)
                return

            send_whatsapp_reply(sender, "Reply 1 or 2 only.", msg_id)
            return

    # =======================
    # IMAGE / DOCUMENT
    # =======================
    if msg["type"] in ("image", "document"):
        if state != STATE_WAITING_FOR_GRN_UPLOAD:
            send_whatsapp_reply(
                sender,
                "⚠️ Please type *Hi* to start.",
                msg_id,
            )
            return

        media = msg.get("image") or msg.get("document")
        media_id = media["id"]
        mime_type = media.get("mime_type", "")

        # ---- Fetch media URL ----
        meta = requests.get(
            f"{BASE_URL}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10,
        ).json()

        # ---- Download media ----
        content = requests.get(
            meta["url"],
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Accept": "application/pdf, image/*",
            },
            timeout=30,
        ).content

        # ---- Correct extension ----
        if mime_type == "application/pdf":
            ext = ".pdf"
        else:
            ext = ".jpg"

        path = TMP_DIR / f"{sender}_{datetime.utcnow().timestamp()}{ext}"
        path.write_bytes(content)

        print("📥 Saved file:", path, "size:", path.stat().st_size)

        send_whatsapp_reply(sender, "⏳ Processing GRN…", msg_id)

        threading.Thread(
            target=process_grn_async,
            args=(sender, path, msg_id),
            daemon=True,
        ).start()
