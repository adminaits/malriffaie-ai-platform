from app.db import supabase
from app.services.huggingface import HuggingFaceClient
from app.config import get_settings
from datetime import date
import re
from statistics import mean, median

settings = get_settings()

PRIVATE_KNOWLEDGE_MESSAGE = """
## Thank You for Your Interest

We appreciate you taking the time to learn more about **Mal Riffaie**. The information you’ve reviewed is just the beginning of how we can support your goals.

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

            score = _score_knowledge_row(item, query_text)

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
    industry = assessment.get("industry")
    business_type = assessment.get("business_type")

    values = [
        industry,
        industry,
        business_type,
        business_type,
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



def _wants_business_start_guidance(message: str) -> bool:
    low = (message or "").lower().strip()
    industry = _detect_industry(message)

    if not industry:
        return False

    start_terms = [
        "start a business", "start business", "starting a business", "start the business",
        "starting the business", "set up a business", "setup a business", "set up the business",
        "setup the business", "open a business", "open business", "open the business",
        "business idea", "business opportunity", "want to start", "planning to start",
        "plan to start", "thinking to start", "thinking about starting", "know about",
        "know more about", "learn about", "interested in starting", "interested to start",
        "how to start", "what do i need to start", "what is needed to start",
        "new venture", "new business",
    ]

    return any(term in low for term in start_terms)


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
    for row in reversed(rows):
        for value in [row.get("message"), row.get("response")]:
            industry = _detect_industry(str(value or ""))
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

    # Structured business assessment is accepted only for logged-in clients/admins.
    assessment = (
        _parse_business_assessment(message)
        if client_logged_in
        else None
    )

    retrieval_query = (
        _business_assessment_search_query(assessment)
        if assessment
        else message
    )

    # Public users get public knowledge only.
    # Logged-in clients/admins get public + private/internal wiki knowledge.
    ctx = retrieve_context(
        retrieval_query,
        include_private=client_logged_in,
    )

    recent_conversation = (
        _load_recent_conversation(visitor_id)
        if client_logged_in
        else []
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
        and _wants_business_start_guidance(message)
    ):
        # The logged-in client dashboard now uses a structured Business Assessment
        # form. Do not send the old multi-question intake list from the backend.
        # This response is also a safe fallback for older frontend builds.
        answer = (
            "To give you accurate business guidance, please complete the "
            "Business Assessment form in your Client Dashboard. "
            "Once submitted, I will use your answers together with relevant "
            "anonymized knowledge from similar projects."
        )
        recommended = []
        used_knowledge = False

    # 1. Service-list/service-description questions.
    # This must be checked before product recommendation logic.
    if answer is None and _wants_service_list(message):
        answer = _service_list_answer(ctx["services"])
        recommended = []

    # 2. Product-list questions.
    elif answer is None and _wants_product_list(message):
        answer = _product_list_answer(ctx["products"])
        # Return every available product so the frontend can render the full list.
        recommended = ctx["products"]

    # 3. Booking/consultation questions.
    elif answer is None and _wants_booking(message):
        answer = _booking_answer(ctx["services"])
        recommended = []

    elif answer is None:
        service = _matched_service(message, ctx["services"])
        product = _matched_product(message, ctx["products"])

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
        elif _wants_recommendation(message):
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
                "8. Do not ask the client to repeat information already supplied in the structured assessment.\n"
                "9. If relevant knowledge exists, summarize it into a useful advisory response rather than reproducing raw document text."
            )

        recent_prompt = _conversation_to_prompt(recent_conversation)
        recent_industry = _recent_business_industry(recent_conversation)

        if recent_prompt:
            prompt += "\n\nRecent conversation:\n" + recent_prompt

        if recent_industry:
            prompt += (
                f"\n\nCurrent business topic from the recent conversation: "
                f"{BUSINESS_INDUSTRY_LABELS.get(recent_industry, recent_industry)}."
            )

        prompt += (
            "\n\nConversation rule: If the customer's current message is a short follow-up "
            "such as 'yes', 'yes please', 'continue', 'okay', or similar, interpret it using "
            "the recent conversation instead of searching unrelated knowledge."
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
        except Exception:
            answer = (
                cfg.get("fallback_message")
                or "I could not connect to the AI service right now. Please try again or contact support."
            )

        if (
            not answer
            or "AI is not configured" in answer
            or "AI connection exception" in answer
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
                        "The AI summarization service is temporarily unavailable, so I will not display raw or potentially unrelated source text. Please try the assessment again shortly or contact Malriffaie Support for a detailed review.",
                    ]
                )
            else:
                answer = (
                    cfg.get("fallback_message")
                    or "I could not process the relevant business information properly right now. Please try again shortly or contact Malriffaie Support."
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
        "sources": ctx["knowledge"] if used_knowledge else [],
    }
