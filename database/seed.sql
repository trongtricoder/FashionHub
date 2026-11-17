-- =====================================================================
-- database/seed.sql  |  Dữ liệu demo cho Fashion Shop
--
-- CHẠY SAU schema.sql, chạy TOÀN BỘ file một lần trong Supabase SQL Editor.
-- CẢNH BÁO: file này XÓA SẠCH dữ liệu các bảng của dự án rồi tạo lại,
-- để id sản phẩm 1..21 khớp với mảng products trong Buyer.html cũ.
-- Chỉ chạy khi database còn trống hoặc chỉ có dữ liệu demo.
--
-- Tất cả tài khoản demo dùng mật khẩu: Demo@12345
--   admin@shop.example
--   buyer1@shop.example  ...  buyer5@shop.example
--   seller1@shop.example ...  seller19@shop.example
-- seller1 = Shop Basic Wear, seller2 = Sweetie Style: hai shop chính,
-- có nhiều đơn và lượt xem nhất để biểu đồ dashboard có ý nghĩa.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;
select setseed(0.42);  -- cố định số ngẫu nhiên để lần nào chạy cũng ra dữ liệu giống nhau

-- ---------- 0. Dọn dữ liệu cũ ----------

truncate table analytics_events, ai_block_logs, moderation_queue, tickets, messages, reviews,
  order_items, orders, cart_items, product_images, product_variants, products, shops,
  body_profiles, profiles restart identity cascade;
delete from auth.users where email like '%@shop.example';

-- ---------- 1. Tài khoản (Supabase Auth + profiles) ----------

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change_token_new, email_change,
  email_change_token_current, phone_change, phone_change_token, reauthentication_token
)
select '00000000-0000-0000-0000-000000000000',
       ('00000000-0000-4000-8000-' || lpad(u.n::text, 12, '0'))::uuid,
       'authenticated', 'authenticated', u.email,
       extensions.crypt('Demo@12345', extensions.gen_salt('bf')), now(),
       '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(),
       '', '', '', '', '', '', '', ''
from (
  select 1 as n, 'admin@shop.example' as email
  union all select 10 + g, 'buyer' || g || '@shop.example' from generate_series(1, 5) g
  union all select 100 + g, 'seller' || g || '@shop.example' from generate_series(1, 19) g
) u;

insert into auth.identities (id, user_id, provider_id, identity_data, provider,
                             last_sign_in_at, created_at, updated_at)
select gen_random_uuid(), id, id::text,
       jsonb_build_object('sub', id::text, 'email', email, 'email_verified', true),
       'email', now(), now(), now()
from auth.users
where email like '%@shop.example';

insert into profiles (id, username, email, full_name, phone, address, role)
select u.id, split_part(u.email, '@', 1), u.email,
       case when u.email like 'admin%' then 'Quản trị viên'
            when u.email like 'buyer%' then
              (array['Nguyễn Thị Lan','Trần Minh Khoa','Lê Thu Hà','Phạm Quốc Bảo','Võ Ngọc Anh'])[u.n]
            else 'Chủ shop ' || u.n end,
       '0900' || lpad(row_number() over (order by u.email)::text, 6, '0'),
       case when u.email like 'buyer%' then
              (array['12 Nguyễn Huệ, Quận 1, TP.HCM','45 Lê Văn Sỹ, Quận 3, TP.HCM',
                     '78 Cộng Hòa, Tân Bình, TP.HCM','23 Phan Xích Long, Phú Nhuận, TP.HCM',
                     '9 Võ Văn Ngân, Thủ Đức, TP.HCM'])[u.n]
       end,
       case when u.email like 'admin%' then 'admin'
            when u.email like 'buyer%' then 'buyer'
            else 'seller' end
from (
  select au.id, au.email,
         nullif(regexp_replace(au.email, '\D', '', 'g'), '')::int as n
  from auth.users au
  where au.email like '%@shop.example'
) u;

-- ---------- 2. Shop (19 shop lấy từ tên cửa hàng trong Buyer.html cũ) ----------
-- Shop số 1 dùng đúng tọa độ trong Seller/orders.html cũ (10.762622, 106.660172).

