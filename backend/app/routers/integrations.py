from fastapi import APIRouter, HTTPException, Depends
from app.db import supabase
from app.auth import get_current_admin
from app.services.google_drive import sync_google_drive_widget

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.post("/knowledge/manual", dependencies=[Depends(get_current_admin)])
def add_manual_knowledge(payload: dict):
    content = payload.get("content", "").strip()

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


@router.post("/tap/checkout")
async def tap_checkout(payload: dict):
    # Production note:
    # Connect this to Tap Payments API using TAP_SECRET_KEY in Render environment variables.
    return {
        "ok": True,
        "checkout_url": None,
        "message": "Tap checkout stub. Connect Tap API credentials.",
    }


@router.get("/calendar/availability")
def calendar_availability():
    # Production note:
    # Connect this to Google Calendar freebusy endpoint using saved calendar settings.
    return {
        "slots": [],
    }
