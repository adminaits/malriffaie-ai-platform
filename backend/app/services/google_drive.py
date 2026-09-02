import io
import json
import httpx
from pypdf import PdfReader
from app.db import supabase


GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

DEFAULT_ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.google-apps.document",
    "text/plain",
]


def _clean_value(value):
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() in {"none", "null", "undefined", "n/a", "na", "-"}:
        return None

    return value


def _normalise_access_level(value, internal_company_wiki: bool = False) -> str:
    """
    Public knowledge can be used by all visitors.
    Private knowledge is only for logged-in clients/admins.

    If Internal Company Wiki is enabled, always force private.
    """
    if internal_company_wiki:
        return "private"

    value = _clean_value(value) or "public"
    value = value.lower()

    if value not in {"public", "private"}:
        return "public"

    return value


def extract_folder_id(folder_url_or_id: str | None) -> str:
    value = _clean_value(folder_url_or_id)

    if not value:
        return ""

    if "/folders/" in value:
        return value.split("/folders/")[1].split("?")[0].split("/")[0]

    return value


def _parse_allowed_mime_types(value) -> list[str]:
    if not value:
        return DEFAULT_ALLOWED_MIME_TYPES

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass

        return [item.strip() for item in value.split(",") if item.strip()]

    return DEFAULT_ALLOWED_MIME_TYPES


def _parse_folder_ids(value) -> list[str]:
    if not value:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass

        return [item.strip() for item in value.split(",") if item.strip()]

    return []


def _bool_value(value, default=True) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}

    return bool(value)


def _drive_list_params(api_key: str, query: str, page_token: str | None = None) -> dict:
    params = {
        "key": api_key,
        "q": query,
        "fields": "nextPageToken, files(id,name,mimeType,webViewLink,modifiedTime,size,parents,shortcutDetails)",
        "pageSize": 100,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }

    if page_token:
        params["pageToken"] = page_token

    return params


async def list_drive_files_direct(api_key: str, folder_id: str) -> list[dict]:
    all_files = []
    page_token = None

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            query = f"'{folder_id}' in parents and trashed = false"
            params = _drive_list_params(api_key, query, page_token)

            response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)

            if response.status_code >= 400:
                raise Exception(
                    f"Google Drive list error: {response.status_code} - {response.text}"
                )

            data = response.json()

            for file in data.get("files", []):
                if file.get("mimeType") != GOOGLE_FOLDER_MIME:
                    all_files.append(file)

            page_token = data.get("nextPageToken")

            if not page_token:
                break

    return all_files


async def list_drive_files_recursive(api_key: str, parent_folder_id: str) -> list[dict]:
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
                params = _drive_list_params(api_key, query, page_token)

                response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)

                if response.status_code >= 400:
                    raise Exception(
                        f"Google Drive recursive list error: {response.status_code} - {response.text}"
                    )

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

                params = _drive_list_params(api_key, query, page_token)

                response = await client.get(GOOGLE_DRIVE_FILES_URL, params=params)

                if response.status_code >= 400:
                    raise Exception(
                        f"Google Drive folder list error: {response.status_code} - {response.text}"
                    )

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


async def download_drive_file_text(api_key: str, file: dict) -> dict:
    """
    Returns:
    {
      "text": "...",
      "error": None
    }

    or:
    {
      "text": "",
      "error": "real reason here"
    }
    """
    file_id = file.get("id")
    mime_type = file.get("mimeType")
    file_name = file.get("name")

    if not file_id:
        return {
            "text": "",
            "error": "Missing Google Drive file ID",
        }

    if mime_type == GOOGLE_SHORTCUT_MIME:
        shortcut = file.get("shortcutDetails") or {}
        target_id = shortcut.get("targetId")
        target_mime = shortcut.get("targetMimeType")

        return {
            "text": "",
            "error": (
                "This file is a Google Drive shortcut. "
                f"Target ID: {target_id or 'unknown'}, "
                f"Target MIME type: {target_mime or 'unknown'}. "
                "Select the real target folder/file instead of the shortcut."
            ),
        }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            if mime_type == "application/vnd.google-apps.document":
                url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"

                response = await client.get(
                    url,
                    params={
                        "key": api_key,
                        "mimeType": "text/plain",
                        "supportsAllDrives": "true",
                    },
                )

                if response.status_code >= 400:
                    return {
                        "text": "",
                        "error": f"Google Doc export failed {response.status_code}: {response.text}",
                    }

                text = response.text.strip()

                if not text:
                    return {
                        "text": "",
                        "error": "Google Doc exported successfully but returned empty text",
                    }

                return {
                    "text": text,
                    "error": None,
                }

            if mime_type == "text/plain":
                url = f"https://www.googleapis.com/drive/v3/files/{file_id}"

                response = await client.get(
                    url,
                    params={
                        "key": api_key,
                        "alt": "media",
                        "supportsAllDrives": "true",
                    },
                )

                if response.status_code >= 400:
                    return {
                        "text": "",
                        "error": f"Text file download failed {response.status_code}: {response.text}",
                    }

                text = response.text.strip()

                if not text:
                    return {
                        "text": "",
                        "error": "Text file downloaded but was empty",
                    }

                return {
                    "text": text,
                    "error": None,
                }

            if mime_type == "application/pdf":
                url = f"https://www.googleapis.com/drive/v3/files/{file_id}"

                response = await client.get(
                    url,
                    params={
                        "key": api_key,
                        "alt": "media",
                        "supportsAllDrives": "true",
                    },
                )

                if response.status_code >= 400:
                    return {
                        "text": "",
                        "error": f"PDF download failed {response.status_code}: {response.text}",
                    }

                text = extract_pdf_text(response.content)

                if not text:
                    return {
                        "text": "",
                        "error": (
                            "PDF downloaded but no selectable text was found. "
                            "It may be a scanned/image PDF and needs OCR or conversion to Google Docs."
                        ),
                    }

                return {
                    "text": text,
                    "error": None,
                }

            return {
                "text": "",
                "error": f"Unsupported MIME type: {mime_type}",
            }

        except Exception as exc:
            return {
                "text": "",
                "error": f"Download/extraction exception for {file_name}: {str(exc)}",
            }


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

    (
        supabase
        .table("knowledge_base")
        .delete()
        .eq("source_type", "google_drive")
        .eq("source_id", source_id)
        .execute()
    )