insert into shops (owner_id, name, description, address, lat, lng, prep_minutes)
select p.id, s.name,
       'Cửa hàng thời trang ' || s.name || ' chuyên các mẫu dễ mặc, giá hợp lý.',
       (10 + s.n * 7) || ' Đường Mẫu, TP. Hồ Chí Minh',
       case when s.n = 1 then 10.762622
            else (array[10.7769,10.7843,10.7540,10.7726,10.7992,10.8100,10.8010,10.8386,10.7340,10.8494])[1 + s.n % 10]
                 + s.n * 0.0003 end,
       case when s.n = 1 then 106.660172
            else (array[106.7009,106.6844,106.6670,106.6679,106.6800,106.7090,106.6527,106.6652,106.7220,106.7537])[1 + s.n % 10]
                 + s.n * 0.0003 end,
       30 + (s.n % 4) * 15
from (
  select t.name, t.n::int as n
  from unnest(array['Shop Basic Wear','Sweetie Style','Streetwear Club','Office Elegance',
                    'Luxury Fashion','Winter Vibe','Denim Store','Sporty Life','Summer Vibe',
                    'Lady Dress','Men Classic','Urban Jacket','Soft Knit','Sneaker Head',
                    'Eco Bag','Travel Accessories','Footwear Store','Cool Glasses','Watch Time'])
       with ordinality as t(name, n)
) s
join profiles p on p.email = 'seller' || s.n || '@shop.example';

-- ---------- 3. Sản phẩm ----------
-- 1..21: giữ nguyên tên, giá, ảnh của mảng products trong Buyer.html cũ.
-- 22..30: sản phẩm thêm cho hai shop chính (ảnh placeholder).
-- 31..34: sản phẩm cố tình vi phạm để demo AI Detector và hàng đợi duyệt.

create temp table seed_products (
  ord int, shop text, name text, description text, price int, category text,
  tags text, shapes text, img text, status text, risk int, reasons text
);

