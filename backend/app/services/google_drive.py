import io
import json
import httpx
from pypdf import PdfReader
from app.db import supabase


GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

DEFAULT_ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.google-apps.document",
    "text/plain",
]


def extract_folder_id(folder_url_or_id: str | None) -> str:
    if not folder_url_or_id:
        return ""

    value = str(folder_url_or_id).strip()

    if "/folders/" in value:
        return value.split("/folders/")[1].split("?")[0].split("/")[0]

    return value


def _parse_allowed_mime_types(value) -> list[str]:
    if not value:
        return DEFAULT_ALLOWED_MIME_TYPES

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return DEFAULT_ALLOWED_MIME_TYPES


def _bool_value(value, default=True) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}

    return bool(value)


async def list_drive_files_direct(api_key: str, folder_id: str) -> list[dict]:
    """
    Reads files directly inside one folder only.
    Does not scan subfolders.
    """
    all_files = []
    page_token = None

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            query = f"'{folder_id}' in parents and trashed = false"

            params = {
                "key": api_key,
                "q": query,
                "fields": "nextPageToken, files(id,name,mimeType,webViewLink,modifiedTime,size,parents)",
                "pageSize": 100,
            }

            if page_token:
                params["pageToken"] = page_token

            response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)
            response.raise_for_status()

            data = response.json()

            for file in data.get("files", []):
                if file.get("mimeType") != GOOGLE_FOLDER_MIME:
                    all_files.append(file)

            page_token = data.get("nextPageToken")

            if not page_token:
                break

    return all_files


async def list_drive_files_recursive(api_key: str, parent_folder_id: str) -> list[dict]:
    """
    Reads all files inside:
    - parent folder
    - subfolders
    - nested subfolders

    Folders are scanned, not inserted as files.
    """
    all_files = []
    folders_to_scan = [parent_folder_id]
    scanned_folders = set()

    async with httpx.AsyncClient(timeout=60) as client:
        while folders_to_scan:
            current_folder_id = folders_to_scan.pop(0)

            if current_folder_id in scanned_folders:
                continue

            scanned_folders.add(current_folder_id)
            page_token = None

            while True:
                query = f"'{current_folder_id}' in parents and trashed = false"

                params = {
                    "key": api_key,
                    "q": query,
                    "fields": "nextPageToken, files(id,name,mimeType,webViewLink,modifiedTime,size,parents)",
                    "pageSize": 100,
                }

                if page_token:
                    params["pageToken"] = page_token

                response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)
                response.raise_for_status()

                data = response.json()
                files = data.get("files", [])

                for file in files:
                    mime_type = file.get("mimeType")

                    if mime_type == GOOGLE_FOLDER_MIME:
                        folder_id = file.get("id")
                        if folder_id and folder_id not in scanned_folders:
                            folders_to_scan.append(folder_id)
                    else:
                        all_files.append(file)

                page_token = data.get("nextPageToken")

                if not page_token:
                    break

    return all_files


async def list_drive_folders_recursive(api_key: str, parent_folder_id: str) -> list[dict]:
    """
    Returns all folders under a parent folder.
    This is for the admin dashboard folder selector.
    """
    folders = []
    folders_to_scan = [
        {
            "id": parent_folder_id,
            "name": "Parent Folder",
            "path": "Parent Folder",
        }
    ]

    scanned_folders = set()

    async with httpx.AsyncClient(timeout=60) as client:
        while folders_to_scan:
            current = folders_to_scan.pop(0)
            current_folder_id = current["id"]
            current_path = current["path"]

            if current_folder_id in scanned_folders:
                continue

            scanned_folders.add(current_folder_id)
            page_token = None

            while True:
                query = (
                    f"'{current_folder_id}' in parents "
                    f"and trashed = false "
                    f"and mimeType = '{GOOGLE_FOLDER_MIME}'"
                )

                params = {
                    "key": api_key,
                    "q": query,
                    "fields": "nextPageToken, files(id,name,mimeType,webViewLink,modifiedTime,parents)",
                    "pageSize": 100,
                }

                if page_token:
                    params["pageToken"] = page_token

                response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)
                response.raise_for_status()

                data = response.json()
                found_folders = data.get("files", [])

                for folder in found_folders:
                    folder_path = f"{current_path} / {folder.get('name')}"

                    item = {
                        "id": folder.get("id"),
                        "name": folder.get("name"),
                        "path": folder_path,
                        "webViewLink": folder.get("webViewLink"),
                        "modifiedTime": folder.get("modifiedTime"),
                        "parents": folder.get("parents"),
                    }

                    folders.append(item)

                    folders_to_scan.append({
                        "id": folder.get("id"),
                        "name": folder.get("name"),
                        "path": folder_path,
                    })

                page_token = data.get("nextPageToken")

                if not page_token:
                    break

    return folders


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())

        return "\n\n".join(pages).strip()

    except Exception:
        return ""


