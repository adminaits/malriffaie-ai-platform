import httpx
from typing import Any
from app.config import get_settings

settings = get_settings()

class HuggingFaceClient:
    def __init__(self, token: str | None, model: str | None = None, endpoint_url: str | None = None):
        self.token = token
        self.model = model or settings.default_hf_model
        self.endpoint_url = endpoint_url or f"https://api-inference.huggingface.co/models/{self.model}"

    async def generate(self, prompt: str, *, temperature: float = 0.3, top_p: float = 0.9, max_tokens: int = 512, timeout: int = 30) -> str:
        if not self.token:
            return "AI is not configured yet. Please add a Hugging Face token in the admin dashboard."
        headers = {"Authorization": f"Bearer {self.token}"}
        payload: dict[str, Any] = {
            "inputs": prompt,
            "parameters": {
                "temperature": temperature,
                "top_p": top_p,
                "max_new_tokens": max_tokens,
                "return_full_text": False,
            },
            "options": {"wait_for_model": True},
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(self.endpoint_url, headers=headers, json=payload)
            if res.status_code >= 400:
                return f"AI connection error: {res.text[:500]}"
            data = res.json()
        if isinstance(data, list) and data:
            item = data[0]
            return item.get("generated_text") or str(item)
        if isinstance(data, dict):
            return data.get("generated_text") or data.get("summary_text") or str(data)
        return str(data)

async def test_hf_connection(token: str, model: str, endpoint_url: str | None = None) -> dict[str, Any]:
    client = HuggingFaceClient(token=token, model=model, endpoint_url=endpoint_url)
    output = await client.generate("Reply with: connection ok", max_tokens=20, timeout=45)
    ok = "error" not in output.lower()
    return {"ok": ok, "message": output}
