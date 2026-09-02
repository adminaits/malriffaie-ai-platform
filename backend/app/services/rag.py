from app.db import supabase
from app.services.huggingface import HuggingFaceClient
from app.config import get_settings
from datetime import date

settings = get_settings()

PRIVATE_KNOWLEDGE_MESSAGE = (
    "Please login, contact info@malriffaie.com, book a consultation, "
    "or call us for more details."
)

DEFAULT_PROMPT = """
You are the customer support and e-commerce AI concierge for {site}.

Use ONLY the approved context provided below:
1. Products from the admin dashboard
2. Services from the admin dashboard
3. Knowledge base content synced from Google Drive or other approved sources

Do not invent information.
Do not mention internal table names, file names, or source names to the customer.
If the answer is available in the approved context, answer clearly.
If the answer is not available, say:
"The information is not available yet. Please book a consultation or contact support."

For company profile questions such as "About Malriffaie", "Who is Mohamed Alriffaie?", or "What is Enchantment Management?", prioritize the knowledge base context.

Always show BHD prices with 3 decimals, for example 300.000 BHD.
Format answers clearly with short paragraphs or bullet points.

Today is {date}. User language: {lang}.
"""


def _latest_ai_settings() -> dict:
    try:
        res = (
            supabase
            .table("ai_settings")
            .select("*")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return (res.data or [{}])[0]
    except Exception:
        return {}


def _format_price(value, currency="BHD") -> str:
    if value is None or value == "":
        return "Available"

    try:
        return f"{float(value):,.3f} {currency or 'BHD'}"
    except Exception:
        return f"{value} {currency or 'BHD'}"


def _clean_optional_url(value):
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


def _query_words(query: str) -> list[str]:
    cleaned = (
        (query or "")
        .replace("?", " ")
        .replace(".", " ")
        .replace(",", " ")
        .replace(":", " ")
        .replace(";", " ")
        .replace("/", " ")
        .replace("-", " ")
        .replace("_", " ")
    )

    stop_words = {
        "what", "about", "tell", "know", "please", "can", "you", "the",
        "is", "are", "for", "with", "from", "that", "this", "have", "has",
        "who", "how", "why", "when", "where", "and", "or", "to", "of",
        "me", "my", "your", "our", "more", "details", "detail",
    }

    words = [
        word.strip(".,?!:;()[]{}\"'").lower()
        for word in cleaned.split()
        if len(word.strip(".,?!:;()[]{}\"'")) > 2
    ]

    return [word for word in words if word and word not in stop_words]


def _keyword_score(text: str, query: str) -> int:
    text = (text or "").lower()
    words = _query_words(query)

    score = 0

    for word in words:
        if word in text:
            score += 1

    return score


def _row_access_level(row: dict) -> str:
    access_level = row.get("access_level") or "public"

    if isinstance(access_level, str):
        access_level = access_level.strip().lower()
    else:
        access_level = "public"

    if access_level not in {"public", "private"}:
        access_level = "public"

    if row.get("internal_company_wiki") is True:
        access_level = "private"

    metadata = row.get("metadata") or {}

    if isinstance(metadata, dict):
        if metadata.get("internal_company_wiki") is True:
            access_level = "private"

        meta_access = metadata.get("access_level")
        if isinstance(meta_access, str) and meta_access.strip().lower() == "private":
            access_level = "private"

    return access_level


def _is_private_row(row: dict) -> bool:
    return _row_access_level(row) == "private"


def _score_knowledge_row(item: dict, query_text: str) -> int:
    content = item.get("content") or ""
    metadata = item.get("metadata") or {}

    score = _keyword_score(content, query_text)
    score += _keyword_score(str(metadata), query_text)

    low_query = query_text.lower()
    low_content = content.lower()
    low_metadata = str(metadata).lower()

    combined = f"{low_content} {low_metadata}"

    if "malriffaie" in low_query and "malriffaie" in combined:
        score += 5

    if "alriffaie" in low_query and "alriffaie" in combined:
        score += 5

    if "mohamed" in low_query and "mohamed" in combined:
        score += 5

    if "enchantment" in low_query and "enchantment" in combined:
        score += 5

    if "management" in low_query and "management" in combined:
        score += 3

    if "internal" in low_query and item.get("internal_company_wiki"):
        score += 5

    if "company" in low_query and item.get("internal_company_wiki"):
        score += 3

    if "wiki" in low_query and item.get("internal_company_wiki"):
        score += 5

    if "about" in low_query and (
        "about malriffaie" in combined
        or "about enchantment" in combined
        or "about mohamed" in combined
    ):
        score += 5

    return score


def _load_knowledge_rows() -> list[dict]:
    """
    Loads recent/approved knowledge rows. This keeps your existing simple Supabase
    retrieval approach, while adding access_level/internal_company_wiki fields.
    """
    try:
        return (
            supabase
            .table("knowledge_base")
            .select("id,source_type,source_id,content,metadata,access_level,internal_company_wiki")
            .limit(300)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def _private_knowledge_match_exists(query: str) -> bool:
    query_text = (query or "").strip()

    if not query_text:
        return False

    all_kb = _load_knowledge_rows()

    for item in all_kb:
        if not _is_private_row(item):
            continue

        if _score_knowledge_row(item, query_text) > 0:
            return True

    return False


def retrieve_context(
    query: str,
    limit: int = 8,
    include_private: bool = False,
) -> dict:
    query_text = (query or "").strip()

    try:
        all_kb = _load_knowledge_rows()
        scored_kb = []

        for item in all_kb:
            if _is_private_row(item) and not include_private:
                continue

            score = _score_knowledge_row(item, query_text)

            if score > 0:
                scored_kb.append((score, item))

        scored_kb.sort(key=lambda x: x[0], reverse=True)
        kb = [item for _, item in scored_kb[:limit]]

        # Important fallback:
        # If no keyword match, still provide approved context.
        # Public users only get public context.
        if not kb:
            fallback_rows = [
                item for item in all_kb
                if include_private or not _is_private_row(item)
            ]
            kb = fallback_rows[:limit]

    except Exception:
        kb = []

    try:
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
    except Exception:
        products = []

    try:
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
    except Exception:
        services = []

    return {
        "knowledge": kb,
        "products": products,
        "services": services,
    }


def recommend_products(message: str, products: list[dict]) -> list[dict]:
    low = message.lower()
    scored = []

    keyword_map = {
        "new business": ["feasibility", "consultation", "marketing", "strategy"],
        "startup": ["feasibility", "consultation", "marketing", "strategy"],
        "start business": ["feasibility", "consultation", "marketing", "strategy"],
        "business": ["feasibility", "consultation", "marketing"],
        "feasibility": ["feasibility"],
        "marketing": ["marketing", "strategy", "content"],
        "agreement": ["agreement", "partnership"],
        "partnership": ["partnership", "agreement"],
        "hr": ["hr", "manual"],
        "consultation": ["consultation", "online"],
        "retainer": ["retainer", "membership"],
        "subscription": ["subscription"],
    }

    expanded_terms = set()

    for word in low.split():
        if len(word) > 3:
            expanded_terms.add(word)

    for phrase, terms in keyword_map.items():
        if phrase in low:
            expanded_terms.update(terms)

    for p in products:
        text = f"{p.get('name', '')} {p.get('description', '')}".lower()
        score = sum(1 for term in expanded_terms if term in text)

        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        return [p for _, p in scored[:3]]

    return products[:3]


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
            "show me products",
            "what do you sell",
        ]
    )


