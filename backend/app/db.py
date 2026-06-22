from supabase import create_client, Client
from .config import get_settings

_settings = get_settings()
supabase: Client = create_client(_settings.supabase_url, _settings.supabase_service_role_key)
