from app.db import supabase
from app.services.huggingface import HuggingFaceClient
from app.config import get_settings
from datetime import date

settings = get_settings()

DEFAULT_PROMPT = """
You are the customer support and e-commerce AI concierge for {site}.
Answer using ONLY the provided products, services, and knowledge base context.
Do not mention files or source names to the customer.
Format answers clearly with short paragraphs or bullet points.
Always show BHD prices with 3 decimals, for example 300.000 BHD.
If the answer is not found, say clearly that the information is not available yet and ask the user to book a consultation or contact support.
Today is {date}. User language: {lang}.
"""


def _latest_ai_settings() -> dict:
    res = (
        supabase
        .table("ai_settings")
        .select("*")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return (res.data or [{}])[0]


def _format_price(value, currency="BHD") -> str:
    if value is None or value == "":
        return "Available"
    try:
        return f"{float(value):,.3f} {currency or 'BHD'}"
    except Exception:
        return f"{value} {currency or 'BHD'}"


def _clean_optional_url(value):
    """
    Prevent invalid custom endpoint values from breaking the chat.

    Empty values, null-like text, or non-URL strings should be ignored.
    If ignored, HuggingFaceClient will build the normal Hugging Face API URL
    from the selected model name.
    """
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() in {"none", "null", "n/a", "na", "-", "undefined"}:
        return None

    if not value.startswith("http://") and not value.startswith("https://"):
        return None

    return value


def _clean_model_name(value, fallback="HuggingFaceH4/zephyr-7b-beta"):
    if value is None:
        return fallback

    value = str(value).strip()

    if value == "":
        return fallback

    if value.lower() in {"none", "null", "n/a", "na", "-", "undefined", "custom"}:
        return fallback

    return value


def retrieve_context(query: str, limit: int = 8) -> dict:
    # Simple Postgres text search fallback.
    # For production, add pgvector embeddings and RPC match_documents().
    kb = (
        supabase
        .table("knowledge_base")
        .select("id,source_type,source_id,content,metadata")
        .ilike("content", f"%{query[:80]}%")
        .limit(limit)
        .execute()
        .data
        or []
    )

    products = (
        supabase
        .table("products")
        .select("*")
        .eq("available", True)
        .order("created_at", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )

    services = (
        supabase
        .table("services")
        .select("*")
        .eq("available", True)
        .order("created_at", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )

    return {
        "knowledge": kb,
        "products": products,
        "services": services,
    }


def recommend_products(message: str, products: list[dict]) -> list[dict]:
    low = message.lower()
    scored = []

    for p in products:
        text = f"{p.get('name', '')} {p.get('description', '')}".lower()
        score = sum(1 for w in low.split() if len(w) > 3 and w in text)

        if score or any(
            k in low
            for k in [
                "marketing",
                "agreement",
                "hr",
                "feasibility",
                "consultation",
                "retainer",
            ]
        ):
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:3]] or products[:3]


def _wants_product_list(message: str) -> bool:
    low = message.lower().strip()
    return any(
        phrase in low
        for phrase in [
            "list all products",
            "all products",
            "show products",
            "products list",
            "what products",
            "available products",
        ]
    )


def _matched_product(message: str, products: list[dict]) -> dict | None:
    low = message.lower()

    # Longest name first avoids short partial matches taking priority.
    for product in sorted(products, key=lambda p: len(p.get("name") or ""), reverse=True):
        name = (product.get("name") or "").lower()
        if name and name in low:
            return product

    return None


def _product_list_answer(products: list[dict]) -> str:
    if not products:
        return "No products are currently available. Please book a consultation or contact support."

    lines = ["Here are the products currently available:", ""]

    for idx, product in enumerate(products, 1):
        lines.append(
            f"{idx}. {product.get('name')} — "
            f"{_format_price(product.get('price'), product.get('currency'))}"
        )

    lines.append("")
    lines.append(
        "You can click a product in the sidebar to view details, "
        "or tell me what you need and I will recommend the best option."
    )

    return "\n".join(lines)


def _product_detail_answer(product: dict) -> str:
    return "\n".join(
        [
            f"Here are the details for {product.get('name')}:",
            "",
            product.get("description") or "Professional product/service package.",
            "",
            f"Price: {_format_price(product.get('price'), product.get('currency'))}",
            f"Availability: {'Available' if product.get('available', True) else 'Unavailable'}",
            "",
            "You can use the Buy Now option or ask me to compare it with another product.",
        ]
    )


def _build_huggingface_client(cfg: dict) -> HuggingFaceClient:
    token = cfg.get("hugging_face_token") or settings.hugging_face_token

    selected_model = cfg.get("model_name") or cfg.get("model")

    custom_model = cfg.get("custom_model_name")

    if selected_model == "custom":
        model_name = custom_model
    else:
        model_name = selected_model

    model_name = _clean_model_name(
        model_name or settings.default_hf_model or settings.default_model,
        fallback="HuggingFaceH4/zephyr-7b-beta",
    )

    endpoint_url = _clean_optional_url(
        cfg.get("custom_hf_endpoint")
        or cfg.get("custom_endpoint_url")
        or settings.custom_hf_endpoint
    )

    return HuggingFaceClient(
        token=token,
        model=model_name,
        endpoint_url=endpoint_url,
    )


async def answer_chat(
    message: str,
    visitor_id: str | None = None,
    lang: str = "en",
    ip_hash: str | None = None,
) -> dict:
    cfg = _latest_ai_settings()
    ctx = retrieve_context(message)

    # Deterministic product answers keep the storefront clean and avoid malformed AI formatting.
    recommended = recommend_products(message, ctx["products"])
    answer = None

    if _wants_product_list(message):
        answer = _product_list_answer(ctx["products"])
        recommended = ctx["products"][:6]
    else:
        product = _matched_product(message, ctx["products"])
        if product and any(
            k in message.lower()
            for k in ["tell", "detail", "price", "buy", "about", "more"]
        ):
            answer = _product_detail_answer(product)
            recommended = [product]

    if answer is None:
        prompt_template = cfg.get("system_prompt") or DEFAULT_PROMPT

        prompt = prompt_template.format(
            site="Malriffaie",
            site_url="",
            url="",
            lang=lang,
            date=date.today().isoformat(),
        )

        prompt += "\n\nProducts:\n" + "\n".join(
            [
                f"- {p.get('name')} | "
                f"{_format_price(p.get('price'), p.get('currency'))} | "
                f"{p.get('description', '')}"
                for p in ctx["products"]
            ]
        )

        prompt += "\n\nServices:\n" + "\n".join(
            [
                f"- {s.get('name')} | "
                f"{_format_price(s.get('price'), s.get('currency'))} | "
                f"{s.get('description', '')}"
                for s in ctx["services"]
            ]
        )

        prompt += "\n\nKnowledge context:\n" + "\n---\n".join(
            [k.get("content", "")[:1200] for k in ctx["knowledge"]]
        )

        prompt += f"\n\nCustomer message: {message}\nAnswer:"

        hf = _build_huggingface_client(cfg)

        answer = await hf.generate(
            prompt,
            temperature=cfg.get("temperature", 0.3),
            top_p=cfg.get("top_p", 0.9),
            max_tokens=cfg.get("max_tokens", 512),
            timeout=cfg.get("timeout", 30),
        )

        if not answer or "AI is not configured" in answer:
            answer = (
                cfg.get("fallback_message")
                or "I do not have that information yet. I can arrange a human handoff for you."
            )

    if visitor_id:
        supabase.table("chat_messages").insert(
            {
                "visitor_id": visitor_id,
                "message": message,
                "response": answer,
                "products_shown": recommended,
                "ip_hash": ip_hash,
            }
        ).execute()

    return {
        "answer": answer,
        "products": recommended,
        "sources": ctx["knowledge"],
    }