async def download_drive_file_text(api_key: str, file: dict) -> str:
    file_id = file.get("id")
    mime_type = file.get("mimeType")

    if not file_id:
        return ""

    async with httpx.AsyncClient(timeout=120) as client:
        if mime_type == "application/vnd.google-apps.document":
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
            response = await client.get(
                url,
                params={
                    "key": api_key,
                    "mimeType": "text/plain",
                },
            )

            if response.status_code >= 400:
                return ""

            return response.text.strip()

        if mime_type == "text/plain":
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            response = await client.get(
                url,
                params={
                    "key": api_key,
                    "alt": "media",
                },
            )

            if response.status_code >= 400:
                return ""

            return response.text.strip()

        if mime_type == "application/pdf":
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            response = await client.get(
                url,
                params={
                    "key": api_key,
                    "alt": "media",
                },
            )

            if response.status_code >= 400:
                return ""

            return extract_pdf_text(response.content)

        return ""


def chunk_text(text: str, max_chars: int = 3500) -> list[str]:
    text = (text or "").strip()

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start = end

    return chunks


async def delete_existing_knowledge_for_file(source_id: str) -> None:
    if not source_id:
        return

    supabase.table("knowledge_base") \
        .delete() \
        .eq("source_type", "google_drive") \
        .eq("source_id", source_id) \
        .execute()


async def insert_knowledge_chunks_from_drive_file(file: dict, content: str) -> int:
    source_id = file.get("id")

    if not source_id or not content:
        return 0

    await delete_existing_knowledge_for_file(source_id)

    chunks = chunk_text(content)
    inserted = 0

    for idx, chunk in enumerate(chunks):
        payload = {
            "source_type": "google_drive",
            "source_id": source_id,
            "content": chunk,
            "metadata": {
                "name": file.get("name"),
                "mimeType": file.get("mimeType"),
                "webViewLink": file.get("webViewLink"),
                "modifiedTime": file.get("modifiedTime"),
                "parents": file.get("parents"),
                "chunk_index": idx,
                "total_chunks": len(chunks),
            },
        }

        supabase.table("knowledge_base").insert(payload).execute()
        inserted += 1

    return inserted


async def sync_google_drive_widget(widget: dict) -> dict:
    api_key = (
        widget.get("google_drive_api_key")
        or widget.get("api_key")
        or widget.get("drive_api_key")
    )

    folder_id = (
        widget.get("selected_folder_id")
        or widget.get("folder_id")
        or widget.get("parent_folder_id")
        or extract_folder_id(widget.get("folder_url"))
    )

    include_subfolders = _bool_value(widget.get("include_subfolders"), default=True)
    allowed_mime_types = _parse_allowed_mime_types(widget.get("allowed_mime_types"))

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

    if include_subfolders:
        files = await list_drive_files_recursive(api_key, folder_id)
    else:
        files = await list_drive_files_direct(api_key, folder_id)

    synced_files = 0
    skipped_files = 0
    total_chunks = 0
    skipped_details = []

    for file in files:
        mime_type = file.get("mimeType")

        if mime_type not in allowed_mime_types:
            skipped_files += 1
            skipped_details.append({
                "name": file.get("name"),
                "mimeType": mime_type,
                "reason": "File type not allowed by widget settings",
            })
            continue

        content = await download_drive_file_text(api_key, file)

        if not content:
            skipped_files += 1
            skipped_details.append({
                "name": file.get("name"),
                "mimeType": mime_type,
                "reason": "No extractable text or unsupported file type",
            })
            continue

        chunks_inserted = await insert_knowledge_chunks_from_drive_file(file, content)

        if chunks_inserted > 0:
            synced_files += 1
            total_chunks += chunks_inserted
        else:
            skipped_files += 1
            skipped_details.append({
                "name": file.get("name"),
                "mimeType": mime_type,
                "reason": "No chunks inserted",
            })

    return {
        "ok": True,
        "message": (
            f"Google Drive sync completed. "
            f"{synced_files} files synced, {total_chunks} knowledge chunks created."
        ),
        "synced_files": synced_files,
        "skipped_files": skipped_files,
        "total_files_found": len(files),
        "total_chunks": total_chunks,
        "include_subfolders": include_subfolders,
        "allowed_mime_types": allowed_mime_types,
        "skipped_details": skipped_details,
    }