insert into seed_products values
 (1,'Shop Basic Wear','Áo thun basic','Áo thun cotton 100% mềm mịn, thấm hút tốt, dễ phối đồ mỗi ngày.',150000,'ao','{basic,toi-gian}','{rectangle,pear,hourglass,apple,inverted_triangle}','https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=600','approved',0,'[]'),
 (2,'Streetwear Club','Áo thun oversize','Áo thun form rộng phong cách đường phố, chất vải dày dặn đứng form.',190000,'ao','{streetwear,nang-dong}','{rectangle,apple,pear}','https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?w=600','approved',0,'[]'),
 (3,'Office Elegance','Áo sơ mi','Áo sơ mi công sở chất liệu thoáng mát, ít nhăn, lịch sự và gọn gàng.',250000,'ao','{cong-so,toi-gian}','{rectangle,hourglass,inverted_triangle}','https://images.unsplash.com/photo-1598033129183-c4f50c736f10?w=600','approved',0,'[]'),
 (4,'Luxury Fashion','Áo limited','Mẫu áo phiên bản giới hạn, chất liệu cao cấp, số lượng có hạn.',450000,'ao','{cao-cap,streetwear}','{hourglass,rectangle}','https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?w=600','approved',0,'[]'),
 (5,'Winter Vibe','Áo hoodie','Áo hoodie nỉ bông ấm áp, mũ rộng, túi kangaroo tiện lợi.',320000,'ao','{mua-dong,streetwear,nang-dong}','{rectangle,apple,pear,inverted_triangle}','https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=600','approved',0,'[]'),
 (6,'Denim Store','Quần jeans','Quần jeans co giãn nhẹ, form đứng, bền màu sau nhiều lần giặt.',380000,'quan','{basic,nang-dong}','{rectangle,hourglass,pear}','https://images.unsplash.com/photo-1541099649105-f69ad21f3246?w=600','approved',0,'[]'),
 (7,'Sporty Life','Quần thể thao','Quần thể thao vải thun lạnh, nhẹ và thoải mái khi vận động.',210000,'quan','{the-thao,nang-dong}','{rectangle,apple,inverted_triangle}','https://images.unsplash.com/photo-1517466787929-bc90951d0974?w=600','approved',0,'[]'),
 (8,'Sweetie Style','Quần ống rộng','Quần ống rộng lưng cao tôn dáng, chất vải rủ nhẹ nhàng, nữ tính.',290000,'quan','{nu-tinh,toi-gian}','{pear,apple,hourglass}','https://images.unsplash.com/photo-1509551388413-e18d0ac5d495?w=600','approved',0,'[]'),
 (9,'Summer Vibe','Quần short','Quần short mát mẻ cho mùa hè, vải mỏng nhẹ, thoáng khí.',180000,'quan','{mua-he,nang-dong}','{rectangle,hourglass,inverted_triangle}','https://images.unsplash.com/photo-1591195853828-11db59a44f6b?w=600','approved',0,'[]'),
 (10,'Sweetie Style','Váy chữ A','Váy chữ A xòe nhẹ, tôn eo, phù hợp đi làm và đi chơi.',270000,'vay-dam','{nu-tinh,toi-gian}','{pear,hourglass,apple}','https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?w=600','approved',0,'[]'),
 (11,'Lady Dress','Váy dài','Váy dài thướt tha, chất liệu mềm rủ, phù hợp dạo phố và dự tiệc.',350000,'vay-dam','{nu-tinh,vintage}','{pear,hourglass,rectangle}','https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?w=600','approved',0,'[]'),
 (12,'Men Classic','Quần kaki','Quần kaki form slim, chất vải dày vừa, mặc đi làm hay đi chơi đều đẹp.',310000,'quan','{cong-so,basic}','{rectangle,apple,inverted_triangle}','https://images.unsplash.com/photo-1473966968600-fa801b869a1a?w=600','approved',0,'[]'),
 (13,'Urban Jacket','Áo khoác','Áo khoác gió chống nước nhẹ, cản gió tốt, kiểu dáng đô thị.',420000,'ao','{streetwear,mua-dong}','{rectangle,inverted_triangle,apple}','https://images.unsplash.com/photo-1551028719-00167b16eac5?w=600','approved',0,'[]'),
 (14,'Soft Knit','Áo cardigan','Áo cardigan len mềm, giữ ấm nhẹ, dễ phối cùng áo thun hoặc đầm.',280000,'ao','{nu-tinh,vintage,mua-dong}','{pear,hourglass,rectangle}','https://images.unsplash.com/photo-1434389677669-e08b4cac3105?w=600','approved',0,'[]'),
 (15,'Sneaker Head','Giày thể thao','Giày thể thao đế êm, thoáng khí, phù hợp đi học đi làm hằng ngày.',550000,'phu-kien','{the-thao,streetwear}','{}','https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600','approved',0,'[]'),
 (16,'Office Elegance','Quần tây','Quần tây ống đứng, vải không nhăn, phù hợp môi trường công sở.',340000,'quan','{cong-so,toi-gian}','{rectangle,hourglass,pear}','https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=600','approved',0,'[]'),
 (17,'Eco Bag','Túi tote','Túi tote vải canvas bền chắc, đựng được laptop và đồ dùng hằng ngày.',120000,'phu-kien','{basic,toi-gian}','{}','https://images.unsplash.com/photo-1544816155-12df9643f363?w=600','approved',0,'[]'),
 (18,'Travel Accessories','Balo','Balo chống nước, nhiều ngăn tiện dụng, phù hợp đi học và đi du lịch.',390000,'phu-kien','{nang-dong,the-thao}','{}','https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=600','approved',0,'[]'),
 (19,'Footwear Store','Giày dép','Giày dép thoải mái, đế chống trượt, dùng được nhiều dịp khác nhau.',230000,'phu-kien','{basic}','{}','https://images.unsplash.com/photo-1603808033192-082d6919d3e1?w=600','approved',0,'[]'),
 (20,'Cool Glasses','Mắt kính','Mắt kính thời trang chống tia UV, gọng nhẹ, nhiều kiểu dáng.',160000,'phu-kien','{streetwear,vintage}','{}','https://images.unsplash.com/photo-1511499767150-a48a237f0083?w=600','approved',0,'[]'),
 (21,'Watch Time','Đồng hồ','Đồng hồ dây da mặt tròn, phong cách tối giản, chống nước sinh hoạt.',890000,'phu-kien','{cao-cap,toi-gian}','{}','https://images.unsplash.com/photo-1524805444758-089113d48a6d?w=600','approved',0,'[]'),
 (22,'Shop Basic Wear','Áo polo trơn','Áo polo trơn vải cá sấu thoáng mát, cổ bo chắc chắn, lịch sự mà trẻ trung.',210000,'ao','{basic,cong-so}','{rectangle,inverted_triangle,apple}','https://picsum.photos/seed/p22a/600/800','approved',0,'[]'),
 (23,'Shop Basic Wear','Áo tank top','Áo tank top ba lỗ cotton co giãn, mặc trong hoặc mặc ngoài đều đẹp.',120000,'ao','{basic,the-thao,mua-he}','{rectangle,hourglass,inverted_triangle}','https://picsum.photos/seed/p23a/600/800','approved',0,'[]'),
 (24,'Shop Basic Wear','Áo thun tay lỡ','Áo thun tay lỡ form rộng vừa phải, chất vải mềm, không bai xù.',180000,'ao','{streetwear,basic,nang-dong}','{rectangle,apple,pear}','https://picsum.photos/seed/p24a/600/800','approved',0,'[]'),
 (25,'Shop Basic Wear','Quần jogger','Quần jogger bo gấu, vải nỉ mỏng, thoải mái cho cả đi chơi và tập luyện.',260000,'quan','{the-thao,streetwear}','{rectangle,inverted_triangle,apple}','https://picsum.photos/seed/p25a/600/800','approved',0,'[]'),
 (26,'Shop Basic Wear','Áo len mỏng','Áo len mỏng dệt kim, giữ ấm nhẹ, hợp những ngày se lạnh.',330000,'ao','{mua-dong,toi-gian,vintage}','{pear,hourglass,rectangle}','https://picsum.photos/seed/p26a/600/800','approved',0,'[]'),
 (27,'Sweetie Style','Váy xòe','Váy xòe nhẹ nhàng, chất voan mềm, họa tiết hoa nhí đáng yêu.',320000,'vay-dam','{nu-tinh,vintage}','{pear,hourglass,apple}','https://picsum.photos/seed/p27a/600/800','approved',0,'[]'),
 (28,'Sweetie Style','Đầm body','Đầm body ôm dáng, vải thun gân co giãn, tôn đường cong tự nhiên.',360000,'vay-dam','{nu-tinh,cao-cap}','{hourglass,rectangle}','https://picsum.photos/seed/p28a/600/800','approved',0,'[]'),
 (29,'Sweetie Style','Chân váy jean','Chân váy jean lưng cao, form chữ A, dễ phối với áo thun và sơ mi.',240000,'vay-dam','{nang-dong,basic}','{pear,hourglass,rectangle}','https://picsum.photos/seed/p29a/600/800','approved',0,'[]'),
 (30,'Sweetie Style','Quần culottes','Quần culottes ống suông lửng, vải đứng form, phù hợp đi làm.',270000,'quan','{cong-so,nu-tinh,toi-gian}','{pear,apple,hourglass}','https://picsum.photos/seed/p30a/600/800','approved',0,'[]'),
 (31,'Luxury Fashion','Áo Gucci replica like auth','Hàng nhái cao cấp giá rẻ, liên hệ zalo 0901234567 để đặt.',99000,'ao','{}','{}','https://picsum.photos/seed/p31a/600/800','blocked',95,
   '[{"rule":"banned_keyword","points":70,"detail":"Chứa từ khóa cấm: replica, like auth, hàng nhái"},{"rule":"external_contact","points":25,"detail":"Mô tả có số điện thoại và Zalo"}]'),
 (32,'Luxury Fashion','Đồng hồ Rolex fake','Fake 1:1',5000,'phu-kien','{}','{}',null,'blocked',95,
   '[{"rule":"banned_keyword","points":40,"detail":"Chứa từ khóa cấm: fake"},{"rule":"price_anomaly","points":25,"detail":"Giá 5.000đ thấp bất thường"},{"rule":"no_image","points":20,"detail":"Sản phẩm không có ảnh"},{"rule":"short_description","points":10,"detail":"Mô tả ngắn hơn 20 ký tự"}]'),
 (33,'Sweetie Style','ÁO THUN SIÊU RẺ SIÊU RẺ SIÊU RẺ','Áo thun cotton rẻ nhất thị trường!!!!!!',8000,'ao','{}','{}',null,'pending',55,
   '[{"rule":"spam_text","points":10,"detail":"Tên viết hoa toàn bộ và ký tự lặp"},{"rule":"price_anomaly","points":25,"detail":"Giá 8.000đ thấp bất thường"},{"rule":"no_image","points":20,"detail":"Sản phẩm không có ảnh"}]'),
 (34,'Summer Vibe','Váy dài','Váy đẹp giá tốt, xem thêm tại https://bit.ly/vay-dep',280000,'vay-dam','{}','{}','https://picsum.photos/seed/p34a/600/800','pending',55,
   '[{"rule":"external_contact","points":25,"detail":"Mô tả có đường link ngoài"},{"rule":"duplicate","points":30,"detail":"Trùng tên với sản phẩm của shop khác"}]');

