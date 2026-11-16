-- =====================================================================
-- database/schema.sql  |  Fashion Shop (Buyer, Seller, Admin)
-- Hợp đồng: mục 8 của PROJECT_CONTEXT.md. Không tự đổi tên bảng, tên cột.
--
-- CÁCH CHẠY: Supabase > SQL Editor > New query > dán toàn bộ file > Run.
-- Có thể chạy lại nhiều lần (create ... if not exists).
-- Mật khẩu nằm trong auth.users của Supabase, KHÔNG có cột mật khẩu ở đây.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------- 1. Bảng ----------

create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique not null,
  email text not null,
  full_name text, phone text, address text, avatar_url text,
  role text not null check (role in ('buyer','seller','admin')),
  status text not null default 'active' check (status in ('active','banned')),
  must_change_password boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists body_profiles (
  user_id uuid primary key references profiles(id) on delete cascade,
  height_cm int, weight_kg int,
  model_gender text not null default 'female' check (model_gender in ('female','male')),
  body_shape text check (body_shape in ('pear','hourglass','rectangle','apple','inverted_triangle')),
  style_tags text[] not null default '{}',
  budget_max int,
  wishes text
);
alter table body_profiles
  add column if not exists model_gender text not null default 'female'
  check (model_gender in ('female','male'));

create table if not exists shops (
  id bigint generated always as identity primary key,
  owner_id uuid unique not null references profiles(id) on delete cascade,
  name text not null, description text, address text,
  lat double precision, lng double precision,
  prep_minutes int not null default 60,
  moderation_status text not null default 'approved'
    check (moderation_status in ('approved','pending','blocked','rejected')),
  created_at timestamptz not null default now()
);

create table if not exists products (
  id bigint generated always as identity primary key,
  shop_id bigint not null references shops(id) on delete cascade,
  name text not null, description text,
  price int not null check (price >= 0),
  category text not null check (category in ('ao','quan','vay-dam','phu-kien')),
  target_gender text not null default 'unisex',
  tags text[] not null default '{}',
  suits_shapes text[] not null default '{}',
  tryon_layer_url text, tryon_model_url text,
  moderation_status text not null default 'pending'
    check (moderation_status in ('approved','pending','blocked','rejected')),
  risk_score int not null default 0,
  risk_reasons jsonb not null default '[]',
  is_active boolean not null default true,
  sold_count int not null default 0,
  created_at timestamptz not null default now()
);
alter table products add column if not exists target_gender text;
update products
set target_gender = case
  when category = 'vay-dam' or tags && array['nu-tinh', 'nu', 'female', 'women', 'woman']::text[]
    then 'female'
  when tags && array['nam', 'male', 'men', 'man']::text[]
    then 'male'
  else 'unisex'
end
where target_gender is null;
alter table products alter column target_gender set default 'unisex';
alter table products alter column target_gender set not null;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'products_target_gender_check'
      and conrelid = 'products'::regclass
  ) then
    alter table products
      add constraint products_target_gender_check
      check (target_gender in ('female', 'male', 'unisex'));
  end if;
end $$;

create table if not exists product_variants (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  size text not null, color text not null,
  stock int not null default 0 check (stock >= 0)
);

create table if not exists product_images (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  url text not null, is_main boolean not null default false, position int not null default 0
);

create table if not exists cart_items (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  variant_id bigint not null references product_variants(id) on delete cascade,
  quantity int not null check (quantity > 0),
  unique (user_id, variant_id)
);

