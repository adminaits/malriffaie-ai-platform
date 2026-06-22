from fastapi import APIRouter, HTTPException, Depends
from app.db import supabase
import httpx
from app.auth import get_current_admin

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

@router.post("/knowledge/manual", dependencies=[Depends(get_current_admin)])
def add_manual_knowledge(payload: dict):
    content = payload.get("content", "").strip()
    if not content:
        raise HTTPException(400, "content is required")
    return supabase.table("knowledge_base").insert({"source_type": "manual", "content": content, "metadata": payload.get("metadata", {})}).execute().data[0]

@router.post("/drive/sync/{widget_id}", dependencies=[Depends(get_current_admin)])
def sync_drive_widget(widget_id: str):
    # Production note: use Google Drive OAuth/service account, download docs/PDFs, chunk, embed, and insert into knowledge_base.
    widget = supabase.table("google_drive_widgets").select("*").eq("id", widget_id).single().execute().data
    if not widget:
        raise HTTPException(404, "Widget not found")
    supabase.table("google_drive_widgets").update({"synced_at": "now()"}).eq("id", widget_id).execute()
    return {"ok": True, "message": "Stub sync complete. Add Google Drive extraction in services/google_drive.py."}

@router.post("/tap/checkout")
async def tap_checkout(payload: dict):
    # Production note: create Tap charge here using TAP_SECRET_KEY.
    return {"ok": True, "checkout_url": None, "message": "Tap checkout stub. Connect Tap API credentials."}

@router.get("/calendar/availability")
def calendar_availability():
    # Production note: call Google Calendar freebusy endpoint with saved calendar settings.
    return {"slots": []}
