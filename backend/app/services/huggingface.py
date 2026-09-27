import re
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

    Customer-facing safeguards:
    - Qwen thinking/reasoning is disabled with /no_think.
    - Internal reasoning fields are never returned to the customer.
    - <think>...</think> blocks are stripped if a provider leaks them.
    - If generation is cut off by the token limit, the response is trimmed
      back to a complete sentence and given a safe closing sentence.
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
    def _strip_reasoning(text: str) -> str:
        value = str(text or "")

        value = re.sub(
            r"<think>.*?</think>",
            "",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )

        value = re.sub(
            r"<think>.*$",
            "",
            value,