def _wants_service_list(message: str) -> bool:
    low = message.lower().strip()

    return any(
        phrase in low
        for phrase in [
            "list all services",
            "all services",
            "show services",
            "services list",
            "what services",
            "available services",
        ]
    )


def _matched_product(message: str, products: list[dict]) -> dict | None:
    low = message.lower()

    for product in sorted(products, key=lambda p: len(p.get("name") or ""), reverse=True):
        name = (product.get("name") or "").lower()
        if name and name in low:
            return product

    if "feasibility" in low:
        for product in products:
            if "feasibility" in (product.get("name") or "").lower():
                return product

    if "marketing" in low:
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            if "marketing" in text:
                return product

    if "hr" in low or "manual" in low:
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            if "hr" in text or "manual" in text:
                return product

    if "agreement" in low or "partnership" in low:
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            if "agreement" in text or "partnership" in text:
                return product

    return None


def _product_list_answer(products: list[dict]) -> str:
    if not products:
        return "No products are currently available. Please book a consultation or contact support."

    lines = ["Here are the products currently available:", ""]

    for idx, product in enumerate(products, 1):
        lines.append(
            f"{idx}. {product.get('name')} - "
            f"{_format_price(product.get('price'), product.get('currency'))}"
        )

    lines.append("")
    lines.append(
        "You can click a product in the sidebar to view details, "
        "or tell me what you need and I will recommend the best option."
    )

    return "\n".join(lines)


def _service_list_answer(services: list[dict]) -> str:
    if not services:
        return "No services are currently available. Please book a consultation or contact support."

    lines = ["Here are the services currently available:", ""]

    for idx, service in enumerate(services, 1):
        lines.append(
            f"{idx}. {service.get('name')} - "
            f"{_format_price(service.get('price'), service.get('currency'))}"
        )

    lines.append("")
    lines.append("You can tell me what you need and I will recommend the best service.")

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


