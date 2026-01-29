import os
import requests
import tempfile
import json
from dotenv import load_dotenv
from pdf2image import convert_from_path
from PIL import Image

from prompt.ocr_prompt import get_ocr_prompt
  # ✅ ADD PROMPT

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    raise ValueError("❌ MISTRAL_API_KEY missing in .env")

OCR_UPLOAD_URL = "https://api.mistral.ai/v1/files"
OCR_PROCESS_URL = "https://api.mistral.ai/v1/ocr"
CHAT_COMPLETIONS_URL = "https://api.mistral.ai/v1/chat/completions"


# ============================================================
# INTERNAL: OCR SINGLE IMAGE
# ============================================================
def _ocr_image(image_path: str) -> dict:
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}"}

    if image_path.lower().endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif image_path.lower().endswith(".png"):
        mime = "image/png"
    else:
        mime = "application/octet-stream"

    with open(image_path, "rb") as f:
        files = {"file": (os.path.basename(image_path), f, mime)}
        data = {"purpose": "ocr"}

        upload_res = requests.post(
            OCR_UPLOAD_URL, headers=headers, files=files, data=data
        )
        upload_res.raise_for_status()

    file_id = upload_res.json()["id"]
    print("📤 Uploaded to Mistral OCR → File ID:", file_id)

    payload = {
        "model": "mistral-ocr-latest",
        "document": {"file_id": file_id},
    }

    ocr_res = requests.post(
        OCR_PROCESS_URL, headers=headers, json=payload
    )
    ocr_res.raise_for_status()

    result = ocr_res.json()
    pages = result.get("pages", [])
    raw_text = "\n\n".join(p.get("markdown", "") for p in pages)

    print("🔍 FULL OCR RESPONSE:", result)

    return {
        "raw_text": raw_text,
        "pages": pages,
    }


# ============================================================
# INTERNAL: STRUCTURED EXTRACTION (RESTORED LLM STEP)
# ============================================================
def _extract_structured_data(raw_text: str, expense_mapping: dict) -> dict:
    if not raw_text.strip():
        return {}

    prompt = get_ocr_prompt(expense_mapping) + "\n\nText:\n" + raw_text
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "mistral-large-latest",   # ✅ SAME AS OLD WORKING FLOW
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0,
    }

    res = requests.post(
        CHAT_COMPLETIONS_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )
    res.raise_for_status()

    content = res.json()["choices"][0]["message"]["content"].strip()

    print("🧠 RAW LLM OUTPUT:", content)

    # Strip ```json fences if present
    if content.startswith("```"):
        content = "\n".join(
            line for line in content.splitlines()
            if not line.strip().startswith("```")
        )

    try:
        structured = json.loads(content)
        print("🧠 STRUCTURED OCR:", structured)
        return structured
    except Exception as e:
        print("❌ Failed to parse structured JSON:", e)
        return {}


# ============================================================
# INTERNAL: PDF → IMAGE CONVERSION
# ============================================================
def _convert_pdf_to_images(pdf_path: str) -> list[str]:
    tmp_dir = tempfile.mkdtemp(prefix="pdf_pages_")
    pages = convert_from_path(pdf_path, dpi=300)

    image_paths = []
    for idx, page in enumerate(pages):
        image_path = os.path.join(tmp_dir, f"page_{idx+1}.png")
        page.save(image_path, "PNG")
        image_paths.append(image_path)

    print(f"📄 PDF converted to {len(image_paths)} image(s)")
    return image_paths


# ============================================================
# PUBLIC: RUN INVOICE OCR (FINAL)
# ============================================================
def run_invoice_ocr(file_path: str, expense_mapping: dict) -> dict:
    """
    Returns:
    { 
        raw_text: str,
        structured: dict,
        model: str
    }
    """

    # -------- PDF FLOW --------
    if file_path.lower().endswith(".pdf"):
        print("📄 Detected PDF invoice")
        image_paths = _convert_pdf_to_images(file_path)

        combined_text = []
        for img in image_paths:
            result = _ocr_image(img)
            if result.get("raw_text"):
                combined_text.append(result["raw_text"])

        raw_text = "\n\n".join(combined_text)

    # -------- IMAGE FLOW --------
    else:
        result = _ocr_image(file_path)
        raw_text = result.get("raw_text", "")

    structured = _extract_structured_data(raw_text, expense_mapping)

    if not structured:
        print("⚠️ OCR EMPTY — USING FALLBACK VALUES")

    return {
        "raw_text": raw_text,
        "structured": structured,
        "model": "mistral-ocr-latest + mistral-large-latest",
    }