-- Chèn kèm id cố định (= ord) để id 1..21 khớp Buyer.html, rồi chỉnh lại sequence.
insert into products (id, shop_id, name, description, price, category, tags, suits_shapes,
                      moderation_status, risk_score, risk_reasons)
overriding system value
select sp.ord, s.id, sp.name, sp.description, sp.price, sp.category,
       sp.tags::text[], sp.shapes::text[], sp.status, sp.risk, sp.reasons::jsonb
from seed_products sp
join shops s on s.name = sp.shop
order by sp.ord;

select setval(pg_get_serial_sequence('products', 'id'), (select max(id) from products));

update products
set target_gender = case
  when category = 'vay-dam' or tags && array['nu-tinh']::text[] then 'female'
  when shop_id = (select id from shops where name = 'Men Classic') then 'male'
  else 'unisex'
end;

-- Ảnh: ảnh chính + 2 ảnh placeholder (sản phẩm vi phạm chỉ có ảnh chính nếu có)
insert into product_images (product_id, url, is_main, position)
select sp.ord, x.url, x.is_main, x.pos
from seed_products sp
cross join lateral (values
  (sp.img, true, 0),
  ('https://picsum.photos/seed/p' || sp.ord || 'b/600/800', false, 1),
  ('https://picsum.photos/seed/p' || sp.ord || 'c/600/800', false, 2)
) as x(url, is_main, pos)
where sp.img is not null and (x.pos = 0 or sp.ord <= 30);

