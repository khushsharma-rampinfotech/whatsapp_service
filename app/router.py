# app/router.py

from app.constants import SERVICE_CLAIM, SERVICE_GRN


def get_services_for_phone(phone: str) -> list[str]:
    """
    TEMP: hardcoded for testing
    Will be replaced with DB query later
    """

    # Your number → both services
    if phone.endswith("6247"):
        return [SERVICE_CLAIM, SERVICE_GRN]

    # Example GRN-only user
    if phone.endswith("1111"):
        return [SERVICE_GRN]

    # Default → claim only
    return [SERVICE_CLAIM]
   