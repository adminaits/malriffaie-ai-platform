import httpx
from app.db import supabase


GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


def extract_folder_id(folder_url_or_id: str | None) -> str:
    if not folder_url_or_id:
        return ""

    value = folder_url_or_id.strip()

    if "/folders/" in value:
        return value.split("/folders/")[1].split("?")[0].split("/")[0]

    return value


async def list_drive_files(api_key: str, folder_id: str) -> list[dict]:
    query = f"'{folder_id}' in parents and trashed = false"

    params = {
        "key": api_key,
        "q": query,
        "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
        "pageSize": 100,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)

    response.raise_for_status()
    return response.json().get("files", [])


async def download_drive_file_text(api_key: str, file: dict) -> str:
    file_id = file.get("id")
    mime_type = file.get("mimeType")

    if not file_id:
        return ""

    async with httpx.AsyncClient(timeout=60) as client:
        if mime_type == "application/vnd.google-apps.document":
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
            response = await client.get(
                url,
                params={
                    "key": api_key,
                    "mimeType": "text/plain",
                },
            )

        elif mime_type == "text/plain":
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            response = await client.get(
                url,
                params={
                    "key": api_key,
                    "alt": "media",
                },
            )

        else:
            return ""

    if response.status_code >= 400:
        return ""

    return response.text.strip()


async def upsert_knowledge_base_from_drive_file(file: dict, content: str) -> None:
    source_id = file.get("id")

    if not source_id or not content:
        return

    existing = (
        supabase
        .table("knowledge_base")
        .select("id")
        .eq("source_type", "google_drive")
        .eq("source_id", source_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    payload = {
        "source_type": "google_drive",
        "source_id": source_id,
        "content": content,
        "metadata": {
            "name": file.get("name"),
            "mimeType": file.get("mimeType"),
            "webViewLink": file.get("webViewLink"),
            "modifiedTime": file.get("modifiedTime"),
        },
    }

    if existing:
        supabase.table("knowledge_base").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("knowledge_base").insert(payload).execute()


async def sync_google_drive_widget(widget: dict) -> dict:
    api_key = (
        widget.get("google_drive_api_key")
        or widget.get("api_key")
        or widget.get("drive_api_key")
    )

    folder_id = widget.get("folder_id") or extract_folder_id(widget.get("folder_url"))

    if not api_key:
        return {
            "ok": False,
            "message": "Google Drive API key is missing.",
            "synced_files": 0,
        }

    if not folder_id:
        return {
            "ok": False,
            "message": "Google Drive folder ID is missing.",
            "synced_files": 0,
        }

    files = await list_drive_files(api_key, folder_id)

    synced_count = 0
    skipped_count = 0

    for file in files:
        content = await download_drive_file_text(api_key, file)

        if not content:
            skipped_count += 1
            continue

        await upsert_knowledge_base_from_drive_file(file, content)
        synced_count += 1

    return {
        "ok": True,
        "message": f"Google Drive sync completed. {synced_count} files synced.",
        "synced_files": synced_count,
        "skipped_files": skipped_count,
        "total_files_found": len(files),
    }
