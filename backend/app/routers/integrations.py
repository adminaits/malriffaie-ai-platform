from fastapi import APIRouter, HTTPException, Depends
from app.db import supabase
from app.auth import get_current_admin
from app.services.google_drive import sync_google_drive_widget
import httpx

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _latest_payment_settings() -> dict:
    rows = (
        supabase
        .table("payment_settings")
        .select("*")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def _tap_secret_key(settings: dict) -> str | None:
    test_mode = settings.get("tap_test_mode", True)

    if test_mode:
        return settings.get("tap_test_secret_key")

    return settings.get("tap_live_secret_key")


def _tap_public_key(settings: dict) -> str | None:
    test_mode = settings.get("tap_test_mode", True)

    if test_mode:
        return settings.get("tap_test_public_key")

    return settings.get("tap_live_public_key")


@router.post("/tap/checkout")
async def tap_checkout(payload: dict):
    settings = _latest_payment_settings()

    if not settings.get("tap_enabled", False):
        raise HTTPException(status_code=400, detail="Tap payment is disabled.")

    secret_key = _tap_secret_key(settings)
    public_key = _tap_public_key(settings)

    if not secret_key:
        raise HTTPException(status_code=400, detail="Tap secret key is missing.")

    amount = payload.get("amount")
    currency = payload.get("currency", "BHD")
    customer = payload.get("customer", {})
    description = payload.get("description", "Malriffaie payment")
    order_id = payload.get("order_id")

    if not amount:
        raise HTTPException(status_code=400, detail="amount is required")

    success_url = (
        settings.get("tap_success_url")
        or payload.get("success_url")
        or "https://malriffaie-ai-platform-frontend-git-main-aitss-projects.vercel.app/payment-success"
    )

    failure_url = (
        settings.get("tap_failure_url")
        or payload.get("failure_url")
        or "https://malriffaie-ai-platform-frontend-git-main-aitss-projects.vercel.app/payment-failed"
    )

    post_url = settings.get("tap_post_url") or payload.get("post_url")

    tap_payload = {
        "amount": float(amount),
        "currency": currency,
        "threeDSecure": True,
        "save_card": bool(settings.get("tap_save_cards", False)),
        "description": description,
        "statement_descriptor": "Malriffaie",
        "metadata": {
            "order_id": order_id,
        },
        "reference": {
            "transaction": str(order_id or ""),
            "order": str(order_id or ""),
        },
        "receipt": {
            "email": True,
            "sms": False,
        },
        "customer": {
            "first_name": customer.get("first_name", "Customer"),
            "last_name": customer.get("last_name", ""),
            "email": customer.get("email", "customer@example.com"),
            "phone": {
                "country_code": customer.get("country_code", "973"),
                "number": customer.get("phone", "00000000"),
            },
        },
        "source": {
            "id": "src_all",
        },
        "redirect": {
            "url": success_url,
        },
    }

    if post_url:
        tap_payload["post"] = {
            "url": post_url,
        }

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.tap.company/v2/charges",
            headers=headers,
            json=tap_payload,
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    data = response.json()

    payment_url = None

    try:
        payment_url = data.get("transaction", {}).get("url")
    except Exception:
        payment_url = None

    return {
        "ok": True,
        "payment_id": data.get("id"),
        "status": data.get("status"),
        "checkout_url": payment_url,
        "public_key": public_key,
        "raw": data,
    }
