# app/handler.py

import os
import json
import threading
from datetime import datetime
from pathlib import Path

import requests
import pyodbc
from dotenv import load_dotenv

from utils.redis_client import redis_client
from app.constants import *
from app.router import get_services_for_phone

# ---------------- CLAIM IMPORTS ----------------
from app.services.claim_adapter import (
    login_with_phone,
    upload_bill_attachments,
    SessionExpiredError,
)
from ocr.mistral_ocr import run_invoice_ocr

# ---------------- GRN IMPORTS ----------------
from app.services.grn_adapter import extract_grn



load_dotenv()

# --------------------------------------------------
# ENV
# --------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
BASE_URL = os.getenv("WHATSAPP_BASE_URL", "https://graph.facebook.com/v20.0")
CLAIMIFY_API_BASE = os.getenv("CLAIMIFY_API_BASE")

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
    
    requests.post(
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

# --------------------------------------------------
# DB HELPERS (CLAIM)
# --------------------------------------------------
# --------------------------------------------------
def fetch_expense_mapping(schema):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT
            et.expense_type_name,
            est.expense_sub_type_name
        FROM [{schema}].[ExpenseType] et
        JOIN [{schema}].[ExpenseSubType] est
            ON est.expense_type_id = et.expense_type_id
        WHERE est.is_disabled = 0
        ORDER BY et.expense_type_name, est.expense_sub_type_name
        """
    )

    mapping = {}
    for et_name, est_name in cur.fetchall():
        mapping.setdefault(et_name, []).append(est_name)

    cur.close()
    conn.close()
    return mapping
# --------------------------------------------------
def resolve_expense_ids(schema, expense_type, expense_sub_type):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT
            est.expense_type_id,
            est.expense_sub_type_id
        FROM [{schema}].[ExpenseSubType] est
        JOIN [{schema}].[ExpenseType] et
            ON et.expense_type_id = est.expense_type_id
        WHERE
            et.expense_type_name = ?
            AND est.expense_sub_type_name = ?
            AND est.is_disabled = 0
        """,
        expense_type,
        expense_sub_type,
    )

    row = cur.fetchone()
    cur.close()
    conn.close()
    return (row.expense_type_id, row.expense_sub_type_id) if row else (None, None)
# --------------------------------------------------
def fetch_entities_for_employee(emp_no: int):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            eem.entity_id,
            em.entity_name
        FROM product.EmployeeEntityMapping eem
        JOIN zeus_t1.EntityMaster em
            ON em.entity_id = eem.entity_id
        WHERE eem.emp_no = ?
          AND (eem.is_disabled = 0 OR eem.is_disabled IS NULL)
          AND em.deleted_on IS NULL
        ORDER BY em.entity_name
        """,
        emp_no,
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"entity_id": r.entity_id, "entity_name": r.entity_name}
        for r in rows
    ]

def fetch_employee_context(phone: str):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT emp_no, tenant_id
        FROM [product].[EmployeeMaster]
        WHERE (country_code + phone_number) = ?
          AND (is_disabled IS NULL OR is_disabled = 0)
        """,
        phone,
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return (int(row.emp_no), row.tenant_id) if row else (None, None)

