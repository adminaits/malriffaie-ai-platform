from fastapi import APIRouter, HTTPException, Depends
from app.db import supabase
from app.auth import get_current_admin
from app.services.google_drive import (
    sync_google_drive_widget,
    list_drive_folders_recursive,
    extract_folder_id,
)
import httpx

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# -------------------------------------------------------------------
# Manual Knowledge Base
# -------------------------------------------------------------------

@router.post("/knowledge/manual", dependencies=[Depends(get_current_admin)])
def add_manual_knowledge(payload: dict):
    content = (payload.get("content") or "").strip()

    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    result = (
        supabase
        .table("knowledge_base")
        .insert({
            "source_type": "manual",
            "source_id": payload.get("source_id"),
            "content": content,
            "metadata": payload.get("metadata", {}),
        })
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save manual knowledge")

    return result.data[0]


# -------------------------------------------------------------------
# Google Drive
# -------------------------------------------------------------------

@router.post("/drive/sync/{widget_id}", dependencies=[Depends(get_current_admin)])
async def sync_drive_widget(widget_id: str):
    rows = (
        supabase
        .table("google_drive_widgets")
        .select("*")
        .eq("id", widget_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not rows:
        raise HTTPException(status_code=404, detail="Widget not found")

    widget = rows[0]

    result = await sync_google_drive_widget(widget)

    try:
        supabase.table("google_drive_widgets").update({
            "synced_at": "now()"
        }).eq("id", widget_id).execute()
    except Exception:
        pass

    return result


@router.get("/drive/folders/{widget_id}", dependencies=[Depends(get_current_admin)])
async def list_drive_folders(widget_id: str):
    rows = (
        supabase
        .table("google_drive_widgets")
        .select("*")
        .eq("id", widget_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not rows:
        raise HTTPException(status_code=404, detail="Widget not found")

    widget = rows[0]

    api_key = (
        widget.get("google_drive_api_key")
        or widget.get("api_key")
        or widget.get("drive_api_key")
    )

    parent_folder_id = (
        widget.get("parent_folder_id")
        or widget.get("folder_id")
        or extract_folder_id(widget.get("folder_url"))
    )

    if not api_key:
        raise HTTPException(status_code=400, detail="Google Drive API key is missing")

    if not parent_folder_id:
        raise HTTPException(status_code=400, detail="Parent folder ID or URL is missing")

    folders = await list_drive_folders_recursive(api_key, parent_folder_id)

    return {
        "ok": True,
        "parent_folder_id": parent_folder_id,
        "folders": folders,
    }


# -------------------------------------------------------------------
# Tap Payment
# -------------------------------------------------------------------

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


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}

    return bool(value)


def _tap_test_mode(settings: dict) -> bool:
    return _as_bool(settings.get("tap_test_mode"), default=True)


def _tap_secret_key(settings: dict) -> str | None:
    if _tap_test_mode(settings):
        return settings.get("tap_test_secret_key")

    return settings.get("tap_live_secret_key")


def _tap_public_key(settings: dict) -> str | None:
    if _tap_test_mode(settings):
        return settings.get("tap_test_public_key")

    return settings.get("tap_live_public_key")


def _safe_amount(value) -> float:
    try:
        amount = float(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    return amount


@router.post("/tap/checkout")
async def tap_checkout(payload: dict):
    settings = _latest_payment_settings()

    mode = settings.get("mode") or "tap"

    if mode not in {"tap", "both"}:
        raise HTTPException(status_code=400, detail="Tap payment mode is not active.")

    if not _as_bool(settings.get("tap_enabled"), default=False):
        raise HTTPException(status_code=400, detail="Tap payment is disabled.")

    secret_key = _tap_secret_key(settings)
    public_key = _tap_public_key(settings)

    if not secret_key:
        raise HTTPException(status_code=400, detail="Tap secret key is missing.")

    amount = _safe_amount(payload.get("amount"))
    currency = payload.get("currency") or "BHD"
    customer = payload.get("customer") or {}
    description = payload.get("description") or "Malriffaie payment"
    order_id = payload.get("order_id")

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

    tap_payment_mode = (settings.get("tap_payment_mode") or "charge").lower()
    tap_ui_language = settings.get("tap_ui_language") or "en"

    # Tap source:
    # src_all opens Tap-hosted payment page with supported payment methods.
    source_id = payload.get("source_id") or "src_all"

    tap_payload = {
        "amount": amount,
        "currency": currency,
        "threeDSecure": True,
        "save_card": _as_bool(settings.get("tap_save_cards"), default=False),
        "description": description,
        "statement_descriptor": "Malriffaie",
        "metadata": {
            "order_id": str(order_id or ""),
            "payment_mode": tap_payment_mode,
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
            "first_name": customer.get("first_name") or "Customer",
            "last_name": customer.get("last_name") or "",
            "email": customer.get("email") or "customer@example.com",
            "phone": {
                "country_code": customer.get("country_code") or "973",
                "number": customer.get("phone") or customer.get("number") or "00000000",
            },
        },
        "source": {
            "id": source_id,
        },
        "redirect": {
            "url": success_url,
        },
        "lang_code": tap_ui_language,
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

    checkout_url = None

    try:
        checkout_url = data.get("transaction", {}).get("url")
    except Exception:
        checkout_url = None

    return {
        "ok": True,
        "test_mode": _tap_test_mode(settings),
        "payment_id": data.get("id"),
        "status": data.get("status"),
        "checkout_url": checkout_url,
        "public_key": public_key,
        "raw": data,
    }


# -------------------------------------------------------------------
# Google Calendar Stub
# -------------------------------------------------------------------

@router.get("/calendar/availability")
def calendar_availability():
    return {
        "slots": [],
    }