def _recommendation_answer(message: str, products: list[dict], services: list[dict]) -> tuple[str, list[dict]]:
    recommended = recommend_products(message, products)

    if not recommended:
        return (
            "For a new business, I recommend starting with an online consultation so we can understand your idea, budget, and next steps.",
            [],
        )

    lines = [
        "For a new business, I recommend starting with these options:",
        "",
    ]

    for idx, product in enumerate(recommended, 1):
        lines.append(
            f"{idx}. {product.get('name')} - "
            f"{_format_price(product.get('price'), product.get('currency'))}"
        )
        if product.get("description"):
            lines.append(f"   {product.get('description')}")

    lines.append("")
    lines.append(
        "If you are still at the idea stage, start with a Feasibility Study or Online Consultation. "
        "If you already have partners or operations, a Partnership Agreement or HR Manual may be the next step."
    )

    return "\n".join(lines), recommended


def _should_answer_deterministically(message: str) -> bool:
    low = message.lower()

    return any(
        phrase in low
        for phrase in [
            "new business",
            "start business",
            "startup",
            "which product",
            "right product",
            "recommend",
            "feasibility",
            "marketing",
            "partnership",
            "agreement",
            "hr manual",
            "consultation",
            "price",
            "cost",
            "products",
            "services",
        ]
    )


def _build_huggingface_client(cfg: dict) -> HuggingFaceClient:
    token = (
        cfg.get("hugging_face_token")
        or getattr(settings, "hugging_face_token", None)
        or getattr(settings, "hf_token", None)
    )

    selected_model = cfg.get("model_name") or cfg.get("model")
    custom_model = cfg.get("custom_model_name")

    if selected_model == "custom":
        model_name = custom_model
    else:
        model_name = selected_model

    default_model = (
        getattr(settings, "default_hf_model", None)
        or getattr(settings, "default_model", None)
        or "HuggingFaceH4/zephyr-7b-beta"
    )

    model_name = _clean_model_name(
        model_name or default_model,
        fallback="HuggingFaceH4/zephyr-7b-beta",
    )

    endpoint_url = _clean_optional_url(
        cfg.get("custom_hf_endpoint")
        or cfg.get("custom_endpoint_url")
        or getattr(settings, "custom_hf_endpoint", None)
        or getattr(settings, "custom_endpoint_url", None)
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
    client_logged_in: bool = False,
) -> dict:
    cfg = _latest_ai_settings()

    if not client_logged_in and _private_knowledge_match_exists(message):
        return {
            "answer": PRIVATE_KNOWLEDGE_MESSAGE,
            "products": [],
            "sources": [],
        }

    ctx = retrieve_context(
        message,
        include_private=client_logged_in,
    )

    recommended = recommend_products(message, ctx["products"])
    answer = None

    if _wants_product_list(message):
        answer = _product_list_answer(ctx["products"])
        recommended = ctx["products"][:6]

    elif _wants_service_list(message):
        answer = _service_list_answer(ctx["services"])
        recommended = ctx["products"][:3]

    else:
        product = _matched_product(message, ctx["products"])

        if product and any(
            k in message.lower()
            for k in [
                "tell",
                "detail",
                "price",
                "buy",
                "about",
                "more",
                "know",
                "explain",
                "what is",
                "what about",
                "cost",
            ]
        ):
            answer = _product_detail_answer(product)
            recommended = [product]

        elif _should_answer_deterministically(message):
            answer, recommended = _recommendation_answer(
                message,
                ctx["products"],
                ctx["services"],
            )

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

        try:
            answer = await hf.generate(
                prompt,
                temperature=cfg.get("temperature", 0.3),
                top_p=cfg.get("top_p", 0.9),
                max_tokens=cfg.get("max_tokens", 512),
                timeout=cfg.get("timeout", 30),
            )
        except Exception as exc:
            answer = (
                cfg.get("fallback_message")
                or f"I could not connect to the AI service right now. Please try again or contact support. Error: {str(exc)}"
            )

        if (
            not answer
            or "AI is not configured" in answer
            or "AI connection exception" in answer
            or "No address associated with hostname" in answer
        ):
            if ctx["knowledge"]:
                first_context = ctx["knowledge"][0].get("content", "").strip()
                answer = first_context[:900] if first_context else None

            if not answer:
                answer = (
                    cfg.get("fallback_message")
                    or "I do not have that information yet. I can arrange a human handoff for you."
                )

    if visitor_id:
        try:
            supabase.table("chat_messages").insert(
                {
                    "visitor_id": visitor_id,
                    "message": message,
                    "response": answer,
                    "products_shown": recommended,
                    "ip_hash": ip_hash,
                }
            ).execute()
        except Exception:
            pass

    return {
        "answer": answer,
        "products": recommended,
        "sources": ctx["knowledge"],
    }
