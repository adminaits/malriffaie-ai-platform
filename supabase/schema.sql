create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;


create table if not exists admin_users (
  id uuid primary key default uuid_generate_v4(),
  email text unique not null,
  password_hash text not null,
  role text default 'admin',
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists users (
  id uuid primary key default uuid_generate_v4(),
  name text,
  email text unique not null,
  password_hash text not null,
  company_name text,
  phone text,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists services (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  description text default '',
  price numeric,
  currency text default 'BHD',
  available boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists products (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  description text default '',
  price numeric,
  currency text default 'BHD',
  image_url text,
  available boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists knowledge_base (
  id uuid primary key default uuid_generate_v4(),
  source_type text not null,
  source_id text,
  content text not null,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create table if not exists bookings (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete set null,
  service_id uuid references services(id) on delete set null,
  product_id uuid references products(id) on delete set null,
  datetime timestamptz not null,
  status text default 'pending',
  google_calendar_id text,
  created_at timestamptz default now()
);

create table if not exists payments (
  id uuid primary key default uuid_generate_v4(),
  booking_id uuid references bookings(id) on delete set null,
  amount numeric not null,
  currency text default 'BHD',
  method text not null,
  status text default 'pending',
  transaction_id text,
  created_at timestamptz default now()
);

create table if not exists leads (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) on delete set null,
  name text not null,
  email text not null,
  product_id uuid references products(id) on delete set null,
  status text default 'new',
  paid boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists chat_messages (
  id uuid primary key default uuid_generate_v4(),
  visitor_id text,
  message text not null,
  response text,
  products_shown jsonb default '[]'::jsonb,
  timestamp timestamptz default now(),
  ip_hash text
);

create table if not exists ai_settings (
  id uuid primary key default uuid_generate_v4(),
  replace_homepage_with_chat boolean default true,
  chat_greeting text default 'Hi, I am your support concierge. I can help with our products, services, FAQs, documents, and bookings. What would you like to know?',
  hugging_face_token text,
  model_name text default 'mistralai/Mistral-7B-Instruct-v0.3',
  custom_endpoint_url text,
  embedding_model text default 'BAAI/bge-m3',
  custom_embedding_model_name text,
  embedding_endpoint_url text,
  system_prompt text,
  temperature numeric default 0.3,
  top_p numeric default 0.9,
  max_tokens int default 512,
  timeout int default 30,
  retry_count int default 2,
  rate_limit int default 10,
  fallback_message text default 'I do not have that information yet. I can arrange a human handoff for you.',
  use_cases jsonb default '[]'::jsonb,
  optional_rule text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists chat_settings (
  id uuid primary key default uuid_generate_v4(),
  brand_title text default 'Malriffaie',
  brand_subtitle text default 'AI Concierge',
  hero_title text default 'How can we help you today?',
  show_tagline boolean default true,
  input_placeholder text default 'Describe what you need...',
  empty_state_title text default 'Ask about products, services, or bookings',
  empty_state_message text default 'I can recommend the right product or help you book a consultation.',
  show_chips boolean default true,
  show_sources boolean default false,
  sticky_input boolean default true,
  auto_focus boolean default true,
  show_sidebar boolean default true,
  show_services_sidebar boolean default true,
  show_products_sidebar boolean default true,
  footer_disclaimer text default 'AI responses may need human confirmation for complex cases.',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists google_drive_widgets (
  id uuid primary key default uuid_generate_v4(),
  api_key text,
  folder_id text,
  folder_url text,
  enabled boolean default false,
  sync_interval_minutes int default 1440,
  synced_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists booking_settings (
  id uuid primary key default uuid_generate_v4(),
  enabled boolean default true,
  manual_fallback_enabled boolean default true,
  google_calendar_enabled boolean default false,
  api_key text,
  calendar_id text,
  timezone text default 'Asia/Bahrain',
  default_duration int default 60,
  buffer_minutes int default 15,
  work_start time default '09:00',
  work_end time default '17:00',
  working_days jsonb default '["sun","mon","tue","wed","thu"]'::jsonb,
  service_product_map jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists payment_settings (
  id uuid primary key default uuid_generate_v4(),
  mode text default 'manual',
  tap_enabled boolean default false,
  manual_transfer_enabled boolean default true,
  pending_message text default 'Your order is pending review. Please complete Benefit transfer and we will confirm shortly.',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists email_settings (
  id uuid primary key default uuid_generate_v4(),
  admin_email text,
  confirmation_subject text default 'Booking confirmation',
  confirmation_body text default 'Thank you. Your booking has been received.',
  reminder_body text default 'Reminder: your booking is coming up soon.',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

insert into products (name, description, price, currency, available) values
('Feasibility Study', 'Business feasibility study package.', null, 'BHD', true),
('HR Manual — 3-000-MANUAL', 'HR manual template/package.', 300.000, 'BHD', true),
('Partnership Agreement', 'Professional partnership agreement service.', 800.000, 'BHD', true),
('Service Level Agreement', 'Service level agreement drafting package.', 160.000, 'BHD', true),
('Marketing Strategy', 'Marketing strategy planning package.', 350.000, 'BHD', true),
('DIY Marketing/Content Service', 'DIY marketing and content support service.', 500.000, 'BHD', true),
('Consultant Retainer Membership 2025', 'Consulting retainer membership.', 200.000, 'BHD', true),
('Online Consultation', 'Book an online consultation.', 50.000, 'BHD', true),
('The Owner’s Money Brief: The 3 Numbers That Matter', 'Owner-focused financial clarity brief.', 25.000, 'BHD', true),
('Consultation Subscriptions', 'Subscription consultation package.', 500.000, 'BHD', true)
on conflict do nothing;

insert into services (name, description, price, currency, available) values
('Online Consultation', 'One-to-one online consultation with booking capability.', 50.000, 'BHD', true)
on conflict do nothing;

insert into chat_settings default values;


-- Safe migration for existing projects
alter table ai_settings add column if not exists custom_embedding_model_name text;

-- Client portal safe migration for existing Supabase projects
alter table users add column if not exists name text;
alter table users add column if not exists company_name text;
alter table users add column if not exists phone text;
alter table users add column if not exists is_active boolean default true;
alter table users add column if not exists updated_at timestamptz default now();