-- Biến thể: áo, quần, váy có 4 đến 6 biến thể (size S..XL, 1 hoặc 2 màu); phụ kiện 3 biến thể.
-- Khoảng 10% biến thể sắp hết hàng (stock 0 đến 5), 10% tồn nhiều.
insert into product_variants (product_id, size, color, stock)
select t.id, t.size, t.color,
       case when t.r < 0.10 then floor(t.r * 60)::int
            when t.r < 0.20 then 20 + floor(t.r * 100)::int
            else 8 + floor(t.r * 25)::int end
from (
  select p.id, s.size, c.color, random() as r
  from products p
  cross join (values ('S', 1), ('M', 2), ('L', 3), ('XL', 4)) s(size, rk)
  cross join (values (1), (2)) c0(ck)
  cross join lateral (
    select case c0.ck
             when 1 then (array['Trắng','Đen','Hồng','Xanh','Be'])[(1 + p.id % 5)::int]
             else        (array['Đen','Hồng','Xanh','Be','Trắng'])[(1 + p.id % 5)::int]
           end as color
  ) c
  where p.category <> 'phu-kien'
    and (c0.ck = 1 or (p.id % 3 = 0 and s.rk <= 2))
  union all
  select p.id, 'Free'::text, c.color, random()
  from products p
  cross join (values ('Đen'), ('Trắng'), ('Nâu')) c(color)
  where p.category = 'phu-kien'
) t;

