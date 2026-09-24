import httpx
from typing import Any
from app.config import get_settings

settings = get_settings()


class HuggingFaceClient:
    """
    Hugging Face chat/text-generation client.

    Default behavior uses Hugging Face Inference Providers through the
    OpenAI-compatible chat-completions router:
        https://router.huggingface.co/v1/chat/completions

    If a custom endpoint is supplied:
    - URLs ending in /v1 are treated as OpenAI-compatible and
      /chat/completions is appended.
    - URLs containing /chat/completions are used directly.
    - Any other custom URL is treated as a legacy text-generation endpoint.
    """

    DEFAULT_CHAT_ENDPOINT = "https://router.huggingface.co/v1/chat/completions"

    def __init__(
        self,
        token: str | None,
        model: str | None = None,
        endpoint_url: str | None = None,
    ):
        self.token = (token or "").strip() or None
        self.model = (
            model
            or getattr(settings, "default_hf_model", None)
            or "Qwen/Qwen3-8B"
        ).strip()

        clean_endpoint = (endpoint_url or "").strip().rstrip("/")

        if not clean_endpoint:
            self.endpoint_url = self.DEFAULT_CHAT_ENDPOINT
            self.endpoint_mode = "chat"
        elif clean_endpoint.endswith("/chat/completions"):
            self.endpoint_url = clean_endpoint
            self.endpoint_mode = "chat"
        elif clean_endpoint.endswith("/v1"):
            self.endpoint_url = f"{clean_endpoint}/chat/completions"
            self.endpoint_mode = "chat"
        else:
            self.endpoint_url = clean_endpoint
            self.endpoint_mode = "legacy"

    @staticmethod
    def _clean_error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("error", "message", "detail"):
                    value = data.get(key)
                    if value:
                        return str(value)[:1000]
            return str(data)[:1000]
        except Exception:
            return (response.text or "").strip()[:1000]

    @staticmethod
    def _extract_chat_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        choices = data.get("choices") or []
        if not choices:
            return ""

        first = choices[0] or {}

        if isinstance(first, dict):
            message = first.get("message") or {}
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

                for key in ("reasoning_content", "reasoning"):
                    value = message.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

            text = first.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

        return ""

    @staticmethod
    def _extract_legacy_text(data: Any) -> str:
        if isinstance(data, list) and data:
            item = data[0]

            if isinstance(item, dict):
                for key in ("generated_text", "summary_text", "text"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

            return str(item).strip()

        if isinstance(data, dict):
            for key in ("generated_text", "summary_text", "text"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            if data.get("error"):
                return ""

        return ""

    async def _post(
        self,
        *,
        payload: dict[str, Any],
        timeout: int,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        total_timeout = max(int(timeout or 30), 10)

        timeout_config = httpx.Timeout(
            timeout=total_timeout,
            connect=min(20, total_timeout),
        )

        async with httpx.AsyncClient(
            timeout=timeout_config,
            follow_redirects=True,
        ) as client:
            return await client.post(
                self.endpoint_url,
                headers=headers,
                json=payload,
            )

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        top_p: float = 0.9,
        max_tokens: int = 512,
        timeout: int = 30,
    ) -> str:
        if not self.token:
            return (
                "AI is not configured yet. "
                "Please add a Hugging Face token in the admin dashboard."
            )

        clean_prompt = str(prompt or "").strip()

        if not clean_prompt:
            return "AI connection exception: Empty prompt."

        try:
            if self.endpoint_mode == "chat":
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": clean_prompt,
                        }
                    ],
                    "temperature": float(temperature),
                    "top_p": float(top_p),
                    "max_tokens": int(max_tokens),
                    "stream": False,
                }

                res = await self._post(
                    payload=payload,
                    timeout=timeout,
                )

                if res.status_code >= 400:
                    error_text = self._clean_error_text(res)
                    return (
                        f"AI connection exception: HTTP {res.status_code}"
                        + (f" - {error_text}" if error_text else "")
                    )

                try:
                    data = res.json()
                except Exception as exc:
                    return (
                        "AI connection exception: "
                        f"Invalid JSON response from Hugging Face: {exc}"
                    )

                output = self._extract_chat_text(data)

                if output:
                    return output

                return (
                    "AI connection exception: "
                    "Hugging Face returned no generated chat content."
                )

            payload = {
                "inputs": clean_prompt,
                "parameters": {
                    "temperature": float(temperature),
                    "top_p": float(top_p),
                    "max_new_tokens": int(max_tokens),
                    "return_full_text": False,
                },
                "options": {
                    "wait_for_model": True,
                },
            }

            res = await self._post(
                payload=payload,
                timeout=timeout,
            )

            if res.status_code >= 400:
                error_text = self._clean_error_text(res)
                return (
                    f"AI connection exception: HTTP {res.status_code}"
                    + (f" - {error_text}" if error_text else "")
                )

            try:
                data = res.json()
            except Exception as exc:
                return (
                    "AI connection exception: "
                    f"Invalid JSON response from custom endpoint: {exc}"
                )

            output = self._extract_legacy_text(data)

            if output:
                return output

            return (
                "AI connection exception: "
                "The custom endpoint returned no generated text."
            )

        except httpx.TimeoutException as exc:
            return f"AI connection exception: Request timed out - {str(exc)}"

        except httpx.ConnectError as exc:
            return f"AI connection exception: Connection failed - {str(exc)}"

        except httpx.HTTPError as exc:
            return f"AI connection exception: HTTP client error - {str(exc)}"

        except Exception as exc:
            return (
                "AI connection exception: "
                f"{type(exc).__name__}: {str(exc)}"
            )


async def test_hf_connection(
    token: str,
    model: str,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    """
    Test the same generation path used by the real chat/RAG flow.
    """
    client = HuggingFaceClient(
        token=token,
        model=model,
        endpoint_url=endpoint_url,
    )

    output = await client.generate(
        "Reply with exactly these two words and nothing else: connection ok",
        temperature=0.1,
        top_p=0.9,
        max_tokens=20,
        timeout=60,
    )

    normalized = (output or "").strip().lower()

    error_markers = (
        "ai is not configured",
        "ai connection exception",
        "ai connection error",
        "request timed out",
        "connection failed",
    )

    has_error = any(marker in normalized for marker in error_markers)
    ok = (not has_error) and ("connection ok" in normalized)

    return {
        "ok": ok,
        "endpoint_url": client.endpoint_url,
        "endpoint_mode": client.endpoint_mode,
        "model": client.model,
        "message": output,
    }