def get_latest_drafted_claim(schema, emp_no, entity_id):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT TOP 1 claim_no
        FROM [{schema}].[Claims]
        WHERE emp_id = ?
          AND entity_id = ?
          AND claim_status = 'Drafted'
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY created_on DESC
        """,
        emp_no,
        entity_id,
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return int(row.claim_no) if row else None

def resolve_expense_type_ids(schema):
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT TOP 1 expense_type_id, expense_sub_type_id
        FROM [{schema}].[ExpenseSubType]
        ORDER BY expense_sub_type_id
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row.expense_type_id, row.expense_sub_type_id

def normalize_date(date_str):
    if not date_str:
        return None
    try:
        if "/" in date_str:
            return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return None

# --------------------------------------------------
# GRN ASYNC
# --------------------------------------------------
def process_grn_async(phone, path, reply_to):
    try:
        result = extract_grn(path)
        if result.get("sharepoint_url") and result.get("database_status") == "Success":
            send_whatsapp_reply(
                phone,
                "✅ *GRN processed successfully*\n• Uploaded\n• Database updated",
                reply_to,
            )
        else:
            send_whatsapp_reply(
                phone,
                "⚠️ GRN received but could not be fully processed.",
                reply_to,
            )
    except Exception:
        send_whatsapp_reply(
            phone,
            "❌ Failed to process GRN.",
            reply_to,
        )
    finally:
        clear_session(phone)

# --------------------------------------------------
# CLAIM OCR
# --------------------------------------------------
def process_claim_async(phone, reply_to):
    try:
        images = redis_client.lrange(rkey(phone, "images"), 0, -1)
        emp_no = int(redis_client.get(rkey(phone, "emp_no")))
        schema = redis_client.get(rkey(phone, "schema"))
        entity_id = redis_client.get(rkey(phone, "entity_id"))

        # 🔹 FETCH DYNAMIC EXPENSE MAPPING (ONCE PER CLAIM)
        expense_mapping = fetch_expense_mapping(schema)

        # ---------- OCR ----------
        extracted = []
        for img in images:
            result = run_invoice_ocr(
                img,
                expense_mapping=expense_mapping
            )
            extracted.append(result.get("structured") or {})

        redis_client.setex(
            rkey(phone, "extracted_bills"),
            CHAT_TTL,
            json.dumps(extracted),
        )

        # ---------- 🔥 IMPORTANT FIX ----------
        # If a claim is already active, DO NOT ask draft question again.
        active_claim = redis_client.get(rkey(phone, "active_claim_no"))

        if active_claim:
            # Reuse same claim and auto-commit
            redis_client.setex(
                rkey(phone, "draft_claim_no"),
                CHAT_TTL,
                int(active_claim),
            )

            threading.Thread(
                target=commit_claim,
                args=(phone, "1", reply_to),  # force "Add to existing"
                daemon=True,
            ).start()
            return

        # ---------- FIRST INVOICE ONLY ----------
        draft = get_latest_drafted_claim(schema, emp_no, entity_id)
        redis_client.setex(rkey(phone, "draft_claim_no"), CHAT_TTL, draft or "")

        redis_client.setex(
            rkey(phone, "state"),
            CHAT_TTL,
            STATE_WAITING_FOR_CLAIM_CHOICE,
        )

        send_whatsapp_reply(
            phone,
            f"📝 Draft claim found (Claim No: {draft})\n1️⃣ Add to existing\n2️⃣ Create new"
            if draft else
            "ℹ️ No draft claim found\n2️⃣ Create new claim",
            reply_to,
        )

    except Exception as e:
        send_whatsapp_reply(
            phone,
            f"❌ OCR failed.\n{e}",
            reply_to,
        )


# --------------------------------------------------
# CLAIM COMMIT (FINAL STEP)
# --------------------------------------------------
def commit_claim(phone, choice, reply_to):
    try:
        emp_no = int(redis_client.get(rkey(phone, "emp_no")))
        schema = redis_client.get(rkey(phone, "schema"))
        entity_id = redis_client.get(rkey(phone, "entity_id"))

        bills = json.loads(redis_client.get(rkey(phone, "extracted_bills")))
        images = redis_client.lrange(rkey(phone, "images"), 0, -1)

        draft_raw = redis_client.get(rkey(phone, "draft_claim_no"))
        draft_claim_no = int(draft_raw) if draft_raw else None

        # 🔐 Login
        auth = login_with_phone(phone)
        session_id = auth["session_id"]

        prepared_bills = []
        invoice_amount = 0.0  # amount for THIS upload only

        for bill in bills:
            amount = float(bill.get("amount") or 0)
            invoice_amount += amount

            from_date = normalize_date(bill.get("from_date"))
            to_date = normalize_date(bill.get("to_date")) or from_date

            # ✅ NEW: resolve expense IDs PER BILL from OCR output
            expense_type = bill.get("expense_type")
            expense_sub_type = bill.get("expense_sub_type")

            et_id, est_id = resolve_expense_ids(
                schema,
                expense_type,
                expense_sub_type,
            )

            if not et_id or not est_id:
                raise Exception(
                    f"Invalid expense mapping: {expense_type} → {expense_sub_type}"
                )

            prepared_bills.append({
                "expense_type_id": et_id,
                "expense_sub_type_id": est_id,
                "from_date": from_date,
                "to_date": to_date,
                "bill_amount": amount,
                "merchant_name": bill.get("merchant_name"),
                "invoice_number": bill.get("invoice_number"),
            })

        payload = {
            "claim": {
                "claim_title": "WhatsApp Claim",
                "claim_description": "Created via WhatsApp",
                "emp_id": emp_no,
                "entity_id": entity_id,
                "total_claim_amount": invoice_amount,
                "claim_status": "Drafted",
            },
            "bills": prepared_bills,
        }

        headers = {
            "X-Session-Id": session_id,
            "Content-Type": "application/json",
        }

        # 🔥 POST vs PUT
        if choice == "1" and draft_claim_no:
            resp = requests.put(
                f"{CLAIMIFY_API_BASE}/api/claims/{draft_claim_no}",
                json=payload,
                headers=headers,
                timeout=60,
            )
        else:
            resp = requests.post(
                f"{CLAIMIFY_API_BASE}/api/claims",
                json=payload,
                headers=headers,
                timeout=60,
            )

        if resp.status_code != 200:
            raise Exception(resp.text)

        data = resp.json()
        claim_no = data["claim_no"]

        # 🔹 Authoritative total from backend
        total_claim_amount = (
            data.get("claim", {}).get("total_claim_amount")
            or data.get("total_claim_amount")
        )

        # ✅ Attach invoice images
        for bill in data["bills"]:
            upload_bill_attachments(
                session_id=session_id,
                claim_no=claim_no,
                bill_no=bill["bill_no"],
                files=[Path(p) for p in images],
            )

        # 🔹 Format amounts
        invoice_text = f"🧾 Invoice Amount: ₹ {invoice_amount:,.2f}"
        total_text = (
            f"\n💰 Total Claim Amount: ₹ {float(total_claim_amount):,.2f}"
            if total_claim_amount is not None
            else ""
        )

        # 🔁 Ask user to add more invoices
        send_whatsapp_reply(
            phone,
            f"✅ Invoice attached successfully\n"
            f"📄 Claim No: {claim_no}\n"
            f"{invoice_text}"
            f"{total_text}\n\n"
            "Do you want to add another invoice?\n"
            "1️⃣ Yes\n"
            "2️⃣ Done",
            reply_to,
        )

        # 🔹 Persist active claim
        redis_client.setex(
            rkey(phone, "active_claim_no"),
            CHAT_TTL,
            claim_no,
        )

        # 🔹 Move to add-more decision state
        redis_client.setex(
            rkey(phone, "state"),
            CHAT_TTL,
            STATE_WAITING_FOR_ADD_MORE,
        )

    except Exception as e:
        send_whatsapp_reply(
            phone,
            f"❌ Failed to save claim\n{e}",
            reply_to,
        )




# --------------------------------------------------
# MAIN HANDLER
# --------------------------------------------------
def handle_whatsapp_incoming(data):
    msg = data["entry"][0]["changes"][0]["value"].get("messages", [None])[0]
    if not msg:
        return

    sender = msg["from"]  # full WhatsApp number (e.g. 919119166247)
    msg_id = msg["id"]
    msg_type = msg["type"]
    state = redis_client.get(rkey(sender, "state"))

    # ---------------- TEXT ----------------
    if msg_type == "text":
        text = msg["text"]["body"].strip().lower()

        # ---- START ----
        if text in ("hi", "start"):
            clear_session(sender)

            emp_no, tenant = fetch_employee_context(sender)
            if not emp_no:
                send_whatsapp_reply(sender, "❌ User not found.", msg_id)
                return

            redis_client.setex(rkey(sender, "emp_no"), CHAT_TTL, emp_no)
            redis_client.setex(rkey(sender, "schema"), CHAT_TTL, tenant)

            # 🔥 Fetch enabled services (DB stores full WhatsApp number)
            services = get_services_for_phone(sender)
            service_set = set(services)

            # 🚨 HARD GUARD — no silent fallback
            if not service_set:
                send_whatsapp_reply(
                    sender,
                    "❌ You are not enabled for any service.",
                    msg_id,
                )
                return

            # ---- ONLY GRN ----
            if service_set == {"GRN"}:
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

            # ---- ONLY CLAIM ----
            if service_set == {"CLAIM"}:
                entities = fetch_entities_for_employee(emp_no)
                if not entities:
                    send_whatsapp_reply(
                        sender,
                        "❌ You are not mapped to any entity. Please contact support.",
                        msg_id,
                    )
                    clear_session(sender)
                    return

                redis_client.setex(
                    rkey(sender, "entities"),
                    CHAT_TTL,
                    json.dumps(entities),
                )
                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_ENTITY,
                )

                lines = ["Select entity:"]
                for idx, e in enumerate(entities, start=1):
                    lines.append(f"{idx}️⃣ {e['entity_name']}")

                send_whatsapp_reply(sender, "\n".join(lines), msg_id)
                return

            # ---- BOTH (CLAIM + GRN) ----
            if service_set == {"CLAIM", "GRN"}:
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

            # ---- SAFETY NET (should never hit) ----
            send_whatsapp_reply(
                sender,
                "❌ Invalid service configuration. Please contact support.",
                msg_id,
            )
            return

        # ---- SERVICE SELECTION (ONLY for dual-service users) ----
        if state == STATE_WAITING_FOR_SERVICE:
            if text == "1":
                emp_no = int(redis_client.get(rkey(sender, "emp_no")))
                entities = fetch_entities_for_employee(emp_no)

                if not entities:
                    send_whatsapp_reply(
                        sender,
                        "❌ You are not mapped to any entity. Please contact support.",
                        msg_id,
                    )
                    clear_session(sender)
                    return

                redis_client.setex(
                    rkey(sender, "entities"),
                    CHAT_TTL,
                    json.dumps(entities),
                )
                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_ENTITY,
                )

                lines = ["Select entity:"]
                for idx, e in enumerate(entities, start=1):
                    lines.append(f"{idx}️⃣ {e['entity_name']}")

                send_whatsapp_reply(sender, "\n".join(lines), msg_id)
                return

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

        # ---- ENTITY ----
        if state == STATE_WAITING_FOR_ENTITY:
            entities_raw = redis_client.get(rkey(sender, "entities"))
            if not entities_raw:
                send_whatsapp_reply(sender, "⚠️ Session expired. Please type Hi.", msg_id)
                clear_session(sender)
                return

            entities = json.loads(entities_raw)
            try:
                idx = int(text) - 1
                entity_id = entities[idx]["entity_id"]
            except (ValueError, IndexError):
                send_whatsapp_reply(
                    sender,
                    "❌ Invalid selection. Please choose a valid number.",
                    msg_id,
                )
                return

            redis_client.setex(rkey(sender, "entity_id"), CHAT_TTL, entity_id)
            redis_client.setex(
                rkey(sender, "state"),
                CHAT_TTL,
                STATE_WAITING_FOR_IMAGE_COUNT,
            )

            send_whatsapp_reply(
                sender,
                "How many images does this invoice have?",
                msg_id,
            )
            return

        # ---- IMAGE COUNT ----
        if state == STATE_WAITING_FOR_IMAGE_COUNT:
            redis_client.setex(rkey(sender, "expected_images"), CHAT_TTL, int(text))
            redis_client.setex(rkey(sender, "received_images"), CHAT_TTL, 0)
            redis_client.delete(rkey(sender, "images"))

            redis_client.setex(
                rkey(sender, "state"),
                CHAT_TTL,
                STATE_WAITING_FOR_IMAGES,
            )

            send_whatsapp_reply(
                sender,
                f"Please send {text} invoice image(s).",
                msg_id,
            )
            return

        # ---- CLAIM CHOICE ----
        if state == STATE_WAITING_FOR_CLAIM_CHOICE and text in ("1", "2"):
            threading.Thread(
                target=commit_claim,
                args=(sender, text, msg_id),
                daemon=True,
            ).start()
            return

        # ---- ADD ANOTHER INVOICE ----
        if state == STATE_WAITING_FOR_ADD_MORE:
            if text in ("1", "yes"):
                redis_client.delete(rkey(sender, "images"))
                redis_client.delete(rkey(sender, "expected_images"))
                redis_client.delete(rkey(sender, "received_images"))

                redis_client.setex(
                    rkey(sender, "state"),
                    CHAT_TTL,
                    STATE_WAITING_FOR_IMAGE_COUNT,
                )

                send_whatsapp_reply(
                    sender,
                    "How many images does this invoice have?",
                    msg_id,
                )
                return

            if text in ("2", "done"):
                send_whatsapp_reply(
                    sender,
                    "✅ Claim completed. Thank you!",
                    msg_id,
                )
                clear_session(sender)
                return

    # ---------------- CLAIM MEDIA ----------------
    if msg_type in ("image", "document") and state == STATE_WAITING_FOR_IMAGES:
        media = msg.get("image") or msg.get("document")
        media_id = media["id"]

        meta = requests.get(
            f"{BASE_URL}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        ).json()

        content = requests.get(
            meta["url"],
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        ).content

        path = TMP_DIR / f"{sender}_{datetime.utcnow().timestamp()}.jpg"
        path.write_bytes(content)

        redis_client.rpush(rkey(sender, "images"), str(path))
        received = redis_client.incr(rkey(sender, "received_images"))
        expected = int(redis_client.get(rkey(sender, "expected_images")))

        if received >= expected:
            send_whatsapp_reply(sender, "⏳ Processing invoices…", msg_id)
            threading.Thread(
                target=process_claim_async,
                args=(sender, msg_id),
                daemon=True,
            ).start()
        else:
            send_whatsapp_reply(
                sender,
                f"📎 Invoice {received}/{expected} received",
                msg_id,
            )
        return

    # ---------------- GRN MEDIA ----------------
    if msg_type in ("image", "document") and state == STATE_WAITING_FOR_GRN_UPLOAD:
        media = msg.get("image") or msg.get("document")
        media_id = media["id"]
        mime = media.get("mime_type", "")

        meta = requests.get(
            f"{BASE_URL}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        ).json()

        content = requests.get(
            meta["url"],
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        ).content

        ext = ".pdf" if mime == "application/pdf" else ".jpg"
        path = TMP_DIR / f"{sender}_{datetime.utcnow().timestamp()}{ext}"
        path.write_bytes(content)

        send_whatsapp_reply(sender, "⏳ Processing GRN…", msg_id)

        threading.Thread(
            target=process_grn_async,
            args=(sender, path, msg_id),
            daemon=True,
        ).start()
        return


