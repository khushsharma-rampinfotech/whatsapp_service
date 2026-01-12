# prompt.py

# ---------------------------------------------------------
# EXPENSE TYPE → SUB-TYPE MAPPING
# ---------------------------------------------------------

EXPENSE_MAPPING = {
    "Vehicle Expenses": [
        "Fuel (Non Fuel Card)",
        "Car Clean",
        "Car Tax",
        "Car Rentals",
        "Mileage",
        "EV Charging",
        "Car Service",
        "Car Repair"
    ],

    "Client, Team and Personal Expenses": [
        "Client Entertainment",
        "Meal Allowance",
        "Food",
        "Team Meeting",
        "Customer Meals"
    ],

    "Miscellaneous": [
        "Subscriptions",
        "Stationary Expense",
        "Phone Expense",
        "Postage & Carriage"
    ],

    "Travel & Accommodation Expenses": [
        "Other Means of Travel",
        "Fuel (Non Fuel Card)",
        "Mileage",
        "Airfare",
        "Buses",
        "Parking and Tolls",
        "Taxis",
        "Rail",
        "EV Charging",
        "Accommodation"
    ],

    "Advertising & Sales Promotion": [
        "Trade Show",
        "Canopy"
    ],

    "Materials Purchased": [
        "Material Purchase"
    ]
}


# ---------------------------------------------------------
# FUNCTION: CREATE OCR PROMPT FOR MISTRAL
# ---------------------------------------------------------
def get_ocr_prompt():
    return f"""
You are an expert invoice reader. Extract information from the provided invoice image.

Return ONLY valid JSON. No explanations.

Extract these fields:

- expense_type
- expense_sub_type
- merchant_name
- invoice_number
- from_date
- to_date
- amount
- VAT

Expense Type → Sub-Type mapping:
{EXPENSE_MAPPING}

Rules:
- Always classify the correct expense_type and expense_sub_type based on product/service.
- Dates must be in DD/MM/YYYY or YYYY-MM-DD if possible.
- Amount should be numeric without currency symbol if possible.
- If something is missing, return empty string "".
"""