async def insert_knowledge_chunks_from_drive_file(
    file: dict,
    content: str,
    access_level: str = "public",
    internal_company_wiki: bool = False,
) -> int:
    source_id = file.get("id")

    if not source_id or not content:
        return 0

    internal_company_wiki = bool(internal_company_wiki)
    access_level = _normalise_access_level(access_level, internal_company_wiki)

    await delete_existing_knowledge_for_file(source_id)

    chunks = chunk_text(content)
    inserted = 0

    for idx, chunk in enumerate(chunks):
        payload = {
            "source_type": "google_drive",
            "source_id": source_id,
            "content": chunk,
            "access_level": access_level,
            "internal_company_wiki": internal_company_wiki,
            "metadata": {
                "name": file.get("name"),
                "mimeType": file.get("mimeType"),
                "webViewLink": file.get("webViewLink"),
                "modifiedTime": file.get("modifiedTime"),
                "parents": file.get("parents"),
                "chunk_index": idx,
                "total_chunks": len(chunks),
                "access_level": access_level,
                "internal_company_wiki": internal_company_wiki,
            },
        }

        supabase.table("knowledge_base").insert(payload).execute()
        inserted += 1

    return inserted


async def sync_google_drive_widget(widget: dict) -> dict:
    api_key = (
        _clean_value(widget.get("google_drive_api_key"))
        or _clean_value(widget.get("api_key"))
        or _clean_value(widget.get("drive_api_key"))
    )

    selected_folder_ids = _parse_folder_ids(widget.get("selected_folder_ids"))

    single_folder_id = (
        _clean_value(widget.get("selected_folder_id"))
        or _clean_value(widget.get("folder_id"))
        or _clean_value(widget.get("parent_folder_id"))
        or extract_folder_id(widget.get("folder_url"))
    )

    folder_ids = selected_folder_ids or ([single_folder_id] if single_folder_id else [])

    include_subfolders = _bool_value(widget.get("include_subfolders"), default=True)
    allowed_mime_types = _parse_allowed_mime_types(widget.get("allowed_mime_types"))

    internal_company_wiki = _bool_value(widget.get("internal_company_wiki"), default=False)
    access_level = _normalise_access_level(widget.get("access_level"), internal_company_wiki)

    if not api_key:
        return {
            "ok": False,
            "message": "Google Drive API key is missing.",
            "folder_ids_used": folder_ids,
            "synced_files": 0,
            "access_level": access_level,
            "internal_company_wiki": internal_company_wiki,
        }

    if not folder_ids:
        return {
            "ok": False,
            "message": "Google Drive folder ID is missing.",
            "folder_ids_used": [],
            "synced_files": 0,
            "access_level": access_level,
            "internal_company_wiki": internal_company_wiki,
        }

    try:
        files = []
        seen_file_ids = set()

        for folder_id in folder_ids:
            if include_subfolders:
                folder_files = await list_drive_files_recursive(api_key, folder_id)
            else:
                folder_files = await list_drive_files_direct(api_key, folder_id)

            for file in folder_files:
                file_id = file.get("id")

                if file_id and file_id not in seen_file_ids:
                    seen_file_ids.add(file_id)
                    files.append(file)

    except Exception as exc:
        return {
            "ok": False,
            "message": str(exc),
            "folder_ids_used": folder_ids,
            "synced_files": 0,
            "total_files_found": 0,
            "access_level": access_level,
            "internal_company_wiki": internal_company_wiki,
        }

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
                "id": file.get("id"),
                "mimeType": mime_type,
                "reason": "File type not allowed by widget settings",
                "webViewLink": file.get("webViewLink"),
            })
            continue

        download_result = await download_drive_file_text(api_key, file)
        content = download_result.get("text", "")
        download_error = download_result.get("error")

        if not content:
            skipped_files += 1
            skipped_details.append({
                "name": file.get("name"),
                "id": file.get("id"),
                "mimeType": mime_type,
                "reason": download_error or "No extractable text or unsupported file type",
                "webViewLink": file.get("webViewLink"),
            })
            continue

        chunks_inserted = await insert_knowledge_chunks_from_drive_file(
            file,
            content,
            access_level=access_level,
            internal_company_wiki=internal_company_wiki,
        )

        if chunks_inserted > 0:
            synced_files += 1
            total_chunks += chunks_inserted
        else:
            skipped_files += 1
            skipped_details.append({
                "name": file.get("name"),
                "id": file.get("id"),
                "mimeType": mime_type,
                "reason": "No chunks inserted",
                "webViewLink": file.get("webViewLink"),
            })

    return {
        "ok": True,
        "message": (
            f"Google Drive sync completed. "
            f"{synced_files} files synced, {total_chunks} knowledge chunks created."
        ),
        "folder_ids_used": folder_ids,
        "synced_files": synced_files,
        "skipped_files": skipped_files,
        "total_files_found": len(files),
        "total_chunks": total_chunks,
        "include_subfolders": include_subfolders,
        "allowed_mime_types": allowed_mime_types,
        "access_level": access_level,
        "internal_company_wiki": internal_company_wiki,
        "skipped_details": skipped_details,
    }