create table if not exists orders (
  id bigint generated always as identity primary key,
  buyer_id uuid not null references profiles(id),
  shop_id bigint not null references shops(id),
  total int not null,
  status text not null default 'pending'
    check (status in ('pending','processing','shipping','completed','cancelled')),
  payment_method text not null check (payment_method in ('cod','mock_card','bank_transfer')),
  payment_status text not null default 'unpaid' check (payment_status in ('unpaid','reported','paid')),
  receiver_name text not null, phone text not null, address text not null,
  lat double precision, lng double precision,
  eta_minutes int,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table orders drop constraint if exists orders_payment_method_check;
alter table orders add constraint orders_payment_method_check
  check (payment_method in ('cod','mock_card','bank_transfer'));
alter table orders drop constraint if exists orders_payment_status_check;
alter table orders add constraint orders_payment_status_check
  check (payment_status in ('unpaid','reported','paid'));

create table if not exists order_items (
  id bigint generated always as identity primary key,
  order_id bigint not null references orders(id) on delete cascade,
  variant_id bigint references product_variants(id) on delete set null,
  product_id bigint references products(id) on delete set null,
  product_name text not null, size text, color text,
  quantity int not null, price int not null
);

create table if not exists reviews (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  rating int not null check (rating between 1 and 5),
  comment text,
  created_at timestamptz not null default now()
);

create table if not exists messages (
  id bigint generated always as identity primary key,
  sender_id uuid not null references profiles(id) on delete cascade,
  receiver_id uuid not null references profiles(id) on delete cascade,
  content text not null,
  product_id bigint references products(id) on delete set null,
  is_read boolean not null default false,
  created_at timestamptz not null default now()
);

alter table messages add column if not exists product_id bigint references products(id) on delete set null;

create table if not exists tickets (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  parent_id bigint references tickets(id) on delete cascade,
  subject text, content text not null,
  status text not null default 'open' check (status in ('open','closed')),
  created_at timestamptz not null default now()
);

create table if not exists moderation_queue (
  id bigint generated always as identity primary key,
  target_type text not null check (target_type in ('shop','product')),
  target_id bigint not null,
  risk_score int not null,
  reasons jsonb not null default '[]',
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  reject_reason text,
  reviewed_by uuid references profiles(id),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);

create table if not exists ai_block_logs (
  id bigint generated always as identity primary key,
  target_type text not null check (target_type in ('shop','product','account')),
  target_id text not null,
  owner_id uuid references profiles(id) on delete set null,
  risk_score int,
  reasons jsonb not null default '[]',
  action text not null check (action in ('pending_review','blocked','warning','ban')),
  restored boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists analytics_events (
  id bigint generated always as identity primary key,
  shop_id bigint not null references shops(id) on delete cascade,
  product_id bigint references products(id) on delete set null,
  user_id uuid references profiles(id) on delete set null,
  event_type text not null check (event_type in ('view','add_to_cart','purchase')),
  created_at timestamptz not null default now()
);

-- ---------- 2. Index ----------

create index if not exists idx_products_shop on products(shop_id);
create index if not exists idx_products_moderation on products(moderation_status, is_active);
create index if not exists idx_orders_buyer on orders(buyer_id);
create index if not exists idx_orders_shop_status on orders(shop_id, status);
create index if not exists idx_messages_pair on messages(sender_id, receiver_id, created_at);
create index if not exists idx_events_shop_time on analytics_events(shop_id, created_at);

-- ---------- 3. Bảo mật ----------
-- Bật RLS và KHÔNG tạo policy: khóa anon chỉ gọi được Auth và Storage,
-- không đọc bảng trực tiếp. Backend dùng service role key nên bỏ qua RLS.

alter table profiles          enable row level security;
alter table body_profiles     enable row level security;
alter table shops             enable row level security;
alter table products          enable row level security;
alter table product_variants  enable row level security;
alter table product_images    enable row level security;
alter table cart_items        enable row level security;
alter table orders            enable row level security;
alter table order_items       enable row level security;
alter table reviews           enable row level security;
alter table messages          enable row level security;
alter table tickets           enable row level security;
alter table moderation_queue  enable row level security;
alter table ai_block_logs     enable row level security;
alter table analytics_events  enable row level security;

-- ---------- 4. Storage (ảnh sản phẩm, ảnh đại diện) ----------

insert into storage.buckets (id, name, public)
values ('product-images', 'product-images', true),
       ('avatars', 'avatars', true)
on conflict (id) do nothing;

drop policy if exists "public read shop images" on storage.objects;
create policy "public read shop images" on storage.objects
  for select using (bucket_id in ('product-images', 'avatars'));

drop policy if exists "logged in upload shop images" on storage.objects;
create policy "logged in upload shop images" on storage.objects
  for insert to authenticated
  with check (bucket_id in ('product-images', 'avatars'));