-- ---------- 4. Đơn hàng ----------
-- n_orders: số đơn tạo ra (spec ghi khoảng 50; để 80 cho biểu đồ doanh thu đỡ thưa).
-- 12 đơn đầu là đơn mới (chờ xác nhận, đang xử lý, đang giao) để demo luồng Seller.
-- Các đơn còn lại rải trong 90 ngày, nghiêng về gần đây và cuối tuần.

do $$
declare
  n_orders constant int := 80;
  buyers uuid[];
  i int; d int; dow int; k int;
  v_shop bigint; v_buyer uuid; v_order bigint;
  v_total int; v_eta int; v_prep int;
  st text; pm text; r double precision;
  slat double precision; slng double precision; olat double precision; olng double precision;
  ts timestamp; created timestamptz;
  rname text; rphone text; raddr text;
begin
  perform setseed(0.42);
  select array_agg(id order by email) into buyers from profiles where role = 'buyer';

  for i in 1..n_orders loop
    -- chọn shop: 55% Shop Basic Wear, 30% Sweetie Style, 15% shop ngẫu nhiên khác
    r := random();
    if r < 0.55 then
      select id into v_shop from shops where name = 'Shop Basic Wear';
    elsif r < 0.85 then
      select id into v_shop from shops where name = 'Sweetie Style';
    else
      select s.id into v_shop from shops s
      where exists (select 1 from products p where p.shop_id = s.id and p.moderation_status = 'approved')
      order by random() limit 1;
    end if;

    -- chọn ngày và trạng thái
    if i <= 12 then
      d := (i - 1) % 3;
      st := (array['pending','processing','shipping'])[1 + (i - 1) % 3];
    else
      loop
        d := floor(89 * power(random(), 1.3))::int;
        dow := extract(dow from (current_date - d))::int;
        exit when dow in (0, 6) or random() < 0.5;  -- cuối tuần dễ được giữ lại hơn
      end loop;
      if d <= 2 then
        st := (array['pending','processing','shipping','completed'])[1 + floor(random() * 4)::int];
      elsif random() < 0.88 then
        st := 'completed';
      else
        st := 'cancelled';
      end if;
    end if;

    pm := case when random() < 0.6 then 'cod' else 'mock_card' end;
    v_buyer := buyers[1 + floor(random() * array_length(buyers, 1))::int];
    select full_name, phone, address into rname, rphone, raddr from profiles where id = v_buyer;
    select lat, lng, prep_minutes into slat, slng, v_prep from shops where id = v_shop;

    -- nơi giao ngẫu nhiên trong nội thành TP.HCM, ETA theo công thức mục 10.4
    olat := 10.74 + random() * 0.10;
    olng := 106.64 + random() * 0.12;
    v_eta := round(v_prep + (111.0 * sqrt(power(olat - slat, 2)
                  + power((olng - slng) * cos(radians(slat)), 2)) * 1.3) / 25 * 60)::int;

    ts := (current_date - d)::timestamp
          + make_interval(hours => 8 + floor(random() * 14)::int, mins => floor(random() * 60)::int);
    created := least(ts at time zone 'Asia/Ho_Chi_Minh', now() - interval '5 minutes');

    insert into orders (buyer_id, shop_id, total, status, payment_method, payment_status,
                        receiver_name, phone, address, lat, lng, eta_minutes, created_at, updated_at)
    values (v_buyer, v_shop, 0, st, pm,
            case when st = 'completed' then 'paid'
                 when pm = 'mock_card' and st <> 'cancelled' then 'paid'
                 else 'unpaid' end,
            rname, rphone, coalesce(raddr, 'TP. Hồ Chí Minh'), olat, olng, v_eta, created,
            case when st = 'pending' then created
                 else least(now(), created + make_interval(mins => v_eta + 30)) end)
    returning id into v_order;

    k := 1 + floor(random() * 3)::int;
    insert into order_items (order_id, variant_id, product_id, product_name, size, color, quantity, price)
    select v_order, v.id, p.id, p.name, v.size, v.color, 1 + (random() < 0.25)::int, p.price
    from product_variants v
    join products p on p.id = v.product_id
    where p.shop_id = v_shop and p.moderation_status = 'approved'
    order by random()
    limit k;

    select sum(price * quantity) into v_total from order_items where order_id = v_order;
    update orders
    set total = coalesce(v_total, 0),
        platform_fee_rate = 7,
        platform_fee = round(coalesce(v_total, 0) * 0.07)::int,
        seller_net = coalesce(v_total, 0) - round(coalesce(v_total, 0) * 0.07)::int
    where id = v_order;
  end loop;
