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
