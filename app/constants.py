# app/constants.py

# -----------------------------
# Services
# -----------------------------
SERVICE_CLAIM = "CLAIM"
SERVICE_GRN = "GRN"

# -----------------------------
# Redis States
# -----------------------------
STATE_WAITING_FOR_SERVICE = "WAITING_FOR_SERVICE"
STATE_WAITING_FOR_ENTITY = "WAITING_FOR_ENTITY"
STATE_WAITING_FOR_IMAGE_COUNT = "WAITING_FOR_IMAGE_COUNT"
STATE_WAITING_FOR_IMAGES = "WAITING_FOR_IMAGES"
STATE_WAITING_FOR_CLAIM_CHOICE = "WAITING_FOR_CLAIM_CHOICE"
STATE_WAITING_FOR_ADD_ANOTHER = "WAITING_FOR_ADD_ANOTHER"
STATE_WAITING_FOR_GRN_UPLOAD = "WAITING_FOR_GRN_UPLOAD"

# -----------------------------
# Redis TTL (seconds)
# -----------------------------
CHAT_TTL = 900
