# app/main.py

import os
import threading
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
from dotenv import load_dotenv

from app.handler import handle_whatsapp_incoming

load_dotenv()

app = FastAPI(title="WhatsApp Microservice")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_verify_token")

# --------------------------------------------------
# Webhook verification (Meta)
# --------------------------------------------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ WhatsApp webhook verified")
        return PlainTextResponse(content=challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


# --------------------------------------------------
# Receive WhatsApp messages
# --------------------------------------------------
@app.post("/webhook")
async def receive_message(request: Request):
    try:
        data = await request.json()
        print("📩 Incoming webhook:", data)

        # Run handler in background thread
        thread = threading.Thread(
            target=handle_whatsapp_incoming,
            args=(data,),
            daemon=True,
        )
        thread.start()

        # Immediate ACK to Meta
        return JSONResponse({"status": "accepted"})

    except Exception as e:
        print("❌ Webhook error:", e)
        raise HTTPException(status_code=500, detail=str(e))
