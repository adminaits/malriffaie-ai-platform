import httpx
from typing import Any
from app.config import get_settings

settings = get_settings()


class HuggingFaceClient:
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

        endpoint = (endpoint_url or "").strip().rstrip("/")

        if not endpoint:
            self.endpoint_url = self.DEFAULT_CHAT_ENDPOINT
            self.endpoint_mode = "chat"
        elif endpoint.endswith("/chat/completions"):
            self.endpoint_url = endpoint
            self.endpoint_mode = "chat"
        elif endpoint.endswith("/v1"):
            self.endpoint_url = endpoint + "/chat/completions"
            self.endpoint_mode = "chat"
        else:
            self.endpoint_url = endpoint
            self.endpoint_mode = "legacy"

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                value = (
                    data.get("error")
                    or data.get("message")
                    or data.get("detail")
                )
                if value:
                    return str(value)[:1000]
            return str(data)[:1000]
        except Exception:
            return (response.text or "").strip()[:1000]

    @staticmethod
    def _clean_output(text: str) -> str:
        value = str(text or "").strip()

        # Remove complete <think>...</think> blocks without regex.
        while True:
            lower = value.lower()
            start = lower.find("<think>")
            end = lower.find("</think>")

            if start == -1 or end == -1 or end < start:
                break

            value = (
                value[:start]
                + value[end + len("</think>"):]
            ).strip()

        # If an opening <think> remains without a closing tag, remove it
        # and everything after it so internal reasoning is never shown.
        lower = value.lower()
        start = lower.find("<think>")

        if start != -1:
            value = value[:start].strip()

        value = value.replace("</think>", "").strip()
        return value

    @staticmethod
    def _extract_chat_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        choices = data.get("choices") or []
        if not choices:
            return ""

        first = choices[0] or {}
        if not isinstance(first, dict):
            return ""

        message = first.get("message") or {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        return ""

    @staticmethod
    def _extract_legacy_text(data: Any) -> str:
        if isinstance(data, list) and data:
            item = data[0]

            if isinstance(item, dict):
                value = (
                    item.get("generated_text")
                    or item.get("summary_text")
                    or item.get("text")
                )
                return str(value or "").strip()

            return str(item).strip()

        if isinstance(data, dict):
            value = (
                data.get("generated_text")
                or data.get("summary_text")
                or data.get("text")
            )
            return str(value or "").strip()

        return ""

    async def _post(
        self,
        payload: dict[str, Any],
        timeout: int,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        total_timeout = max(int(timeout or 30), 10)

        timeout_config = httpx.Timeout(
            total_timeout,
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

        customer_prompt = (
            clean_prompt
            + "\n\n/no_think"
            + "\nReturn only the final customer-facing answer."
            + "\nDo not include analysis, reasoning, planning, chain-of-thought, "
              "or internal notes."
            + "\nKeep the response concise and useful."
            + "\nAlways finish with a complete sentence."
        )

        try:
            if self.endpoint_mode == "chat":
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": customer_prompt,
                        }
                    ],
                    "temperature": float(temperature),
                    "top_p": float(top_p),
                    "max_tokens": int(max_tokens),
                    "stream": False,
                }

                response = await self._post(payload, timeout)

                if response.status_code >= 400:
                    error_text = self._error_text(response)
                    return (
                        "AI connection exception: "
                        f"HTTP {response.status_code} - {error_text}"
                    )

                try:
                    data = response.json()
                except Exception as exc:
                    return (
                        "AI connection exception: "
                        f"Invalid JSON response from Hugging Face: {exc}"
                    )

                output = self._clean_output(
                    self._extract_chat_text(data)
                )

                if output:
                    return output

                return (
                    "AI connection exception: "
                    "Hugging Face returned no customer-facing generated content."
                )

            payload = {
                "inputs": customer_prompt,
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

            response = await self._post(payload, timeout)

            if response.status_code >= 400:
                error_text = self._error_text(response)
                return (
                    "AI connection exception: "
                    f"HTTP {response.status_code} - {error_text}"
                )

            try:
                data = response.json()
            except Exception as exc:
                return (
                    "AI connection exception: "
                    f"Invalid JSON response from custom endpoint: {exc}"
                )

            output = self._clean_output(
                self._extract_legacy_text(data)
            )

            if output:
                return output

            return (
                "AI connection exception: "
                "The custom endpoint returned no generated text."
            )

        except httpx.TimeoutException as exc:
            return (
                "AI connection exception: "
                f"Request timed out - {exc}"
            )

        except httpx.ConnectError as exc:
            return (
                "AI connection exception: "
                f"Connection failed - {exc}"
            )

        except httpx.HTTPError as exc:
            return (
                "AI connection exception: "
                f"HTTP client error - {exc}"
            )

        except Exception as exc:
            return (
                "AI connection exception: "
                f"{type(exc).__name__}: {exc}"
            )


async def test_hf_connection(
    token: str,
    model: str,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    client = HuggingFaceClient(
        token=token,
        model=model,
        endpoint_url=endpoint_url,
    )

    output = await client.generate(
        "Reply with exactly these two words and nothing else: connection ok",
        temperature=0.1,
        top_p=0.9,
        max_tokens=40,
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

    has_error = any(
        marker in normalized
        for marker in error_markers
    )

    ok = (
        not has_error
        and "connection ok" in normalized
    )

    result = {
        "ok": ok,
        "endpoint_url": client.endpoint_url,
        "endpoint_mode": client.endpoint_mode,
        "model": client.model,
        "message": output,
    }

    return result
import httpx
from typing import Any
from app.config import get_settings

settings = get_settings()


class HuggingFaceClient:
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

        endpoint = (endpoint_url or "").strip().rstrip("/")

        if not endpoint:
            self.endpoint_url = self.DEFAULT_CHAT_ENDPOINT
            self.endpoint_mode = "chat"
        elif endpoint.endswith("/chat/completions"):
            self.endpoint_url = endpoint
            self.endpoint_mode = "chat"
        elif endpoint.endswith("/v1"):
            self.endpoint_url = endpoint + "/chat/completions"
            self.endpoint_mode = "chat"
        else:
            self.endpoint_url = endpoint
            self.endpoint_mode = "legacy"

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                value = (
                    data.get("error")
                    or data.get("message")
                    or data.get("detail")
                )
                if value:
                    return str(value)[:1000]
            return str(data)[:1000]
        except Exception:
            return (response.text or "").strip()[:1000]

    @staticmethod
    def _clean_output(text: str) -> str:
        value = str(text or "").strip()

        # Remove complete <think>...</think> blocks without regex.
        while True:
            lower = value.lower()
            start = lower.find("<think>")
            end = lower.find("</think>")

            if start == -1 or end == -1 or end < start:
                break

            value = (
                value[:start]
                + value[end + len("</think>"):]
            ).strip()

        # If an opening <think> remains without a closing tag, remove it
        # and everything after it so internal reasoning is never shown.
        lower = value.lower()
        start = lower.find("<think>")

        if start != -1:
            value = value[:start].strip()

        value = value.replace("</think>", "").strip()
        return value

    @staticmethod
    def _extract_chat_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        choices = data.get("choices") or []
        if not choices:
            return ""

        first = choices[0] or {}
        if not isinstance(first, dict):
            return ""

        message = first.get("message") or {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        return ""

    @staticmethod
    def _extract_legacy_text(data: Any) -> str:
        if isinstance(data, list) and data:
            item = data[0]

            if isinstance(item, dict):
                value = (
                    item.get("generated_text")
                    or item.get("summary_text")
                    or item.get("text")
                )
                return str(value or "").strip()

            return str(item).strip()

        if isinstance(data, dict):
            value = (
                data.get("generated_text")
                or data.get("summary_text")
                or data.get("text")
            )
            return str(value or "").strip()

        return ""

    async def _post(
        self,
        payload: dict[str, Any],
        timeout: int,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        total_timeout = max(int(timeout or 30), 10)

        timeout_config = httpx.Timeout(
            total_timeout,
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

        customer_prompt = (
            clean_prompt
            + "\n\n/no_think"
            + "\nReturn only the final customer-facing answer."
            + "\nDo not include analysis, reasoning, planning, chain-of-thought, "
              "or internal notes."
            + "\nKeep the response concise and useful."
            + "\nAlways finish with a complete sentence."
        )

        try:
            if self.endpoint_mode == "chat":
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": customer_prompt,
                        }
                    ],
                    "temperature": float(temperature),
                    "top_p": float(top_p),
                    "max_tokens": int(max_tokens),
                    "stream": False,
                }

                response = await self._post(payload, timeout)

                if response.status_code >= 400:
                    error_text = self._error_text(response)
                    return (
                        "AI connection exception: "
                        f"HTTP {response.status_code} - {error_text}"
                    )

                try:
                    data = response.json()
                except Exception as exc:
                    return (
                        "AI connection exception: "
                        f"Invalid JSON response from Hugging Face: {exc}"
                    )

                output = self._clean_output(
                    self._extract_chat_text(data)
                )

                if output:
                    return output

                return (
                    "AI connection exception: "
                    "Hugging Face returned no customer-facing generated content."
                )

            payload = {
                "inputs": customer_prompt,
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

            response = await self._post(payload, timeout)

            if response.status_code >= 400:
                error_text = self._error_text(response)
                return (
                    "AI connection exception: "
                    f"HTTP {response.status_code} - {error_text}"
                )

            try:
                data = response.json()
            except Exception as exc:
                return (
                    "AI connection exception: "
                    f"Invalid JSON response from custom endpoint: {exc}"
                )

            output = self._clean_output(
                self._extract_legacy_text(data)
            )

            if output:
                return output

            return (
                "AI connection exception: "
                "The custom endpoint returned no generated text."
            )

        except httpx.TimeoutException as exc:
            return (
                "AI connection exception: "
                f"Request timed out - {exc}"
            )

        except httpx.ConnectError as exc:
            return (
                "AI connection exception: "
                f"Connection failed - {exc}"
            )

        except httpx.HTTPError as exc:
            return (
                "AI connection exception: "
                f"HTTP client error - {exc}"
            )

        except Exception as exc:
            return (
                "AI connection exception: "
                f"{type(exc).__name__}: {exc}"
            )


async def test_hf_connection(
    token: str,
    model: str,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    client = HuggingFaceClient(
        token=token,
        model=model,
        endpoint_url=endpoint_url,
    )

    output = await client.generate(
        "Reply with exactly these two words and nothing else: connection ok",
        temperature=0.1,
        top_p=0.9,
        max_tokens=40,
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

    has_error = any(
        marker in normalized
        for marker in error_markers
    )

    ok = (
        not has_error
        and "connection ok" in normalized
    )

    result = {
        "ok": ok,
        "endpoint_url": client.endpoint_url,
        "endpoint_mode": client.endpoint_mode,
        "model": client.model,
        "message": output,
    }

    return result
