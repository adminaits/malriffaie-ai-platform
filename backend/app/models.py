from pydantic import BaseModel, EmailStr, Field
from typing import Any, Optional
from datetime import datetime

class ProductIn(BaseModel):
    name: str
    description: str = ""
    price: float | None = None
    currency: str = "BHD"
    image_url: str | None = None
    available: bool = True

class Product(ProductIn):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

class ServiceIn(BaseModel):
    name: str
    description: str = ""
    price: float | None = None
    currency: str = "BHD"
    available: bool = True

class LeadIn(BaseModel):
    name: str
    email: EmailStr
    product_id: str | None = None
    status: str = "new"
    paid: bool = False

class BookingIn(BaseModel):
    user_id: str | None = None
    service_id: str | None = None
    product_id: str | None = None
    datetime: str
    status: str = "pending"

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    visitor_id: str | None = None
    lang: str = "en"

class ChatResponse(BaseModel):
    answer: str
    products: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

class AiSettingsIn(BaseModel):
    hugging_face_token: str | None = None
    model_name: str | None = None
    custom_endpoint_url: str | None = None
    embedding_model: str | None = None
    custom_embedding_model_name: str | None = None
    embedding_endpoint_url: str | None = None
    system_prompt: str | None = None
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 512
    timeout: int = 30
    retry_count: int = 2
    rate_limit: int = 10
    fallback_message: str = "I do not have that information yet. I can arrange a human handoff for you."
    use_cases: list[str] = []
    optional_rule: str | None = None

class ChatSettingsIn(BaseModel):
    brand_title: str = "Malriffaie"
    brand_subtitle: str = "AI Concierge"
    hero_title: str = "How can we help you today?"
    show_tagline: bool = True
    input_placeholder: str = "Describe what you need..."
    empty_state_title: str = "Ask about products, services, or bookings"
    empty_state_message: str = "I can recommend the right product or help you book a consultation."
    show_chips: bool = True
    show_sources: bool = False
    sticky_input: bool = True
    auto_focus: bool = True
    show_sidebar: bool = True
    show_services_sidebar: bool = True
    show_products_sidebar: bool = True
    footer_disclaimer: str = "AI responses may need human confirmation for complex cases."