end $$;

-- sold_count = số lượng đã bán trong các đơn hoàn tất
update products p
set sold_count = x.q
from (
  select oi.product_id, sum(oi.quantity)::int as q
  from order_items oi join orders o on o.id = oi.order_id
  where o.status = 'completed'
  group by oi.product_id
) x
where x.product_id = p.id;

-- ---------- 5. Sự kiện phân tích (90 ngày) ----------
-- Lượt xem: cuối tuần cao hơn (x1.35), xu hướng tăng nhẹ về gần đây (x0.7 đến x1.2).
-- Thêm giỏ hàng: khoảng 8% lượt xem. Sự kiện purchase lấy từ đơn hoàn tất.

with days as (
  select g as d, (current_date - g) as day from generate_series(0, 89) g
),
shop_base as (
  select s.id as shop_id,
         case s.name when 'Shop Basic Wear' then 70 when 'Sweetie Style' then 45 else 3 end as base,
         (select array_agg(p.id order by p.id) from products p
           where p.shop_id = s.id and p.moderation_status = 'approved') as ids
  from shops s
),
counts as (
  select b.shop_id, b.ids, dd.day, t.event_type,
         greatest(0, round(
           b.base * t.ratio
           * (0.7 + 0.5 * (1 - dd.d / 89.0))
           * (case when extract(dow from dd.day) in (0, 6) then 1.35 else 1 end)
           * (0.85 + random() * 0.3)
         ))::int as n
  from shop_base b
  cross join days dd
  cross join (values ('view', 1.0), ('add_to_cart', 0.08)) t(event_type, ratio)
  where b.ids is not null
)
insert into analytics_events (shop_id, product_id, user_id, event_type, created_at)
select c.shop_id,
       c.ids[1 + floor(random() * array_length(c.ids, 1))::int],
       null,
       c.event_type,
       least(now(), (c.day::timestamp + random() * interval '1 day') at time zone 'Asia/Ho_Chi_Minh')
from counts c
cross join lateral generate_series(1, c.n) gs;

insert into analytics_events (shop_id, product_id, user_id, event_type, created_at)
select o.shop_id, oi.product_id, o.buyer_id, 'purchase', o.updated_at
from orders o
join order_items oi on oi.order_id = o.id
where o.status = 'completed';

-- ---------- 6. Đánh giá, số đo, chat, ticket ----------

insert into reviews (product_id, user_id, rating, comment, created_at)
select p.id, b.id,
       (array[3,4,4,5,5,5,5,4])[1 + floor(random() * 8)::int],
       (array['Chất vải đẹp, đúng mô tả.','Giao hàng nhanh, mặc vừa size.','Giá hợp lý, sẽ ủng hộ tiếp.',
              'Màu hơi khác ảnh một chút nhưng vẫn ổn.','Form đẹp, tôn dáng.','Đóng gói cẩn thận.'])
         [1 + floor(random() * 6)::int],
       now() - random() * interval '60 days'
from products p
cross join lateral (
  select id from profiles where role = 'buyer' order by random() limit 2 + floor(random() * 4)::int
) b
where p.moderation_status = 'approved';

