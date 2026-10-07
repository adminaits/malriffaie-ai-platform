from app.db import supabase
from app.services.huggingface import HuggingFaceClient
from app.config import get_settings
from datetime import date
import re
from statistics import mean, median

settings = get_settings()

# TEMPORARY TESTING ONLY:
# Set this to False before going live so internal source names/IDs
# are never shown to clients.
SHOW_RAG_SOURCES_TO_CLIENT = True

PRIVATE_KNOWLEDGE_MESSAGE = """
## Thank You for Your Interest

We appreciate you taking the time to learn more about **MalRiffaie**. The information you’ve reviewed is just the beginning of how we can support your goals.

To explore tailored solutions for your business or project, we invite you to:

- **Log in** to your client portal if you already have an account
- **Subscribe** to stay updated with our latest insights, offers, and service announcements

For personalized guidance, you can also:

- **Email us:** info@malriffaie.com
- **Book a consultation** to discuss your needs in detail
- **Call us** for immediate assistance and quick answers

Our team is ready to help you move forward with clarity and confidence.
""".strip()

DEFAULT_PROMPT = """
You are the customer support and e-commerce AI concierge for {site}.

Use ONLY the approved context provided below:
1. Products from the admin dashboard
2. Services from the admin dashboard
3. Knowledge base content synced from Google Drive or other approved sources

Do not invent information.
Ignore any context that is not relevant to the customer's requested industry or topic.
Never answer a question about one industry using knowledge from an unrelated industry.
For structured business assessments, summarize only relevant approved knowledge and clearly separate supported findings from assumptions.
Never expose business names, client identities, source file names, source IDs, or individual confidential figures from private knowledge.
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


def _clean_model_name(value, fallback="Qwen/Qwen3-8B"):
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


def _expand_knowledge_terms(query: str) -> list[str]:
    """
    Expand a user's topic into closely-related search terms so the RAG layer
    can retrieve approved knowledge even when the documents use different
    wording.

    Example:
    "farming" -> agriculture, agricultural, farm, seeds, nuts, crops, etc.
    """
    low = (query or "").lower()

    topic_groups = {
        "farming": [
            "farming",
            "farm",
            "farms",
            "agriculture",
            "agricultural",
            "agri",
            "seed",
            "seeds",
            "nut",
            "nuts",
            "crop",
            "crops",
            "produce",
            "horticulture",
            "plantation",
            "greenhouse",
            "irrigation",
        ],
        "healthcare": [
            "healthcare",
            "health care",
            "medical",
            "clinic",
            "medical center",
            "medical centre",
            "home care",
            "homecare",
            "wellness",
            "pharmacy",
            "dental",
            "physiotherapy",
            "laboratory",
        ],
        "salon": [
            "salon",
            "beauty",
            "spa",
            "hair",
            "nail",
            "barber",
            "massage",
        ],
        "hotel": [
            "hotel",
            "hospitality",
            "resort",
            "guest house",
            "guesthouse",
            "serviced apartment",
        ],
        "cafe": [
            "cafe",
            "café",
            "coffee",
            "restaurant",
            "food",
            "bakery",
            "cloud kitchen",
            "takeaway",
        ],
        "construction": [
            "construction",
            "contracting",
            "contractor",
            "civil works",
            "fit out",
            "fit-out",
        ],
    }

    expanded = []

    for terms in topic_groups.values():
        if any(term in low for term in terms):
            expanded.extend(terms)

    return list(dict.fromkeys(expanded))


def _keyword_score(text: str, query: str) -> int:
    text = (text or "").lower()
    words = _query_words(query)
    expanded_terms = _expand_knowledge_terms(query)

    score = 0

    for word in words:
        if word in text:
            score += 2

    for term in expanded_terms:
        if term in text:
            score += 4

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
            .limit(1000)
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

        score = _score_knowledge_row(item, query_text)

        # Require a stronger match so normal public questions like
        # "products list", "services", or "book consultation" are not blocked.
        if score >= 2:
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

        query_words = _query_words(query_text)
        query_industry = _detect_industry(query_text)
        expanded_terms = _expand_knowledge_terms(query_text)

        scoring_query = query_text
        if expanded_terms:
            scoring_query = (
                query_text
                + " "
                + " ".join(expanded_terms)
            ).strip()

        # Multi-word questions need a stronger relevance match than a
        # single-keyword lookup. This prevents generic words such as
        # "business" from pulling an unrelated feasibility study.
        minimum_score = 2 if len(query_words) >= 2 else 1

        for item in all_kb:
            if _is_private_row(item) and not include_private:
                continue

            # If the question clearly names an industry, only use knowledge
            # that belongs to or explicitly mentions that same industry.
            # This prevents healthcare questions from returning cafe,
            # confectionery, salon, construction, etc. content.
            if query_industry and not _row_matches_industry(item, query_industry):
                continue

            score = _score_knowledge_row(item, scoring_query)

            if score >= minimum_score:
                scored_kb.append((score, item))

        scored_kb.sort(key=lambda x: x[0], reverse=True)
        kb = [item for _, item in scored_kb[:limit]]

        # Never substitute unrelated/random knowledge when nothing relevant
        # meets the threshold.
        if not kb:
            kb = []

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



def _is_greeting(message: str) -> bool:
    """Handle simple greetings locally without calling the external AI model."""
    low = (message or "").lower().strip()
    cleaned = low.strip(" .,!?:;؟،")

    greetings = {
        "hi",
        "hello",
        "hey",
        "hiya",
        "good morning",
        "good afternoon",
        "good evening",
        "morning",
        "afternoon",
        "evening",
        "السلام عليكم",
        "سلام",
        "مرحبا",
        "مرحباً",
        "هلا",
        "اهلا",
        "أهلا",
        "اهلين",
        "أهلين",
    }

    return cleaned in greetings



def _wants_product_list(message: str) -> bool:
    low = (message or "").lower().strip()

    exact_requests = {
        "product",
        "products",
        "product please",
        "products please",
        "product list",
        "products list",
        "list product",
        "list products",
        "list all products",
        "list of products",
        "all products",
        "show product",
        "show products",
        "show me products",
        "show me the products",
        "show all products",
        "show me all products",
        "available products",
        "what product",
        "what products",
        "what products do you have",
        "what products do you offer",
        "which products",
        "tell me about products",
        "tell me about your products",
        "tell me the products",
        "describe products",
        "describe your products",
        "explain products",
        "your products",
        "products available",
        "products you provide",
        "products you offer",
        "what do you sell",
        "catalog",
        "catalogue",
        "product catalog",
        "product catalogue",
    }

    if low in exact_requests:
        return True

    return any(
        phrase in low
        for phrase in [
            "list all products",
            "list of products",
            "show me products",
            "show all products",
            "show me all products",
            "products list",
            "product list",
            "available products",
            "what products do you have",
            "what products do you offer",
            "tell me about products",
            "describe products",
            "describe your products",
            "product catalog",
            "product catalogue",
        ]
    )


def _wants_service_list(message: str) -> bool:
    low = (message or "").lower().strip()

    return any(
        phrase in low
        for phrase in [
            "list services",
            "list all services",
            "list of services",
            "service list",
            "services list",
            "show services",
            "show me services",
            "show all services",
            "show me all services",
            "available services",
            "what services",
            "what service",
            "what services do you have",
            "what services do you offer",
            "which services",
            "describe services",
            "describe the services",
            "describe your services",
            "can you describe services",
            "can you describe the services",
            "tell me about services",
            "tell me about your services",
            "tell me the services",
            "explain services",
            "explain your services",
            "services available",
            "services you provide",
            "services you offer",
            "your services",
        ]
    )


def _is_public_product_or_service_question(message: str) -> bool:
    low = (message or "").lower().strip()

    public_phrases = [
        "products",
        "product list",
        "products list",
        "list products",
        "show products",
        "services",
        "service list",
        "services list",
        "list services",
        "show services",
        "book",
        "booking",
        "consultation",
        "online consultation",
        "price",
        "cost",
        "how much",
        "what do you sell",
        "what services",
        "what products",
        "feasibility",
        "marketing",
        "partnership",
        "agreement",
        "hr manual",
        "retainer",
    ]

    return any(phrase in low for phrase in public_phrases)


def _wants_booking(message: str) -> bool:
    low = (message or "").lower()

    return any(
        phrase in low
        for phrase in [
            "book",
            "booking",
            "online consultation",
            "book consultation",
            "book an online consultation",
            "appointment",
            "schedule",
        ]
    )


def _booking_answer(services: list[dict]) -> str:
    consultation = None

    for service in services:
        name = (service.get("name") or "").lower()
        if "consultation" in name:
            consultation = service
            break

    if consultation:
        return "\n".join(
            [
                "You can book an online consultation.",
                "",
                f"Service: {consultation.get('name')}",
                f"Price: {_format_price(consultation.get('price'), consultation.get('currency'))}",
                "",
                "Please continue with the booking flow or contact info@malriffaie.com if you need help choosing a time.",
            ]
        )

    return (
        "You can book a consultation. Please use the booking option, "
        "or contact info@malriffaie.com if you need help choosing a time."
    )


MARKETING_CHOICE_MARKER = "[MARKETING_CHOICE]"


def _is_marketing_topic(message: str) -> bool:
    low = " ".join(str(message or "").lower().split())

    marketing_terms = [
        "marketing",
        "marketing strategy",
        "marketing strategies",
        "marketing plan",
        "promotion",
        "promotional",
        "advertising",
        "social media",
        "customer acquisition",
        "branding",
        "brand awareness",
        "sales strategy",
        "go to market",
        "go-to-market",
    ]

    return any(term in low for term in marketing_terms)


def _declines_product_sales(message: str) -> bool:
    """Detect an explicit request for advice without buying a product/package."""
    low = " ".join(str(message or "").lower().split())

    phrases = [
        "do not want to buy",
        "don't want to buy",
        "dont want to buy",
        "would not like to buy",
        "wouldn't like to buy",
        "not like to buy",
        "not interested in buying",
        "not interested to buy",
        "i don't want products",
        "i dont want products",
        "i do not want products",
        "no products please",
        "without buying",
        "just give me advice",
        "just give advice",
        "just advice",
        "only advice",
        "just suggestions",
        "only suggestions",
    ]

    return any(phrase in low for phrase in phrases)


def _has_explicit_marketing_product_intent(message: str) -> bool:
    """
    Detect when the customer clearly wants the Malriffaie marketing product.

    A generic sentence such as "What marketing strategies can we use?" is
    intentionally NOT product intent; it should offer the two-path chooser.
    """
    low = " ".join(str(message or "").lower().split())

    if not _is_marketing_topic(low):
        return False

    if _declines_product_sales(low):
        return False

    product_terms = [
        "buy",
        "purchase",
        "order",
        "checkout",
        "buy now",
        "package",
        "product",
        "price",
        "how much is",
        "availability",
        "available to buy",
        "marketing strategy package",
        "marketing package",
        "your marketing service",
        "your marketing product",
    ]

    return any(term in low for term in product_terms)


def _should_offer_marketing_choice(message: str) -> bool:
    """
    Offer two routes for an ambiguous marketing request:
    1) Malriffaie Marketing Strategy product
    2) AI suggestions from approved knowledge
    """
    text = str(message or "").strip()

    if not text:
        return False

    if text.upper().startswith(MARKETING_CHOICE_MARKER):
        return False

    if not _is_marketing_topic(text):
        return False

    if _has_explicit_marketing_product_intent(text):
        return False

    if _declines_product_sales(text):
        return False

    return True


def _marketing_choice_answer() -> str:
    return "\n".join(
        [
            MARKETING_CHOICE_MARKER,
            "I can help you with marketing in two ways:",
            "",
            "1. View the Malriffaie Marketing Strategy Package - see the product details, price, and purchase option.",
            "2. Get AI Marketing Suggestions - I will use your current business topic and relevant approved knowledge-base information to suggest practical marketing strategies.",
            "",
            "Please choose option 1 or 2.",
        ]
    )


def _parse_marketing_choice(
    message: str,
    recent_rows: list[dict] | None = None,
) -> str | None:
    """
    Parse either the structured frontend action or a typed 1/2 response.
    Typed 1/2 is accepted only when the immediately preceding assistant answer
    was the marketing chooser.
    """
    raw = str(message or "").strip()
    low = " ".join(raw.lower().split())

    if low.startswith(MARKETING_CHOICE_MARKER.lower()):
        tail = low[len(MARKETING_CHOICE_MARKER):].strip(" :-")

        if tail in {"1", "product", "package", "buy", "view product"}:
            return "product"

        if tail in {
            "2",
            "advice",
            "suggestions",
            "ai advice",
            "ai suggestions",
            "knowledge",
            "knowledge base",
        }:
            return "advice"

        return None

    # Natural-language explicit choices are also supported.
    if low in {
        "view marketing strategy package",
        "marketing strategy package",
        "choose product",
        "choose package",
        "option 1 product",
    }:
        return "product"

    if low in {
        "get ai marketing suggestions",
        "ai marketing suggestions",
        "choose ai suggestions",
        "choose advice",
        "option 2 advice",
    }:
        return "advice"

    # Plain 1/2 should only act as a choice if the latest assistant reply was
    # the chooser. This prevents an unrelated "1" or "2" from being routed.
    latest_assistant = ""

    for row in reversed(recent_rows or []):
        response = str(row.get("response") or "").strip()
        if response:
            latest_assistant = response
            break

    if MARKETING_CHOICE_MARKER in latest_assistant:
        if low in {"1", "1.", "option 1", "number 1", "first", "product"}:
            return "product"

        if low in {"2", "2.", "option 2", "number 2", "second", "advice", "suggestions"}:
            return "advice"

    return None


def _find_marketing_product(products: list[dict]) -> dict | None:
    """Prefer the dedicated Marketing Strategy product, then any marketing item."""
    for product in products or []:
        name = str(product.get("name") or "").lower()
        description = str(product.get("description") or "").lower()

        if "marketing" in name and "strategy" in name:
            return product

        if "marketing strategy" in f"{name} {description}":
            return product

    for product in products or []:
        text = f"{product.get('name', '')} {product.get('description', '')}".lower()
        if "marketing" in text:
            return product

    return None


def _matched_product(message: str, products: list[dict]) -> dict | None:
    low = str(message or "").lower()

    # Marketing is intentionally ambiguous unless the user clearly asks for
    # the product/package. Generic marketing questions use the two-option flow.
    if _is_marketing_topic(low) and not _has_explicit_marketing_product_intent(low):
        return None

    for product in sorted(products, key=lambda p: len(p.get("name") or ""), reverse=True):
        name = (product.get("name") or "").lower()
        if name and name in low:
            return product

    if "feasibility" in low:
        for product in products:
            if "feasibility" in (product.get("name") or "").lower():
                return product

    if "marketing" in low and _has_explicit_marketing_product_intent(low):
        return _find_marketing_product(products)

    has_hr_intent = bool(
        re.search(r"\bhr\b", low)
        or "human resources" in low
        or "hr manual" in low
        or "employee manual" in low
    )

    if has_hr_intent or "manual" in low:
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            if (
                re.search(r"\bhr\b", text)
                or "human resources" in text
                or "manual" in text
            ):
                return product

    if "agreement" in low or "partnership" in low:
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            if "agreement" in text or "partnership" in text:
                return product

    return None


def _product_list_answer(products: list[dict]) -> str:
    if not products:
        return (
            "No products are currently available. "
            "Please book a consultation or contact support."
        )

    lines = ["Here are all the products currently available:", ""]

    for idx, product in enumerate(products, 1):
        name = product.get("name") or "Unnamed product"
        description = product.get("description") or ""

        lines.append(f"{idx}. {name}")
        lines.append(
            f"   Price: {_format_price(product.get('price'), product.get('currency'))}"
        )

        if description:
            lines.append(f"   Description: {description}")

        lines.append("")

    lines.append(
        "You can select any product from the sidebar or use the Buy Now option."
    )

    return "\n".join(lines)


def _service_list_answer(services: list[dict]) -> str:
    if not services:
        return (
            "No services are currently available. "
            "Please book a consultation or contact support."
        )

    lines = ["Here are the services currently available:", ""]

    for idx, service in enumerate(services, 1):
        name = service.get("name") or "Unnamed service"
        description = service.get("description") or ""

        lines.append(f"{idx}. {name}")
        lines.append(
            f"   Price: {_format_price(service.get('price'), service.get('currency'))}"
        )

        if description:
            lines.append(f"   Description: {description}")

        lines.append("")

    lines.append(
        "Tell me which service you are interested in and I can explain it in more detail."
    )

    return "\n".join(lines)


def _matched_service(message: str, services: list[dict]) -> dict | None:
    low = (message or "").lower()

    for service in sorted(services, key=lambda s: len(s.get("name") or ""), reverse=True):
        name = (service.get("name") or "").lower()
        if name and name in low:
            return service

    if "consultation" in low:
        for service in services:
            service_text = f"{service.get('name', '')} {service.get('description', '')}".lower()
            if "consultation" in service_text:
                return service

    return None


def _service_detail_answer(service: dict) -> str:
    return "\n".join(
        [
            f"Here are the details for {service.get('name')}:",
            "",
            service.get("description") or "Professional service.",
            "",
            f"Price: {_format_price(service.get('price'), service.get('currency'))}",
            f"Availability: {'Available' if service.get('available', True) else 'Unavailable'}",
            "",
            "Tell me if you would like help booking this service.",
        ]
    )


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


def _wants_recommendation(message: str) -> bool:
    low = (message or "").lower().strip()

    return any(
        phrase in low
        for phrase in [
            "recommend",
            "recommendation",
            "which product is right",
            "which product should i",
            "which service is right",
            "which service should i",
            "what should i choose",
            "best option for me",
            "best product for",
            "best service for",
            "what do you recommend",
            "help me choose",
            "new business",
            "start business",
            "startup",
        ]
    )



def _wants_anonymized_benchmark(message: str) -> bool:
    low = (message or "").lower().strip()

    benchmark_terms = [
        "average", "avg", "benchmark", "typical budget", "typical cost",
        "usual budget", "usual cost", "average budget", "average cost",
        "setup budget", "setup cost", "startup budget", "startup cost",
        "initial investment", "investment needed", "how much to start",
        "how much does it cost to start", "cost to set up", "cost to setup",
        "budget to set up", "budget to setup",
    ]

    return any(term in low for term in benchmark_terms)


def _detect_industry(message: str) -> str | None:
    low = (message or "").lower()

    aliases = {
        "healthcare": ["healthcare", "health care", "medical", "clinic", "medical center", "medical centre", "home care", "homecare", "nursing", "wellness", "pharmacy", "dental", "physiotherapy", "laboratory", "lab"],
        "salon": ["salon", "beauty salon", "beauty business", "beauty center", "beauty centre", "spa", "hair salon", "nail salon", "barbershop", "barber shop", "massage center", "massage centre"],
        "hotel": ["hotel", "hotels", "boutique hotel", "resort", "guest house", "guesthouse", "hospitality", "serviced apartment", "serviced apartments"],
        "cafe": ["cafe", "café", "coffee shop", "coffeeshop", "restaurant", "food business", "bakery", "cloud kitchen", "kiosk", "takeaway"],
        "construction": ["construction", "contracting", "contractor", "building materials", "fit out", "fit-out", "civil works"],
        "retail": ["retail", "retail shop", "store", "shop", "boutique", "ecommerce", "e-commerce", "online store"],
        "education": ["education", "school", "nursery", "training center", "training centre", "academy", "institute", "learning center", "learning centre"],
        "gym": ["gym", "fitness", "fitness center", "fitness centre", "sports center", "sports centre", "health club"],
        "farming": [
            "farming", "farm", "farms", "agriculture", "agricultural", "agri",
            "seed", "seeds", "nut", "nuts", "crop", "crops", "produce",
            "horticulture", "plantation", "greenhouse", "irrigation"
        ],
    }

    for industry, terms in aliases.items():
        if any(term in low for term in terms):
            return industry

    return None



BUSINESS_INTAKE_QUESTIONS = {
    "healthcare": [
        "What is your approximate budget for this healthcare business?",
        "Which country, city, or area are you planning to establish it in?",
        "What type of healthcare business are you considering, such as a clinic, medical center, home care center, wellness center, pharmacy, dental clinic, or another type?",
        "Do you have previous experience in healthcare or a related field?",
        "Will this be a startup from scratch, or do you already have an existing healthcare business?",
        "Have you already checked the main healthcare licensing or regulatory requirements for the location?",
    ],
    "salon": [
        "What is your approximate budget for the salon or beauty business?",
        "Which country, city, or area are you planning to open it in?",
        "What type of beauty business are you considering, such as a ladies salon, nail salon, spa, hair salon, massage center, or another concept?",
        "What services do you plan to offer?",
        "What approximate size, number of chairs, rooms, or treatment stations are you considering?",
        "Do you already have experience or an existing customer base in the beauty industry?",
        "Will this be a new startup or an expansion of an existing business?",
    ],
    "hotel": [
        "What is your approximate investment budget?",
        "Which country, city, or area are you considering for the hotel?",
        "What type or category of hotel are you planning, such as budget, boutique, serviced apartments, resort, 3-star, 4-star, or another concept?",
        "Approximately how many rooms or units are you considering?",
        "Do you already own or lease the property, or are you still searching for a location?",
        "Who is your main target customer, such as tourists, business travelers, families, long-stay guests, or another segment?",
        "Will this be a new project or an existing hospitality business?",
    ],
    "cafe": [
        "What is your approximate budget?",
        "Which country, city, or area are you planning to operate in?",
        "Are you planning a café, restaurant, takeaway, kiosk, bakery, cloud kitchen, or another food concept?",
        "Will the business have seating, or will it mainly be takeaway and delivery?",
        "What food or beverage concept are you planning?",
        "Who is your main target customer?",
        "Will this be a startup from scratch or an existing operation?",
    ],
    "construction": [
        "What is your approximate startup or working-capital budget?",
        "Which country or area will the business operate in?",
        "What type of construction or contracting work will you focus on?",
        "Will you work mainly on residential, commercial, industrial, fit-out, maintenance, or another type of project?",
        "Do you already have engineers, supervisors, labor, equipment, or supplier relationships?",
        "Do you have previous construction or project-management experience?",
        "Will this be a new company or an expansion of an existing business?",
    ],
    "retail": [
        "What is your approximate budget?",
        "Which country, city, or area are you planning to operate in?",
        "What products do you plan to sell?",
        "Will the business be a physical store, online store, or both?",
        "Who is your main target customer?",
        "Do you already have suppliers or brands selected?",
        "Will this be a new startup or an existing retail business?",
    ],
    "education": [
        "What is your approximate budget?",
        "Which country, city, or area are you planning to operate in?",
        "What type of education business are you considering, such as a nursery, school, academy, training center, or institute?",
        "What age group or customer segment will you serve?",
        "Do you already have a suitable premises or are you still looking for one?",
        "Do you have previous experience in education or training?",
        "Have you reviewed the main licensing or accreditation requirements?",
    ],
    "gym": [
        "What is your approximate budget?",
        "Which country, city, or area are you planning to operate in?",
        "What type of fitness business are you considering, such as a general gym, boutique studio, ladies gym, personal-training studio, or sports center?",
        "What approximate size or member capacity are you planning for?",
        "What equipment or services do you expect to provide?",
        "Do you have previous fitness-industry experience or an existing customer base?",
        "Will this be a new startup or an expansion of an existing business?",
    ],
    "farming": [
        "What is your approximate budget?",
        "Which country, city, or area are you planning to operate in?",
        "What type of farming or agricultural activity are you considering?",
        "Are you planning production, processing, importing, distribution, or retail?",
        "What crops, seeds, nuts, produce, or agricultural products are you focusing on?",
        "Do you already have land, facilities, suppliers, or farming experience?",
        "Will this be a startup from scratch or an expansion of an existing business?",
    ],
}

BUSINESS_INDUSTRY_LABELS = {
    "healthcare": "healthcare",
    "salon": "beauty and salon",
    "hotel": "hotel and hospitality",
    "cafe": "café and food",
    "construction": "construction and contracting",
    "retail": "retail",
    "education": "education and training",
    "gym": "fitness",
    "farming": "farming and agriculture",
}



def _parse_business_assessment(message: str) -> dict | None:
    """
    Parse the structured assessment message sent by the logged-in client dashboard.

    Expected format starts with:
    [BUSINESS_ASSESSMENT]
    """
    text = str(message or "").strip()

    if not text.startswith("[BUSINESS_ASSESSMENT]"):
        return None

    result = {}

    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = (
            key.strip()
            .lower()
            .replace(" / ", "_")
            .replace("/", "_")
            .replace(" ", "_")
        )
        value = value.strip()

        if key and value:
            result[key] = value

    industry = str(result.get("industry") or "").strip().lower()

    if not industry:
        return None

    result["industry"] = industry
    return result


def _business_assessment_search_query(assessment: dict) -> str:
    """
    Build a focused retrieval query from structured client answers.
    """
    values = [
        assessment.get("industry"),
        assessment.get("business_type"),
        assessment.get("country"),
        assessment.get("city_area"),
        assessment.get("business_stage"),
        assessment.get("target_customer"),
        assessment.get("previous_experience"),
    ]

    return " ".join(
        str(value).strip()
        for value in values
        if value
        and str(value).strip().lower()
        not in {"not specified", "none", "n/a", "na"}
    )


def _business_assessment_profile(assessment: dict) -> str:
    """
    Format the submitted assessment for the model prompt.
    """
    preferred_order = [
        ("Industry", "industry_label"),
        ("Business type", "business_type"),
        ("Budget", "budget"),
        ("Country", "country"),
        ("City / area", "city_area"),
        ("Previous experience", "previous_experience"),
        ("Business stage", "business_stage"),
        ("Target customer", "target_customer"),
        ("Additional notes", "additional_notes"),
    ]

    lines = []

    for label, key in preferred_order:
        value = assessment.get(key)

        if (
            value
            and str(value).strip().lower()
            not in {"not specified", "none", "n/a", "na"}
        ):
            lines.append(f"- {label}: {value}")

    ignored = {key for _, key in preferred_order} | {"industry"}

    for key, value in assessment.items():
        if key in ignored:
            continue

        if (
            not value
            or str(value).strip().lower()
            in {"not specified", "none", "n/a", "na"}
        ):
            continue

        label = key.replace("_", " ").strip().title()
        lines.append(f"- {label}: {value}")

    return "\n".join(lines)



def _wants_business_idea_discovery(message: str) -> bool:
    """
    Detect broad business-idea discovery by meaning/components instead of
    relying mainly on exact phrases.

    Examples that should return True:
    - "I have 20,000 BHD. What business can I start?"
    - "I have 20000 BD to start the business. Can you share suggestions?"
    - "Suggest a business for my 15k budget."
    - "Which business would be suitable with this investment?"

    If the client already names a supported industry, return False so the
    industry-specific guidance / assessment flow can take over.
    """
    raw = str(message or "").strip()

    if not raw:
        return False

    low = raw.lower()

    # Normalize punctuation and repeated whitespace while preserving numbers.
    normalized = re.sub(r"[?.,!;:()\[\]{}]", " ", low)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Once a supported industry is explicitly named, this is no longer broad
    # discovery. Example: "I have 20,000 BHD to start a salon."
    if _detect_industry(raw):
        return False

    # Support common spelling variations in free-form customer chat.
    business_terms = [
        "business",
        "buisness",
        "buissness",
        "venture",
        "startup",
        "start-up",
        "company",
        "project",
    ]

    start_terms = [
        "start",
        "starting",
        "open",
        "opening",
        "setup",
        "set up",
        "launch",
        "launching",
        "establish",
        "establishing",
        "build",
        "create",
    ]

    discovery_terms = [
        "suggest",
        "suggestion",
        "suggestions",
        "recommend",
        "recommendation",
        "recommendations",
        "idea",
        "ideas",
        "option",
        "options",
        "which",
        "what business",
        "what can i start",
        "what should i start",
        "category",
        "categories",
        "profitable",
        "suitable",
        "best",
        "good business",
        "opportunity",
        "opportunities",
        "advise",
        "advice",
        "guide",
        "guidance",
    ]

    has_budget = bool(
        re.search(
            r"\b(?:bhd|bd|budget|capital|investment|funds|funding)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )

    has_business = any(term in normalized for term in business_terms)
    has_start = any(term in normalized for term in start_terms)
    has_discovery = any(term in normalized for term in discovery_terms)

    # Direct discovery patterns. These work even if no budget is stated.
    direct_patterns = [
        r"\bwhat\s+(?:type\s+of\s+)?business\b.*\bstart\b",
        r"\bwhich\s+(?:type\s+of\s+)?business\b.*\bstart\b",
        r"\bwhat\s+business\b.*\bshould\b",
        r"\bwhich\s+business\b.*\bshould\b",
        r"\bsuggest(?:ion|ions)?\b.*\bbusiness\b",
        r"\bbusiness\b.*\bsuggest(?:ion|ions)?\b",
        r"\brecommend(?:ation|ations)?\b.*\bbusiness\b",
        r"\bbusiness\b.*\brecommend(?:ation|ations)?\b",
        r"\bbusiness\s+idea(?:s)?\b",
        r"\bbusiness\s+opportunit(?:y|ies)\b",
        r"\bprofitable\s+business\b",
        r"\bbest\s+business\b",
        r"\bgood\s+business\b",
    ]

    if any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in direct_patterns
    ):
        return True

    # Primary semantic rule:
    # business context + start intent + either budget or discovery intent.
    if has_business and has_start and (has_budget or has_discovery):
        return True

    # Example: "I have 20k BD, what can I start?"
    if has_budget and has_start and has_discovery:
        return True

    # Example: "Suggest a business for this budget."
    if has_budget and has_business and has_discovery:
        return True

    return False


def _business_idea_discovery_search_query(message: str) -> str:
    """
    Build a broad retrieval query for cross-industry opportunity discovery.

    The original client message is kept, while adding terms that are useful
    across feasibility studies and startup/project knowledge.
    """
    base = str(message or "").strip()

    discovery_terms = [
        "startup",
        "setup budget",
        "startup cost",
        "initial investment",
        "project cost",
        "feasibility",
        "business opportunity",
        "profit",
        "revenue",
        "break even",
        "operating cost",
    ]

    return (base + " " + " ".join(discovery_terms)).strip()


DISCOVERY_INDUSTRIES = [
    "healthcare",
    "salon",
    "hotel",
    "cafe",
    "construction",
    "retail",
    "education",
    "gym",
    "farming",
]


def _extract_budget_from_message(message: str) -> float | None:
    """
    Best-effort extraction of a BHD budget from the client's message.

    Examples:
    - "20,000 BHD"
    - "20000 bd"
    - "budget is 15k"
    """
    low = str(message or "").lower().replace(",", "")

    patterns = [
        r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:bhd|bd)\b",
        r"\b(?:budget|capital|investment)\s*(?:is|of|around|about|approximately|approx)?\s*([0-9]+(?:\.[0-9]+)?)\s*k\b",
        r"\b([0-9]+(?:\.[0-9]+)?)\s*k\s*(?:bhd|bd)?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, low)
        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        if "k" in match.group(0):
            value *= 1000

        if value > 0:
            return value

    return None


def _discovery_row_score(row: dict, industry: str, client_budget: float | None) -> int:
    """
    Score a knowledge row for cross-industry business discovery.

    The score rewards:
    - a clear industry match
    - feasibility / setup / investment / financial content
    - rows containing an extractable setup/startup/project amount
    - budget amounts reasonably close to the client's stated budget
    """
    content = str(row.get("content") or "")
    metadata = row.get("metadata") or {}
    combined = f"{content} {metadata}".lower()

    score = 0

    if _row_matches_industry(row, industry):
        score += 20

    useful_terms = [
        "feasibility",
        "startup",
        "setup",
        "investment",
        "project cost",
        "capital",
        "revenue",
        "profit",
        "break even",
        "break-even",
        "operating cost",
        "operational cost",
        "rent",
        "staff",
        "salary",
        "equipment",
        "fit out",
        "fit-out",
        "license",
        "licensing",
    ]

    for term in useful_terms:
        if term in combined:
            score += 2

    amount = _extract_benchmark_amount(row)
    if amount is not None:
        score += 8

        if client_budget and client_budget > 0:
            ratio = amount / client_budget

            # Strongest preference is around the user's budget.
            if 0.60 <= ratio <= 1.25:
                score += 12
            elif 0.35 <= ratio <= 1.75:
                score += 7
            elif ratio <= 2.50:
                score += 3

    return score


def _retrieve_balanced_business_discovery_context(
    message: str,
    include_private: bool,
    per_industry_limit: int = 2,
    max_total: int = 16,
) -> dict:
    """
    Scan approved knowledge across supported industries and return a balanced
    set of business-opportunity evidence.

    Important:
    - no product/service rows are used for this discovery context
    - one source cannot dominate simply because it has many chunks
    - up to `per_industry_limit` distinct sources are selected per industry
    """
    all_rows = _load_knowledge_rows()
    client_budget = _extract_budget_from_message(message)

    selected = []
    industry_summary = {}
    seen_global_sources = set()

    for industry in DISCOVERY_INDUSTRIES:
        candidates = []

        for row in all_rows:
            if _is_private_row(row) and not include_private:
                continue

            if not _row_matches_industry(row, industry):
                continue

            score = _discovery_row_score(
                row,
                industry,
                client_budget,
            )

            if score <= 0:
                continue

            candidates.append((score, row))

        candidates.sort(key=lambda pair: pair[0], reverse=True)

        chosen = []
        seen_industry_sources = set()

        for score, row in candidates:
            source_id = str(
                row.get("source_id")
                or row.get("id")
                or ""
            ).strip()

            dedupe_key = source_id or f"row:{row.get('id')}"

            if dedupe_key in seen_industry_sources:
                continue

            if dedupe_key in seen_global_sources:
                continue

            chosen.append(row)
            seen_industry_sources.add(dedupe_key)
            seen_global_sources.add(dedupe_key)

            if len(chosen) >= per_industry_limit:
                break

        if chosen:
            industry_summary[industry] = len(chosen)
            selected.extend(chosen)

        if len(selected) >= max_total:
            break

    selected = selected[:max_total]

    return {
        "knowledge": selected,
        "products": [],
        "services": [],
        "discovery_meta": {
            "client_budget": client_budget,
            "scanned_rows": len(all_rows),
            "industry_summary": industry_summary,
            "selected_sources": len(selected),
        },
    }


def _wants_business_start_guidance(message: str) -> bool:
    """
    Trigger the structured/intake guidance only after the client has named
    a specific supported industry.

    Broad questions such as:
    "I have 20,000 BHD. What business can I start?"
    are handled by business-idea discovery first.
    """
    low = (message or "").lower().strip()
    industry = _detect_industry(message)

    if not industry:
        return False

    industry_start_terms = [
        "start a business",
        "start business",
        "starting a business",
        "start the business",
        "starting the business",
        "set up a business",
        "setup a business",
        "set up the business",
        "setup the business",
        "open a business",
        "open business",
        "open the business",
        "business idea",
        "business opportunity",
        "want to start",
        "planning to start",
        "plan to start",
        "thinking to start",
        "thinking about starting",
        "know about",
        "know more about",
        "learn about",
        "interested in starting",
        "interested to start",
        "how to start",
        "what do i need to start",
        "what is needed to start",
        "new venture",
        "new business",
        "tell me about",
        "can i know about",
    ]

    return any(term in low for term in industry_start_terms)


def _business_start_intake_answer(message: str) -> str:
    industry = _detect_industry(message)
    industry_label = BUSINESS_INDUSTRY_LABELS.get(
        industry,
        (industry or "business").replace("_", " ")
    )

    questions = BUSINESS_INTAKE_QUESTIONS.get(
        industry,
        [
            "What is your approximate budget?",
            "Which country, city, or area are you planning to operate in?",
            "What specific type of business or concept are you considering?",
            "Who is your main target customer?",
            "Do you have previous experience in this sector?",
            "Will this be a startup from scratch or an existing business?",
        ],
    )

    lines = [
        f"Malriffaie Support is happy to assist you with your new venture in the {industry_label} industry.",
        "",
        "To give you the most relevant guidance using suitable market information and anonymized insights from similar projects, could you please share:",
        "",
    ]
    lines.extend([f"• {question}" for question in questions])
    lines.extend([
        "",
        "Once I have these details, I can guide you more accurately on setup requirements, likely investment, operations, risks, and relevant opportunities for this type of business.",
    ])
    return "\n".join(lines)


SIMILAR_BUSINESS_FAMILIES = {
    "food_service": {
        "topic_terms": [
            "restaurant", "restaurants", "cafe", "café", "coffee shop",
            "bakery", "takeaway", "cloud kitchen", "kiosk", "food service",
        ],
        "close_terms": [
            "restaurant", "restaurants", "cafe", "café", "coffee shop",
            "bakery", "takeaway", "cloud kitchen", "kiosk", "food service",
        ],
        "proxy_terms": [
            "hotel restaurant", "hotel f&b", "hotel f & b",
            "food and beverage", "f&b department", "f & b department",
        ],
    },
    "hospitality": {
        "topic_terms": [
            "hotel", "hotels", "resort", "hospitality", "guest house",
            "guesthouse", "serviced apartment", "serviced apartments",
        ],
        "close_terms": [
            "hotel", "hotels", "resort", "hospitality", "guest house",
            "guesthouse", "serviced apartment", "serviced apartments",
        ],
        "proxy_terms": [],
    },
    "food_processing": {
        "topic_terms": [
            "food processing", "food manufacturing", "snack manufacturing",
            "chocolate manufacturing", "food production", "food factory",
        ],
        "close_terms": [
            "food processing", "food manufacturing", "snack manufacturing",
            "chocolate manufacturing", "food production", "food factory",
        ],
        "proxy_terms": ["packaging", "production line"],
    },
    "light_manufacturing": {
        "topic_terms": [
            "cap manufacturing", "caps manufacturing", "cap business",
            "caps business", "hat manufacturing", "hats manufacturing",
            "headwear", "apparel", "garment", "garments", "textile",
            "clothing", "light manufacturing", "embroidery",
            "printing factory", "manufacturing", "factory", "production",
        ],
        "close_terms": [
            "cap", "caps", "hat", "hats", "headwear", "apparel",
            "garment", "garments", "textile", "clothing",
            "light manufacturing", "embroidery", "printing",
            "manufacturing", "factory", "production",
        ],
        "proxy_terms": ["packaging manufacturing", "small manufacturing"],
    },
    "beauty": {
        "topic_terms": [
            "salon", "beauty", "spa", "hair salon", "nail salon",
            "barber", "barbershop", "massage center", "massage centre",
        ],
        "close_terms": [
            "salon", "beauty", "spa", "hair", "nail", "barber", "massage",
        ],
        "proxy_terms": [],
    },
    "healthcare": {
        "topic_terms": [
            "healthcare", "health care", "medical", "clinic", "medical center",
            "medical centre", "home care", "homecare", "nursing", "wellness",
            "pharmacy", "dental", "physiotherapy", "laboratory",
        ],
        "close_terms": [
            "healthcare", "health care", "medical", "clinic", "medical center",
            "medical centre", "home care", "homecare", "nursing", "wellness",
            "pharmacy", "dental", "physiotherapy", "laboratory",
        ],
        "proxy_terms": [],
    },
    "construction": {
        "topic_terms": [
            "construction", "contracting", "contractor", "fit out",
            "fit-out", "civil works",
        ],
        "close_terms": [
            "construction", "contracting", "contractor", "fit out",
            "fit-out", "civil works",
        ],
        "proxy_terms": [],
    },
    "retail": {
        "topic_terms": [
            "retail", "shop", "store", "boutique", "ecommerce", "e-commerce",
        ],
        "close_terms": [
            "retail", "shop", "store", "boutique", "ecommerce", "e-commerce",
        ],
        "proxy_terms": [],
    },
    "fitness": {
        "topic_terms": [
            "gym", "fitness", "health club", "sports center", "sports centre",
        ],
        "close_terms": [
            "gym", "fitness", "health club", "sports center", "sports centre",
        ],
        "proxy_terms": [],
    },
    "agriculture": {
        "topic_terms": [
            "farming", "farm", "agriculture", "agricultural", "greenhouse",
            "horticulture", "crop", "crops", "seeds", "nuts",
        ],
        "close_terms": [
            "farming", "farm", "agriculture", "agricultural", "greenhouse",
            "horticulture", "crop", "crops", "seeds", "nuts",
        ],
        "proxy_terms": [],
    },
}

FOLLOWUP_METRIC_TERMS = {
    "salary": [
        "salary", "salaries", "wage", "wages", "payroll",
        "compensation", "monthly pay",
    ],
    "staffing": [
        "staff", "staffing", "employee", "employees", "worker", "workers",
        "manpower", "headcount", "labor", "labour",
    ],
    "expenses": [
        "expense", "expenses", "operating cost", "operational cost",
        "overhead", "overheads", "utilities", "marketing cost",
        "packaging cost", "maintenance cost",
    ],
    "equipment": [
        "equipment", "machinery", "machine", "machines", "tools",
        "production line",
    ],
    "rent": ["rent", "rental", "lease", "premises"],
    "budget": [
        "budget", "startup cost", "setup cost", "initial investment",
        "investment", "project cost", "capital", "capex",
    ],
    "revenue": ["revenue", "sales", "turnover", "income"],
    "profit": ["profit", "margin", "net income", "gross profit"],
    "licensing": ["license", "licence", "licensing", "permit", "approval"],
    "marketing": [
        "marketing", "marketing strategy", "marketing strategies",
        "marketing plan", "promotion", "advertising", "social media",
        "customer acquisition", "branding", "brand awareness",
        "sales strategy", "go to market", "go-to-market",
    ],
}


def _normalize_search_text(value) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _contains_search_term(text_value: str, term: str) -> bool:
    text_low = _normalize_search_text(text_value)
    term_low = _normalize_search_text(term)

    if not term_low:
        return False

    if " " in term_low or "-" in term_low or "&" in term_low:
        return term_low in text_low

    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(term_low)}(?![a-z0-9])",
            text_low,
            flags=re.IGNORECASE,
        )
    )


def _detect_business_family(text_value: str) -> str | None:
    low = _normalize_search_text(text_value)

    # Specific food-processing must be checked before generic manufacturing.
    family_order = [
        "food_service",
        "food_processing",
        "hospitality",
        "light_manufacturing",
        "beauty",
        "healthcare",
        "construction",
        "retail",
        "fitness",
        "agriculture",
    ]

    for family in family_order:
        config = SIMILAR_BUSINESS_FAMILIES[family]
        if any(_contains_search_term(low, term) for term in config["topic_terms"]):
            return family

    return None


def _detect_followup_metric(message: str) -> str:
    low = _normalize_search_text(message)

    for metric, terms in FOLLOWUP_METRIC_TERMS.items():
        if any(_contains_search_term(low, term) for term in terms):
            return metric

    return "general"


def _resolve_followup_metric(message: str, recent_rows: list[dict]) -> str:
    metric = _detect_followup_metric(message)

    if metric != "general":
        return metric

    # "Can you share the average breakdown?" should inherit the last concrete
    # metric, e.g. expenses, instead of becoming a random new search.
    for row in reversed(recent_rows or []):
        previous = str(row.get("message") or "").strip()
        previous_metric = _detect_followup_metric(previous)
        if previous_metric != "general":
            return previous_metric

    return "general"


def _has_explicit_business_topic(message: str) -> bool:
    low = _normalize_search_text(message)

    if _detect_business_family(low):
        return True

    explicit_markers = [
        "manufacturing", "factory", "production", "trading", "restaurant",
        "cafe", "café", "hotel", "salon", "clinic", "construction",
        "retail", "gym", "farming",
    ]

    return any(_contains_search_term(low, marker) for marker in explicit_markers)


def _is_contextual_followup(message: str) -> bool:
    low = _normalize_search_text(message)

    if not low:
        return False

    # If the current message itself clearly names the business, treat it as a
    # new/explicit topic message, not as an ambiguous follow-up.
    if _has_explicit_business_topic(low):
        return False

    markers = [
        "how many staff", "how many employees", "staff salary", "staff salaries",
        "what will be the salary", "what is the salary", "is it for all",
        "is that for all", "other expenses", "other expense", "other costs",
        "other cost", "average breakdown", "cost breakdown", "breakdown for this",
        "what about", "how much", "what will be", "what would be",
        "can you share", "can you explain", "more details", "continue",
        "yes please",
    ]

    if any(marker in low for marker in markers):
        return True

    words = _query_words(low)
    generic = {
        "staff", "employee", "employees", "salary", "salaries", "expense",
        "expenses", "cost", "costs", "equipment", "rent", "revenue", "profit",
        "breakdown", "average", "required", "need", "monthly", "yearly",
    }

    meaningful = [word for word in words if word not in generic]
    return len(words) <= 8 and len(meaningful) <= 2


def _topic_anchor_terms(text_value: str) -> list[str]:
    words = _query_words(text_value)
    noise = {
        "prefer", "choose", "chosen", "choice", "want", "know", "about",
        "more", "could", "should", "like", "idea", "option", "category",
        "selected", "select", "explore", "further", "please", "explain",
        "details", "detail", "start", "starting", "business", "company",
        "okay", "ok",
    }

    anchors = []

    for word in words:
        if word in noise or word.isdigit() or len(word) < 3:
            continue
        if word not in anchors:
            anchors.append(word)

    return anchors[:5]


def _find_recent_business_topic(
    rows: list[dict],
) -> tuple[str | None, list[str], str | None]:
    """
    Find the latest explicit business topic from CUSTOMER messages only.
    Assistant responses are intentionally ignored so a bad AI answer cannot
    silently change the active business topic.
    """
    for row in reversed(rows or []):
        customer_message = str(row.get("message") or "").strip()

        if not customer_message:
            continue

        if _is_contextual_followup(customer_message):
            continue

        if not _has_explicit_business_topic(customer_message):
            continue

        anchors = _topic_anchor_terms(customer_message)
        family = _detect_business_family(customer_message)

        if anchors:
            return customer_message, anchors, family

    return None, [], None


def _row_text(row: dict) -> str:
    metadata = row.get("metadata") or {}
    return _normalize_search_text(
        f"{row.get('content') or ''} {metadata}"
    )


def _row_contains_metric(row: dict, metric: str) -> bool:
    if metric == "general":
        return True

    text_value = _row_text(row)
    terms = FOLLOWUP_METRIC_TERMS.get(metric, [])
    return any(_contains_search_term(text_value, term) for term in terms)


def _row_exact_topic_score(row: dict, anchors: list[str]) -> int:
    if not anchors:
        return 0

    text_value = _row_text(row)
    matched = sum(
        1 for anchor in anchors
        if _contains_search_term(text_value, anchor)
    )

    if len(anchors) == 1:
        return 100 if matched == 1 else 0

    if matched >= 2:
        return 100 + (matched * 5)

    return 0


def _row_similarity_level(
    row: dict,
    target_family: str | None,
    metric: str,
) -> tuple[int, str]:
    """
    Allow proxy borrowing only from operationally sensible similar businesses.
    Numeric borrowing also requires evidence relevant to the requested metric.
    """
    if not target_family:
        return 0, ""

    text_value = _row_text(row)
    row_family = _detect_business_family(text_value)
    config = SIMILAR_BUSINESS_FAMILIES.get(target_family) or {}

    if metric != "general" and not _row_contains_metric(row, metric):
        return 0, ""

    # Same family: strong proxy.
    if row_family == target_family:
        if any(
            _contains_search_term(text_value, term)
            for term in config.get("close_terms", [])
        ):
            return 80, "similar business"

    # Explicit cross-family proxy terms only. This is how hotel F&B can help a
    # restaurant/cafe question without using whole-hotel costs.
    if any(
        _contains_search_term(text_value, term)
        for term in config.get("proxy_terms", [])
    ):
        return 60, "broader industry proxy"

    return 0, ""


def _load_products_and_services() -> tuple[list[dict], list[dict]]:
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

    return products, services


def _retrieve_followup_business_context(
    message: str,
    recent_rows: list[dict],
    include_private: bool,
    limit: int = 8,
) -> tuple[dict, dict]:
    """
    Retrieve exact-topic evidence first. If the exact topic does not contain
    enough evidence for the requested metric, add carefully-labelled proxy
    evidence from similar businesses.
    """
    topic_message, anchors, family = _find_recent_business_topic(recent_rows)
    metric = _resolve_followup_metric(message, recent_rows)

    meta = {
        "active_topic": topic_message,
        "anchors": anchors,
        "family": family,
        "metric": metric,
        "exact_sources": 0,
        "proxy_sources": 0,
    }

    if not topic_message or not anchors:
        fallback = retrieve_context(
            message,
            limit=limit,
            include_private=include_private,
        )
        return fallback, meta

    all_rows = _load_knowledge_rows()
    exact_source_ids = set()

    # Identify sources that clearly belong to the selected exact topic.
    for row in all_rows:
        if _is_private_row(row) and not include_private:
            continue

        if _row_exact_topic_score(row, anchors) > 0:
            source_id = str(row.get("source_id") or row.get("id") or "").strip()
            if source_id:
                exact_source_ids.add(source_id)

    exact_candidates = []
    proxy_candidates = []

    metric_terms = " ".join(FOLLOWUP_METRIC_TERMS.get(metric, []))
    relevance_query = f"{topic_message} {message} {metric_terms}".strip()

    for row in all_rows:
        if _is_private_row(row) and not include_private:
            continue

        source_id = str(row.get("source_id") or row.get("id") or "").strip()
        relevance = _score_knowledge_row(row, relevance_query)

        # Exact business/source always gets priority. Rows containing the
        # requested metric get an additional boost.
        if source_id and source_id in exact_source_ids:
            metric_bonus = 30 if _row_contains_metric(row, metric) else 0
            exact_candidates.append((200 + metric_bonus + relevance, row))
            continue

        proxy_score, proxy_label = _row_similarity_level(row, family, metric)
        if proxy_score > 0:
            row_copy = dict(row)
            row_copy["_rag_match_level"] = proxy_label
            row_copy["_rag_family"] = family
            proxy_candidates.append((proxy_score + relevance, row_copy))

    exact_candidates.sort(key=lambda pair: pair[0], reverse=True)
    proxy_candidates.sort(key=lambda pair: pair[0], reverse=True)

    selected = []
    seen_chunks = set()

    # Prefer up to 5 exact-topic chunks.
    for _, row in exact_candidates:
        source_key = str(row.get("source_id") or row.get("id") or "")
        content_key = (source_key, str(row.get("content") or "")[:160])

        if content_key in seen_chunks:
            continue

        row_copy = dict(row)
        row_copy["_rag_match_level"] = "exact topic"
        row_copy["_rag_family"] = family
        selected.append(row_copy)
        seen_chunks.add(content_key)

        if len(selected) >= min(5, limit):
            break

    # Fill remaining slots using sensible proxy evidence only.
    for _, row in proxy_candidates:
        if len(selected) >= limit:
            break

        source_key = str(row.get("source_id") or row.get("id") or "")
        content_key = (source_key, str(row.get("content") or "")[:160])

        if content_key in seen_chunks:
            continue

        selected.append(row)
        seen_chunks.add(content_key)

    meta["exact_sources"] = len({
        row.get("source_id") or row.get("id")
        for row in selected
        if row.get("_rag_match_level") == "exact topic"
    })
    meta["proxy_sources"] = len({
        row.get("source_id") or row.get("id")
        for row in selected
        if row.get("_rag_match_level") != "exact topic"
    })

    products, services = _load_products_and_services()

    return {
        "knowledge": selected,
        "products": products,
        "services": services,
    }, meta


def _format_followup_knowledge_context(rows: list[dict]) -> str:
    blocks = []

    for row in rows:
        level = row.get("_rag_match_level") or "retrieved knowledge"
        content = str(row.get("content") or "")[:1200].strip()

        if not content:
            continue

        blocks.append(f"[Evidence level: {level}]\n{content}")

    return "\n---\n".join(blocks)


def _load_recent_conversation(visitor_id: str | None, limit: int = 6) -> list[dict]:
    if not visitor_id:
        return []

    try:
        rows = (
            supabase
            .table("chat_messages")
            .select("message,response,created_at")
            .eq("visitor_id", visitor_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        return list(reversed(rows))
    except Exception:
        return []


def _conversation_to_prompt(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        customer_message = str(row.get("message") or "").strip()
        assistant_response = str(row.get("response") or "").strip()

        if customer_message:
            lines.append(f"Customer: {customer_message}")
        if assistant_response:
            lines.append(f"Assistant: {assistant_response}")

    return "\n".join(lines)


def _recent_business_industry(rows: list[dict]) -> str | None:
    # Use customer messages only. Assistant responses may contain an earlier
    # retrieval mistake and must never redefine the user's active industry.
    for row in reversed(rows):
        industry = _detect_industry(str(row.get("message") or ""))
        if industry:
            return industry
    return None


def _row_matches_industry(row: dict, industry: str) -> bool:
    if not industry:
        return False

    metadata = row.get("metadata") or {}
    content = (row.get("content") or "").lower()
    meta_text = str(metadata).lower()

    if isinstance(metadata, dict):
        explicit = (
            metadata.get("industry")
            or metadata.get("dataset")
            or metadata.get("sector")
            or metadata.get("business_type")
        )
        if isinstance(explicit, str) and explicit.strip().lower() == industry:
            return True

    terms_map = {
        "healthcare": ["healthcare", "health care", "medical", "clinic", "home care", "homecare", "nursing", "wellness", "pharmacy", "dental"],
        "salon": ["salon", "beauty", "spa", "hair", "nail", "barber", "massage"],
        "hotel": ["hotel", "hospitality", "resort", "guest house", "guesthouse", "serviced apartment"],
        "cafe": ["cafe", "café", "coffee", "restaurant", "food", "bakery", "cloud kitchen", "takeaway"],
        "construction": ["construction", "contracting", "contractor", "building materials", "fit out", "fit-out", "civil works"],
        "retail": ["retail", "store", "shop", "boutique", "ecommerce", "e-commerce"],
        "education": ["education", "school", "nursery", "training", "academy", "institute"],
        "gym": ["gym", "fitness", "sports center", "sports centre", "health club"],
        "farming": [
            "farming", "farm", "farms", "agriculture", "agricultural", "agri",
            "seed", "seeds", "nut", "nuts", "crop", "crops", "produce",
            "horticulture", "plantation", "greenhouse", "irrigation"
        ],
    }

    return any(term in content or term in meta_text for term in terms_map.get(industry, [industry]))


def _benchmark_enabled(row: dict) -> bool:
    metadata = row.get("metadata") or {}

    if isinstance(metadata, dict):
        if metadata.get("benchmark_enabled") is False:
            return False
        if metadata.get("benchmark_enabled") is True:
            return True

    return row.get("source_type") == "google_drive"


def _extract_bhd_amounts(text: str) -> list[float]:
    text = text or ""
    amounts = []

    patterns = [
        r'(?i)(?:BHD|BD|B\.D\.|د\.ب)\s*([0-9][0-9,]*(?:\.[0-9]+)?)',
        r'(?i)([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:BHD|BD|B\.D\.|د\.ب)',
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text):
            try:
                value = float(str(match).replace(",", ""))
                if value > 0:
                    amounts.append(value)
            except Exception:
                pass

    return amounts


def _extract_benchmark_amount(row: dict) -> float | None:
    metadata = row.get("metadata") or {}

    if isinstance(metadata, dict):
        for key in [
            "benchmark_amount",
            "startup_budget",
            "setup_budget",
            "startup_cost",
            "setup_cost",
            "initial_investment",
            "investment_amount",
            "total_project_cost",
        ]:
            value = metadata.get(key)
            if value not in (None, ""):
                try:
                    return float(str(value).replace(",", ""))
                except Exception:
                    pass

    content = row.get("content") or ""
    priority_phrases = [
        "startup budget", "setup budget", "startup cost", "setup cost",
        "initial investment", "total investment", "total project cost",
        "capital required", "investment required", "project cost",
    ]

    lines = [line.strip() for line in content.splitlines() if line.strip()]

    for phrase in priority_phrases:
        for line in lines:
            if phrase in line.lower():
                amounts = _extract_bhd_amounts(line)
                if amounts:
                    return max(amounts)

    amounts = _extract_bhd_amounts(content)
    if len(amounts) == 1:
        return amounts[0]

    return None


def _load_synced_benchmark_rows(industry: str) -> list[dict]:
    rows = _load_knowledge_rows()
    matched = []

    for row in rows:
        if row.get("source_type") != "google_drive":
            continue
        if not _is_private_row(row):
            continue
        if not _benchmark_enabled(row):
            continue
        if not _row_matches_industry(row, industry):
            continue
        matched.append(row)

    return matched


def _safe_int(value, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _safe_template(template: str, **values) -> str:
    try:
        return str(template).format(**values)
    except Exception:
        return str(template)


def _build_anonymized_benchmark_answer(
    message: str,
    cfg: dict | None = None,
) -> str | None:
    cfg = cfg or {}

    industry = _detect_industry(message)
    if not industry:
        return None

    rows = _load_synced_benchmark_rows(industry)

    grouped = {}
    for row in rows:
        source_id = row.get("source_id") or row.get("id")
        grouped.setdefault(source_id, []).append(row)

    case_amounts = []

    for source_rows in grouped.values():
        values = []
        for row in source_rows:
            amount = _extract_benchmark_amount(row)
            if amount is not None:
                values.append(amount)

        if values:
            case_amounts.append(max(values))

    minimum_cases = _safe_int(cfg.get("benchmark_min_cases"), 3)
    count = len(case_amounts)
    industry_label = industry.replace("_", " ").title()

    if count < minimum_cases:
        default_message = (
            "I found {count} eligible anonymized {industry} case{plural} "
            "in the synced private knowledge base. "
            "At least {minimum} distinct cases are required before I provide "
            "an aggregate budget benchmark."
        )

        template = cfg.get("benchmark_insufficient_message") or default_message

        return _safe_template(
            template,
            count=count,
            industry=industry,
            industry_label=industry_label,
            minimum=minimum_cases,
            plural="s" if count != 1 else "",
        )

    avg_value = mean(case_amounts)
    median_value = median(case_amounts)
    min_value = min(case_amounts)
    max_value = max(case_amounts)

    default_intro = (
        "Based on {count} anonymized {industry_label} cases "
        "in the synced private knowledge base:"
    )
    intro_template = cfg.get("benchmark_result_intro") or default_intro
    intro = _safe_template(
        intro_template,
        count=count,
        industry=industry,
        industry_label=industry_label,
        minimum=minimum_cases,
        plural="s" if count != 1 else "",
    )

    default_footer = (
        "This is an aggregate internal benchmark only.\n"
        "Individual business names, identities, source files, "
        "and record-level amounts are not disclosed."
    )
    footer = cfg.get("benchmark_result_footer") or default_footer

    return "\n".join(
        [
            intro,
            "",
            f"Average setup/startup budget: {_format_price(avg_value, 'BHD')}",
            f"Median setup/startup budget: {_format_price(median_value, 'BHD')}",
            f"Observed range: {_format_price(min_value, 'BHD')} to {_format_price(max_value, 'BHD')}",
            "",
            str(footer).strip(),
        ]
    )




def _truncate_at_word_boundary(text: str, max_chars: int = 900) -> str:
    """
    Truncate fallback knowledge without cutting a word in half.
    Prefer ending on sentence punctuation when possible.
    """
    value = " ".join(str(text or "").split())

    if not value:
        return ""

    if len(value) <= max_chars:
        return value

    shortened = value[:max_chars]

    # Prefer a complete sentence reasonably close to the limit.
    sentence_end = max(
        shortened.rfind("."),
        shortened.rfind("!"),
        shortened.rfind("?"),
        shortened.rfind("؟"),
    )

    if sentence_end >= int(max_chars * 0.55):
        shortened = shortened[: sentence_end + 1]
    elif " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]

    return shortened.rstrip(" ,;:-") + "..."



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
        or "Qwen/Qwen3-8B"
    )

    model_name = _clean_model_name(
        model_name or default_model,
        fallback="Qwen/Qwen3-8B",
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


def _knowledge_source_name(row: dict) -> str:
    """
    Best-effort readable source label for temporary RAG testing.
    """
    metadata = row.get("metadata") or {}

    if isinstance(metadata, dict):
        for key in (
            "name",
            "filename",
            "file_name",
            "title",
            "source_name",
            "document_name",
            "original_name",
        ):
            value = metadata.get(key)
            if value:
                return str(value).strip()

    return str(
        row.get("source_id")
        or row.get("id")
        or "Unknown source"
    ).strip()


def _append_test_sources(answer: str, knowledge_rows: list[dict]) -> str:
    """
    TEMPORARY TESTING ONLY.

    Append unique source names, source IDs, and retrieval evidence levels to
    the customer-visible answer so RAG behavior can be verified.
    """
    if not SHOW_RAG_SOURCES_TO_CLIENT:
        return answer

    if not knowledge_rows:
        return answer

    lines = []
    seen = set()

    for row in knowledge_rows:
        source_id = str(
            row.get("source_id")
            or row.get("id")
            or ""
        ).strip()

        source_name = _knowledge_source_name(row)
        match_level = str(row.get("_rag_match_level") or "retrieved").strip()
        unique_key = (source_id, source_name, match_level)

        if unique_key in seen:
            continue

        seen.add(unique_key)

        suffix = f" | Match: {match_level}"

        if source_id and source_name and source_name != source_id:
            lines.append(
                f"- {source_name} | Source ID: {source_id}{suffix}"
            )
        elif source_id:
            lines.append(f"- Source ID: {source_id}{suffix}")
        else:
            lines.append(f"- {source_name}{suffix}")

    if not lines:
        return answer

    return (
        str(answer or "").rstrip()
        + "\n\n"
        + "TEST RAG SOURCES:\n"
        + "\n".join(lines)
    )


async def answer_chat(
    message: str,
    visitor_id: str | None = None,
    lang: str = "en",
    ip_hash: str | None = None,
    client_logged_in: bool = False,
) -> dict:
    cfg = _latest_ai_settings()

    # Structured business assessment is accepted only for logged-in clients/admins.
    assessment = (
        _parse_business_assessment(message)
        if client_logged_in
        else None
    )

    business_idea_discovery = (
        client_logged_in
        and not assessment
        and _wants_business_idea_discovery(message)
    )

    # Load recent conversation BEFORE retrieval. This prevents short follow-up
    # questions from drifting into unrelated projects.
    recent_conversation = (
        _load_recent_conversation(visitor_id, limit=12)
        if client_logged_in
        else []
    )

    marketing_choice = _parse_marketing_choice(
        message,
        recent_conversation,
    )

    marketing_choice_offer = (
        not assessment
        and marketing_choice is None
        and _should_offer_marketing_choice(message)
    )

    marketing_advice_mode = (
        marketing_choice == "advice"
        or (
            _is_marketing_topic(message)
            and _declines_product_sales(message)
        )
    )

    contextual_followup = (
        client_logged_in
        and not assessment
        and not business_idea_discovery
        and (
            _is_contextual_followup(message)
            or marketing_advice_mode
        )
    )

    followup_meta = {
        "active_topic": None,
        "anchors": [],
        "family": None,
        "metric": "general",
        "exact_sources": 0,
        "proxy_sources": 0,
    }

    if assessment:
        retrieval_query = _business_assessment_search_query(assessment)
        ctx = retrieve_context(
            retrieval_query,
            limit=8,
            include_private=client_logged_in,
        )

    elif business_idea_discovery:
        retrieval_query = _business_idea_discovery_search_query(message)
        ctx = _retrieve_balanced_business_discovery_context(
            message=message,
            include_private=client_logged_in,
            per_industry_limit=2,
            max_total=16,
        )

    elif contextual_followup:
        followup_retrieval_message = (
            "marketing strategy marketing plan promotion advertising social media "
            "branding customer acquisition sales strategy cost effective"
            if marketing_choice == "advice"
            else message
        )
        retrieval_query = followup_retrieval_message
        ctx, followup_meta = _retrieve_followup_business_context(
            message=followup_retrieval_message,
            recent_rows=recent_conversation,
            include_private=client_logged_in,
            limit=8,
        )

    elif marketing_advice_mode:
        # Public/non-contextual advice can still search approved public
        # marketing knowledge even though there is no logged-in topic lock.
        retrieval_query = (
            "marketing strategy marketing plan promotion advertising social media "
            "branding customer acquisition sales strategy cost effective"
        )
        ctx = retrieve_context(
            retrieval_query,
            limit=8,
            include_private=client_logged_in,
        )

    else:
        retrieval_query = message
        ctx = retrieve_context(
            retrieval_query,
            limit=8,
            include_private=client_logged_in,
        )

    print(
        "RAG_DEBUG:",
        {
            "query": retrieval_query,
            "client_logged_in": client_logged_in,
            "business_idea_discovery": business_idea_discovery,
            "marketing_choice": marketing_choice,
            "marketing_choice_offer": marketing_choice_offer,
            "marketing_advice_mode": marketing_advice_mode,
            "contextual_followup": contextual_followup,
            "followup_meta": followup_meta,
            "knowledge_count": len(ctx.get("knowledge") or []),
            "discovery_meta": (
                ctx.get("discovery_meta")
                if business_idea_discovery
                else None
            ),
            "sources": [
                {
                    "source_id": row.get("source_id"),
                    "source_type": row.get("source_type"),
                    "access_level": _row_access_level(row),
                    "match_level": row.get("_rag_match_level"),
                    "preview": str(row.get("content") or "")[:160],
                }
                for row in (ctx.get("knowledge") or [])[:8]
            ],
        },
        flush=True,
    )

    # Start with no product recommendations. Products are only attached
    # after a matching product or recommendation intent.
    recommended = []
    answer = None
    used_knowledge = False

    # 0. Greetings are answered locally from the editable Admin Dashboard greeting.
    # Do not call Hugging Face and do not show product cards for greetings.
    if _is_greeting(message):
        answer = (
            cfg.get("chat_greeting")
            or "Hi! Welcome to Malriffaie AI Concierge. How can I help you today?"
        )
        recommended = []

    # Logged-in clients/admins can request anonymized aggregate benchmarks
    # from synced private Google Drive knowledge.
    elif client_logged_in and _wants_anonymized_benchmark(message):
        benchmark_answer = _build_anonymized_benchmark_answer(message, cfg)
        if benchmark_answer:
            answer = benchmark_answer
            recommended = []
            used_knowledge = False

    elif (
        client_logged_in
        and not assessment
        and not business_idea_discovery
        and _wants_business_start_guidance(message)
    ):
        answer = _business_start_intake_answer(message)
        recommended = []
        used_knowledge = False

    # Structured business assessments must bypass all normal product/service
    # routing. They are analyzed only by the assessment RAG/AI path below.
    if assessment:
        recommended = []

    # Marketing questions can be ambiguous: the client may want either the
    # paid Marketing Strategy product or practical AI guidance. Offer both.
    elif answer is None and marketing_choice_offer:
        answer = _marketing_choice_answer()
        recommended = []
        used_knowledge = False

    # Choice 1: show the Marketing Strategy product and purchase card.
    elif answer is None and marketing_choice == "product":
        marketing_product = _find_marketing_product(ctx.get("products") or [])

        if marketing_product:
            answer = _product_detail_answer(marketing_product)
            recommended = [marketing_product]
        else:
            answer = (
                "The Marketing Strategy Package is not currently available in the product catalog. "
                "You can choose AI Marketing Suggestions instead, or contact support for help."
            )
            recommended = []

        used_knowledge = False

    # Choice 2 intentionally leaves answer=None so the RAG/AI advisory path
    # below can generate knowledge-based marketing suggestions.

    # 1. Service-list/service-description questions.
    # This must be checked before product recommendation logic.
    elif (
        answer is None
        and not business_idea_discovery
        and _wants_service_list(message)
    ):
        answer = _service_list_answer(ctx["services"])
        recommended = []

    # 2. Product-list questions.
    elif (
        answer is None
        and not business_idea_discovery
        and _wants_product_list(message)
    ):
        answer = _product_list_answer(ctx["products"])
        # Return every available product so the frontend can render the full list.
        recommended = ctx["products"]

    # 3. Booking/consultation questions.
    elif (
        answer is None
        and not business_idea_discovery
        and _wants_booking(message)
    ):
        answer = _booking_answer(ctx["services"])
        recommended = []

    elif answer is None:
        service = (
            None
            if (business_idea_discovery or marketing_advice_mode)
            else _matched_service(message, ctx["services"])
        )
        product = (
            None
            if (business_idea_discovery or marketing_advice_mode)
            else _matched_product(message, ctx["products"])
        )

        detail_words = [
            "tell",
            "detail",
            "price",
            "about",
            "more",
            "know",
            "explain",
            "what is",
            "what about",
            "cost",
            "describe",
        ]

        # 4. Specific service detail questions.
        if service and any(k in message.lower() for k in detail_words):
            answer = _service_detail_answer(service)
            recommended = []

        # 5. Specific product detail questions.
        elif product and any(k in message.lower() for k in detail_words + ["buy"]):
            answer = _product_detail_answer(product)
            recommended = [product]

        # 6. Only genuine recommendation requests use product recommendations.
        elif (
            not business_idea_discovery
            and not contextual_followup
            and not marketing_advice_mode
            and marketing_choice is None
            and _wants_recommendation(message)
        ):
            answer, recommended = _recommendation_answer(
                message,
                ctx["products"],
                ctx["services"],
            )

    # 6. Only block private/internal knowledge questions after public answers fail.
    # This preserves the main idea:
    # - end users can access public products/services/booking/public knowledge
    # - private/internal Google Drive wiki requires client/admin login
    if (
        answer is None
        and not client_logged_in
        and not _is_public_product_or_service_question(message)
        and _private_knowledge_match_exists(message)
    ):
        return {
            "answer": PRIVATE_KNOWLEDGE_MESSAGE,
            "products": [],
            "sources": [],
        }

    # 7. If no deterministic public answer, use AI with allowed context.
    if answer is None:
        used_knowledge = bool(ctx["knowledge"])

        prompt_template = cfg.get("system_prompt") or DEFAULT_PROMPT

        prompt = prompt_template.format(
            site="Malriffaie",
            site_url="",
            url="",
            lang=lang,
            date=date.today().isoformat(),
        )

        if assessment:
            assessment_knowledge = ctx["knowledge"][:5]

            prompt += "\n\nKnowledge context:\n" + "\n---\n".join(
                [k.get("content", "")[:900] for k in assessment_knowledge]
            )

        elif business_idea_discovery:
            # IMPORTANT: Do not include Malriffaie product/service catalog here.
            # The user is asking which BUSINESS they could start, not which
            # Malriffaie service/product to buy.
            discovery_rows = ctx.get("knowledge") or []

            prompt += (
                "\n\nBUSINESS OPPORTUNITY KNOWLEDGE CONTEXT:\n"
                + "\n---\n".join(
                    [k.get("content", "")[:1200] for k in discovery_rows]
                )
            )

            discovery_meta = ctx.get("discovery_meta") or {}
            client_budget = discovery_meta.get("client_budget")

            if client_budget:
                prompt += (
                    "\n\nClient stated budget: "
                    f"{_format_price(client_budget, 'BHD')}"
                )

            prompt += (
                "\n\nThe context above contains anonymized knowledge from "
                "multiple business categories. Treat each category as a possible "
                "business opportunity only when the context provides relevant "
                "support. Do not treat Malriffaie consulting products or services "
                "as businesses the client can start."
            )

        elif marketing_advice_mode:
            # Marketing advice must use relevant knowledge and the active
            # business topic. Do not feed the product/service sales catalog
            # into this advisory generation step.
            if contextual_followup and followup_meta.get("active_topic"):
                prompt += (
                    "\n\nMARKETING ADVISORY KNOWLEDGE CONTEXT:\n"
                    + _format_followup_knowledge_context(
                        ctx.get("knowledge") or []
                    )
                )
            else:
                prompt += "\n\nMARKETING ADVISORY KNOWLEDGE CONTEXT:\n" + "\n---\n".join(
                    [k.get("content", "")[:1200] for k in (ctx.get("knowledge") or [])]
                )

        else:
            if contextual_followup and followup_meta.get("active_topic"):
                prompt += (
                    "\n\nFOLLOW-UP KNOWLEDGE CONTEXT:\n"
                    + _format_followup_knowledge_context(
                        ctx.get("knowledge") or []
                    )
                )
            else:
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

        knowledge_count = len(ctx.get("knowledge") or [])

        if knowledge_count > 0:
            prompt += (
                f"\n\nIMPORTANT: {knowledge_count} relevant approved knowledge-base "
                "chunk(s) were retrieved for this question. "
                "Use that knowledge to answer the customer's actual topic. "
                "Do not say that Malriffaie has no information on the topic when "
                "relevant approved knowledge has been supplied in the Knowledge context. "
                "Do not replace the requested topic with generic company products or services."
            )

            if business_idea_discovery:
                prompt += (
                    "\nFor this discovery request, the retrieved context may intentionally "
                    "contain multiple industries. Compare only the business ideas actually "
                    "supported by that context and the client's budget."
                )

        if business_idea_discovery:
            prompt += (
                "\n\nBusiness idea discovery instructions:\n"
                "1. The client has NOT chosen an industry yet. Do not ask them to complete "
                "the Business Assessment form at this stage.\n"
                "2. Suggest 3 to 5 ACTUAL BUSINESS CATEGORIES the client could consider "
                "starting. Examples of categories are cafe, salon, retail, farming, gym, "
                "education, healthcare, hospitality, or construction when supported by context.\n"
                "3. NEVER present Malriffaie products/services such as Marketing Strategy, "
                "HR Manual, Partnership Agreement, Feasibility Study, Retainer Membership, "
                "or Consultation as businesses the client could start.\n"
                "4. Use the client's stated budget and only the approved multi-industry "
                "knowledge supplied above.\n"
                "5. Briefly explain why each suggested business may fit, including setup "
                "intensity, staffing, operating complexity, and main risks only where supported.\n"
                "6. Do not claim any option is guaranteed to be profitable. Use wording such as "
                "'may be suitable', 'appears achievable', or 'worth exploring'.\n"
                "7. Do not invent exact setup costs, profit margins, revenue, ROI, or break-even "
                "figures that are not supported by approved knowledge.\n"
                "8. If one industry appears to exceed the budget based on available evidence, "
                "say so and avoid ranking it as a strong fit.\n"
                "9. Prefer diversity: do not return three variations of the same industry when "
                "credible alternatives exist.\n"
                "10. Finish by asking which suggested business the client wants to explore. "
                "After the client chooses one, the structured Business Assessment can be used.\n"
                "11. Do not redirect to consultation or products unless the client asks for them."
            )

        if marketing_advice_mode:
            prompt += (
                "\n\nMARKETING ADVISORY MODE:\n"
                "The client chose practical AI marketing guidance instead of the product path.\n"
                "1. Give practical marketing strategies for the client's active business topic.\n"
                "2. Use only the approved knowledge supplied in this prompt and relevant recent conversation.\n"
                "3. Do not sell, promote, price, or recommend the Malriffaie Marketing Strategy Package in this answer.\n"
                "4. If the client asked for cost-effective ideas, prioritize low-cost and measurable actions supported by the knowledge.\n"
                "5. Keep the advice specific to the active business. Do not switch industries.\n"
                "6. Do not invent current-market claims, statistics, costs, or performance results that are not supported by the approved context.\n"
                "7. If useful knowledge is missing, say what is missing rather than turning the answer into a product sales response.\n"
                "8. Structure the answer as clear actions, suggested channels, and practical next steps."
            )

        if assessment:
            prompt += "\n\nStructured client business assessment:\n"
            prompt += _business_assessment_profile(assessment)

            prompt += (
                "\n\nBusiness assessment instructions:\n"
                "1. Begin with a short summary of the client's business profile.\n"
                "2. Use only approved knowledge relevant to the same industry and business type.\n"
                "3. Assess the stated budget only where the approved context supports a comparison. "
                "Do not guess a budget benchmark.\n"
                "4. Summarize relevant setup, licensing, staffing, operational, market, and financial considerations found in the approved context.\n"
                "5. Use anonymized aggregate or generalized insights only. Never reveal business names, client identities, source file names, source IDs, or individual confidential figures.\n"
                "6. If there is not enough relevant knowledge for a conclusion, say that clearly.\n"
                "7. Finish with practical next steps and any important follow-up information still needed.\n"
                "8. Do not ask the client to repeat information already supplied in the assessment.\n"
                "9. Summarize the relevant knowledge into a clear advisory answer; never reproduce raw document text."
            )

        recent_prompt = _conversation_to_prompt(recent_conversation)
        recent_industry = _recent_business_industry(recent_conversation)

        if recent_prompt:
            prompt += "\n\nRecent conversation:\n" + recent_prompt

        if contextual_followup and followup_meta.get("active_topic"):
            active_topic = followup_meta.get("active_topic")
            family = followup_meta.get("family") or "unknown"
            metric = followup_meta.get("metric") or "general"
            exact_sources = followup_meta.get("exact_sources") or 0
            proxy_sources = followup_meta.get("proxy_sources") or 0

            prompt += (
                "\n\nACTIVE BUSINESS TOPIC LOCK:\n"
                f"Selected business/topic: {active_topic}\n"
                f"Business family: {family}\n"
                f"Current information type requested: {metric}\n"
                f"Exact-topic knowledge sources available: {exact_sources}\n"
                f"Similar-business proxy sources available: {proxy_sources}\n\n"
                "Rules for this follow-up:\n"
                "1. Keep the answer about the selected business/topic. Never silently switch "
                "to another business, feasibility study, or industry.\n"
                "2. Use [Evidence level: exact topic] first.\n"
                "3. If an exact figure is unavailable, you MAY use a number from "
                "[Evidence level: similar business] or [Evidence level: broader industry proxy] "
                "only as a clearly labelled proxy/benchmark.\n"
                "4. If using a proxy, explicitly say it comes from a similar business and is "
                "not an exact confirmed figure for the selected business.\n"
                "5. Never present a proxy as a confirmed salary, staffing requirement, cost, "
                "revenue, profit, or budget for the selected business.\n"
                "6. Borrow only the SAME TYPE of information requested. A salary question may "
                "borrow salary/payroll evidence, but never an unrelated project-cost number.\n"
                "7. Do not convert total payroll into per-person salary, or per-person salary into "
                "total payroll, unless the approved source clearly provides the required headcount "
                "and relationship. Preserve monthly/yearly and per-person/total units exactly.\n"
                "8. Similarity must be operationally sensible. Restaurant/cafe/bakery/takeaway "
                "may share food-service benchmarks. Hotel F&B can be used only for comparable "
                "food-and-beverage roles/costs, not whole-hotel costs. Food-processing data must "
                "not be treated as restaurant front-of-house data.\n"
                "9. For cap/light manufacturing, prefer cap/headwear/apparel/garment/textile/"
                "light-manufacturing evidence. Never borrow healthcare, nursing, hotel, or "
                "unrelated food-project figures.\n"
                "10. If neither exact nor sensible proxy evidence exists, say the requested "
                "information is not available in the approved knowledge. Do not guess.\n"
                "11. Confidence: High = exact-topic evidence; Medium = close similar-business "
                "evidence; Low = broader proxy evidence. Include the confidence when a numerical "
                "proxy is used."
            )

        if recent_industry:
            prompt += (
                f"\n\nCurrent business topic from the recent conversation: "
                f"{BUSINESS_INDUSTRY_LABELS.get(recent_industry, recent_industry)}."
            )

        prompt += (
            "\n\nConversation rule: Treat short follow-ups such as staffing, salary, "
            "expenses, equipment, rent, revenue, profit, cost breakdown, 'yes', 'continue', "
            "or 'what about this?' as questions about the most recently selected CUSTOMER "
            "business topic. Never let an unrelated assistant answer redefine that topic."
        )

        customer_prompt_message = (
            "Provide practical marketing strategy suggestions for the active business topic. "
            "Use relevant approved knowledge and keep the recommendations cost-conscious where possible."
            if marketing_choice == "advice"
            else message
        )

        prompt += f"\n\nCustomer message: {customer_prompt_message}\nAnswer:"

        hf = _build_huggingface_client(cfg)

        try:
            configured_timeout = _safe_int(cfg.get("timeout"), 30)
            generation_timeout = (
                max(configured_timeout, 60)
                if assessment
                else configured_timeout
            )

            answer = await hf.generate(
                prompt,
                temperature=cfg.get("temperature", 0.3),
                top_p=cfg.get("top_p", 0.9),
                max_tokens=cfg.get("max_tokens", 512),
                timeout=generation_timeout,
            )

            print(
                "HF_GENERATION_RESULT:",
                repr(answer)[:3000],
                flush=True,
            )

        except Exception as exc:
            print(
                "HF_GENERATION_EXCEPTION:",
                type(exc).__name__,
                str(exc),
                flush=True,
            )

            answer = (
                cfg.get("fallback_message")
                or "I could not connect to the AI service right now. Please try again or contact support."
            )

        if (
            not answer
            or "AI is not configured" in answer
            or "AI connection exception" in answer
            or "AI connection error" in answer
            or "Request timed out" in answer
            or "Connection failed" in answer
            or "HTTP client error" in answer
            or "no generated chat content" in answer.lower()
            or "No address associated with hostname" in answer
            or "Name or service not known" in answer
            or "Temporary failure in name resolution" in answer
        ):
            used_knowledge = False

            if assessment:
                relevant_cases = len(
                    {
                        row.get("source_id") or row.get("id")
                        for row in ctx["knowledge"]
                        if row.get("source_id") or row.get("id")
                    }
                )

                answer = "\n".join(
                    [
                        "Your business assessment has been received.",
                        "",
                        _business_assessment_profile(assessment),
                        "",
                        f"I found {relevant_cases} relevant anonymized knowledge source"
                        f"{'s' if relevant_cases != 1 else ''} for this business profile.",
                        "",
                        "I found relevant knowledge for your assessment, but the AI generation step did not complete successfully. I will not display raw or potentially unrelated source text. Please try again shortly. If the issue continues, check the Render log entry beginning with HF_GENERATION_RESULT or HF_GENERATION_EXCEPTION.",
                    ]
                )
            else:
                answer = (
                    cfg.get("fallback_message")
                    or "I could not process the relevant business information properly right now. Please try again shortly or contact Malriffaie Support."
                )

    # TEMPORARY TESTING ONLY:
    # Show which knowledge sources contributed to the AI/RAG answer.
    # Disable SHOW_RAG_SOURCES_TO_CLIENT before production.
    if used_knowledge and ctx.get("knowledge"):
        answer = _append_test_sources(
            answer,
            ctx.get("knowledge") or [],
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
        "products": [] if (
            assessment
            or business_idea_discovery
            or marketing_choice_offer
            or marketing_advice_mode
        ) else recommended,
        "sources": ctx["knowledge"] if used_knowledge else [],
    }