insert into body_profiles (user_id, height_cm, weight_kg, body_shape, style_tags, budget_max, wishes)
select p.id, v.h, v.w, v.shape, v.tags::text[], v.budget, v.wishes
from (values
  ('buyer1@shop.example', 158, 50, 'pear',              '{nu-tinh,toi-gian}',     350000, 'Thích váy nhẹ nhàng đi làm'),
  ('buyer2@shop.example', 175, 70, 'rectangle',         '{streetwear,nang-dong}', 500000, 'Cần áo hoodie mùa lạnh'),
  ('buyer3@shop.example', 163, 55, 'hourglass',         '{cong-so,toi-gian}',     400000, 'Đồ công sở thoải mái'),
  ('buyer4@shop.example', 180, 78, 'inverted_triangle', '{the-thao,nang-dong}',   450000, 'Quần thể thao và giày'),
  ('buyer5@shop.example', 165, 68, 'apple',             '{nu-tinh,vintage}',      300000, 'Đầm che bụng')
) v(email, h, w, shape, tags, budget, wishes)
join profiles p on p.email = v.email;

insert into tickets (user_id, subject, content, status, created_at)
select id, 'Không nhận được mã xác nhận',
       'Em đăng ký tài khoản nhưng chưa vào được, nhờ admin hỗ trợ giúp em.', 'open', now() - interval '1 day'
from profiles where username = 'buyer3';

insert into tickets (user_id, subject, content, status, created_at)
select id, 'Sản phẩm bị chờ duyệt',
       'Sản phẩm của shop em đang ở trạng thái chờ duyệt, admin xem giúp em với.', 'open', now() - interval '3 hours'
from profiles where username = 'seller2';

insert into tickets (user_id, parent_id, content, status, created_at)
select (select id from profiles where username = 'admin'), t.id,
       'Admin đã kiểm tra, bạn thử đăng nhập lại giúp mình nhé.', 'open', now() - interval '20 hours'
from tickets t where t.subject = 'Không nhận được mã xác nhận';

-- ---------- 7. Hàng đợi kiểm duyệt và nhật ký AI chặn ----------

insert into moderation_queue (target_type, target_id, risk_score, reasons, status, created_at)
select 'product', id, risk_score, risk_reasons, 'pending', now() - interval '2 hours'
from products
where moderation_status in ('pending', 'blocked');

insert into ai_block_logs (target_type, target_id, owner_id, risk_score, reasons, action, created_at)
select 'product', p.id::text, s.owner_id, p.risk_score, p.risk_reasons,
       case p.moderation_status when 'blocked' then 'blocked' else 'pending_review' end,
       now() - interval '2 hours'
from products p
join shops s on s.id = p.shop_id
where p.moderation_status in ('pending', 'blocked');

-- Luxury Fashion có 2 sản phẩm bị chặn trong 7 ngày: mức "warning" (1 đến 2 mục)
insert into ai_block_logs (target_type, target_id, owner_id, risk_score, reasons, action, created_at)
select 'account', s.owner_id::text, s.owner_id, null,
       '[{"rule":"blocked_count","points":0,"detail":"2 sản phẩm bị chặn trong 7 ngày gần nhất"}]'::jsonb,
       'warning', now() - interval '2 hours'
from shops s where s.name = 'Luxury Fashion';

-- Một mục đã được Admin khôi phục hôm qua (cho ô "đã khôi phục" ở trang A2)
insert into ai_block_logs (target_type, target_id, owner_id, risk_score, reasons, action, restored, created_at)
select 'product', '4', s.owner_id, 35,
       '[{"rule":"short_description","points":10,"detail":"Mô tả ngắn"},{"rule":"spam_text","points":25,"detail":"Nghi ngờ spam"}]'::jsonb,
       'pending_review', true, now() - interval '1 day'
from shops s where s.name = 'Luxury Fashion';

-- ---------- 8. Kiểm tra nhanh ----------

select 'profiles' as bang, count(*) as so_dong from profiles
union all select 'shops', count(*) from shops
union all select 'products', count(*) from products
union all select 'product_variants', count(*) from product_variants
union all select 'product_images', count(*) from product_images
union all select 'orders', count(*) from orders
union all select 'order_items', count(*) from order_items
union all select 'reviews', count(*) from reviews
union all select 'analytics_events', count(*) from analytics_events
union all select 'moderation_queue', count(*) from moderation_queue
union all select 'ai_block_logs', count(*) from ai_block_logs
order by 1;