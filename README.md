# tg-ai-responder

Shaxsiy Telegram **user** akkauntini (bot emas) AI yordamida avtomatik javob beradigan servis. Har bir suhbatdosh haqida
qisqa "kontakt kartasi" (ContactContext) saqlanadi, javob yozishda butun tarix emas, shu karta va oxirgi 8 ta xabar
ishlatiladi. AI provayderi ikkita alohida servis: **Claude** (Anthropic SDK) va **Gemini** (google-genai SDK).

## Arxitektura

```
                       +-------------------------- Django admin (web) ---------------------------+
                       |  Account wizard (phone -> code -> 2FA), Chat sozlamalari, ContactContext,|
                       |  ProviderConfig (Fernet bilan shifrlangan kalitlar), MessageLog,         |
                       |  GlobalSettings (kill switch)                                            |
                       +---------------------------------+----------------------------------------+
                                                         |
                                                    PostgreSQL
                                                         |
  Telegram MTProto      +--------------------+     +-----+------+      +---------------------+
  <================>    | telegram-listener  |---->|   Redis    |<---->|   worker (Celery)   |
  (Telethon, har bir    |  1 ta jarayon,     |     | broker +   |      |  handle_incoming    |
   akkauntga bitta      |  N ta ulanish      |<----| tg:outbox  |      |  summarize_chat     |
   ulanish)             |  events.NewMessage |     +-----+------+      |  start_bootstrap    |
                        +--------------------+           ^             +----------+----------+
                          | media fayllar                |                        |
                          v                         +----+----+       POST /generate, /summarize,
                     [media volume] <-------------- |  beat   |       /describe-media
                                                    | maintain|       (api_key + X-Internal-Token)
                                                    +---------+                   |
                                                              +-------------------+------------------+
                                                              |                                      |
                                                     +--------v--------+                  +----------v------+
                                                     | claude-service  |                  | gemini-service  |
                                                     | FastAPI         |                  | FastAPI         |
                                                     | Anthropic SDK   |                  | google-genai    |
                                                     | ffmpeg kadrlar  |                  | video/audio     |
                                                     | faster-whisper  |                  | native          |
                                                     +-----------------+                  +-----------------+
```

Asosiy qoida: **Telegram bilan faqat `telegram-listener` gaplashadi.**

1. Listener yangi xabarni oladi, `MessageLog` ga yozadi (media bo'lsa `media` volume ga yuklab oladi) va
   `handle_incoming` Celery vazifasini `burst_window_seconds` kechikish bilan navbatga qo'yadi.
2. Worker kontekstni yig'adi (ContactContext + oxirgi 8 xabar), kerak bo'lsa ovoz/video ni matnga aylantiradi,
   AI servisdan javob oladi va `send_message` buyrug'ini Redis dagi `tg:outbox` ro'yxatiga qo'yadi.
3. Listener buyruqni oladi, "typing..." holatini ko'rsatib tasodifiy kechikish kutadi, yana bir bor tekshiradi
   (kill switch, egasi o'zi javob berdimi) va xabarni yuboradi.

Bootstrap ham xuddi shu yo'l bilan ishlaydi: worker `bootstrap_dialogs` / `fetch_chat_history` buyrug'ini
`tg:outbox` ga qo'yadi, listener dialoglarni o'qib bazaga yozadi va `summarize_chat` ni navbatga qo'yadi.

### Docker compose servislari

| Servis | Vazifasi |
|---|---|
| `web` | Django admin + DRF API (`/admin/`, `/api/`) |
| `telegram-listener` | `python manage.py run_listener`, barcha akkauntlar uchun bitta Telethon jarayoni |
| `worker` | Celery worker: javob, xulosa, bootstrap |
| `beat` | Celery beat: `maintain_contexts` (davriy kontekst yangilash) |
| `claude-service` | Claude FastAPI servisi (host portiga ochilmagan) |
| `gemini-service` | Gemini FastAPI servisi (host portiga ochilmagan) |
| `postgres`, `redis` | Ma'lumotlar bazasi va navbat |

### Modellar

- `Account` - Telegram akkaunti: `api_id`, shifrlangan `api_hash`, shifrlangan `StringSession`, holat, persona prompt,
  provayder (yoki global), `chat_filter_mode` (all / whitelist / blacklist), `allow_groups`.
- `GlobalSettings` - kill switch, standart provayder, rate limit, kechikishlar, xulosa va bootstrap limitlari.
- `ProviderConfig` - `claude` / `gemini` uchun shifrlangan API kalit va model.
- `Chat` - suhbat: turi, `auto_reply_enabled`, `list_status` (whitelist/blacklist), `messages_since_summary`.
- `ContactContext` - ism, munosabat, til, ohang, mavzular, `summary`, `facts` (JSON), `open_tasks`, `open_questions`,
  `last_summarized_msg_id`, `updated_at`.
- `MessageLog` - kiruvchi/chiquvchi xabarlar: `direction`, `media_type`, `text`, `transcript`, `provider`, tokenlar,
  `status`, `source` (contact / owner / ai / bootstrap).

## O'rnatish

### Docker bilan (production)

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Chiqqan qiymatni `.env` dagi `FERNET_KEY` ga yozing. `DJANGO_SECRET_KEY`, `INTERNAL_SERVICE_TOKEN` va
`POSTGRES_PASSWORD` ni ham tasodifiy qiymatlarga almashtiring. `FERNET_KEY` ni yo'qotmang: usiz saqlangan
sessiyalar va API kalitlarni ochib bo'lmaydi.

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Admin panel: `http://localhost:8000/admin/`.

### Lokal ishlab chiqish va testlar

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

Testlar SQLite bilan ishlaydi, Telegram, Redis, Celery va AI SDK lar to'liq mock qilingan. `POSTGRES_DB` berilmasa
Django avtomatik SQLite ishlatadi.

## Admin panel

1. **Provider configs** - `claude` va `gemini` uchun API kalitni kiriting. Kalit Fernet bilan shifrlanib bazaga
   yoziladi, ro'yxatda faqat niqoblangan ko'rinishda chiqadi (`sk-a********abcd`). Model bo'sh bo'lsa standart
   ishlatiladi: `claude-sonnet-5-5` (variant: `claude-opus-5-5`) va `gemini-2.5-flash`.
2. **Global settings** - kill switch, standart provayder, rate limit, kechikishlar, `resummarize_every_n_messages`,
   bootstrap limitlari.
3. **Accounts** - akkaunt qo'shish va ulash (pastda), auto-reply ni pauza/davom ettirish, persona prompt.
4. **Chats** - har bir suhbat uchun auto-reply on/off, whitelist/blacklist, "Re-bootstrap chat" va "Re-summarize now"
   amallari. ContactContext shu sahifada tahrirlanadi.
5. **Contact contexts** - kontakt kartalarini qo'lda tahrirlash.
6. **Message logs** - kiruvchi xabarlar, AI javoblari, transkriptlar, tokenlar va o'tkazib yuborish sabablari.

DRF API (faqat admin): `/api/accounts/`, `/api/chats/`, `/api/messages/`, `/api/kill-switch/`
(`POST {"enabled": true}`).

## Login jarayoni

1. [my.telegram.org](https://my.telegram.org) -> "API development tools" dan `api_id` va `api_hash` oling.
2. Admin -> Accounts -> Add: nom, telefon, `api_id`, `api_hash` (password maydon, saqlangandan keyin niqoblanadi).
3. Akkaunt sahifasidagi **Connect** tugmasi -> wizard:
   - **Telefon** - `send_code_request`, `phone_code_hash` va vaqtinchalik sessiya shifrlangan holda saqlanadi;
   - **Kod** - Telegram ilovasiga kelgan kod, `sign_in(phone, code, phone_code_hash)`;
   - **2FA parol** - akkauntda ikki bosqichli parol bo'lsa so'raladi.
4. Muvaffaqiyatli bo'lsa `StringSession` Fernet bilan shifrlanib saqlanadi, holat `connected` bo'ladi va bootstrap
   avtomatik boshlanadi. Listener har `LISTENER_ACCOUNT_SYNC_SECONDS` da yangi akkauntlarni o'zi ulaydi.
5. QR orqali login (ixtiyoriy):

   ```bash
   docker compose exec web python manage.py qr_login <account_id>
   ```

   Chiqqan `tg://login?token=...` havolani QR ga aylantirib Telegram -> Settings -> Devices -> Link Desktop Device
   orqali skanerlang.

Auto-reply standart holatda **o'chiq**. Kontekstlar tayyor bo'lgach akkauntda "Resume auto-reply" ni bosing.

## Bootstrap va kontekst vazifalari

**Bootstrap (bir marta).** Akkaunt ulanganda `start_bootstrap` `bootstrap_dialogs` buyrug'ini yuboradi. Listener
oxirgi `bootstrap_dialog_limit` ta shaxsiy dialogni (botlar va Saved Messages dan tashqari) aylanib chiqadi, har biridan
`bootstrap_messages_per_dialog` ta xabarni `source=bootstrap` bilan saqlaydi, dialoglar orasida pauza qiladi va
FloodWait bo'lsa kutadi. Har bir chat uchun `summarize_chat(mode="bootstrap")` ishga tushadi: xabarlar
`summary_chunk_size` bo'yicha bo'laklanadi, har bir bo'lak oldingi karta bilan birga AI ga beriladi va karta
to'ldiriladi (ism, munosabat, mavzular, til, ohang, faktlar, ochiq vazifalar va savollar).

**Davriy yangilash.**

- Har yangi xabarda `messages_since_summary` oshadi; u `resummarize_every_n_messages` ga yetganda
  `summarize_chat` darhol navbatga qo'yiladi.
- `beat` har `CONTEXT_MAINTENANCE_INTERVAL_SECONDS` da `maintain_contexts` ni ishga tushiradi: hisoblagichi N dan
  oshgan yoki kartasi `context_refresh_hours` dan eski va yangi xabarlari bor chatlarni yangilaydi.
- Xulosa faqat `last_summarized_msg_id` dan keyingi xabarlarni oladi va `summary`, `facts`, `open_tasks`,
  `open_questions`, `last_summarized_msg_id` ni yangilaydi, hisoblagichni nolga tushiradi.

**Javob berish.** Javob uchun hech qachon Telegram tarixi qayta o'qilmaydi: faqat ContactContext + bazadagi oxirgi
`recent_messages_count` (standart 8) ta xabar ishlatiladi.

## Media

| Tur | Claude | Gemini |
|---|---|---|
| Matn, rasm | Rasm `image` blok sifatida modelga beriladi | `Part.from_bytes` |
| Ovozli xabar, audio | faster-whisper transkripsiya | native audio tushunish |
| Video, dumaloq video (video note) | ffmpeg kadrlar + faster-whisper, keyin Claude kadrlarni tasvirlaydi | native video tushunish |

Ovoz/video matni `MessageLog.transcript` ga yoziladi va keyingi javob va xulosalarda matn sifatida ishlatiladi.
Javoblar matn ko'rinishida yuboriladi. Media hajmi `MAX_MEDIA_MB` bilan cheklangan.

## Provayderni almashtirish

- **Global:** Admin -> Global settings -> `default_provider`.
- **Akkaunt bo'yicha:** Admin -> Accounts -> `provider` (bo'sh = global) va ixtiyoriy `model_override`.
- **Model:** Admin -> Provider configs -> `model`, masalan `claude-opus-5-5`.

Worker har so'rovda shifrdan ochilgan API kalitni va `X-Internal-Token` ni servisga yuboradi. AI servislar kalit
saqlamaydi va host portlariga ochilmaydi (`expose`, `ports` emas), ular faqat compose ichki tarmog'ida.

Ichki interfeys (ikkala servisda bir xil):

- `POST /generate` - `{api_key, model, system, messages: [{role, content: [{type: text|image|audio|video, ...}]}], max_tokens}`
- `POST /summarize` - `{api_key, model, existing_context, messages: [{id, role, date, text}], mode: bootstrap|update}`
- `POST /describe-media` - `{api_key, model, media_type, mime_type, data_b64}`

## Xavfsizlik qoidalari

- Har bir chat uchun rate limit: `min_seconds_between_replies` va `max_replies_per_hour`.
- Tasodifiy "insoniy" kechikish (`reply_delay_min/max_seconds`) va "typing..." holati.
- Ketma-ket bir nechta xabar kelsa, faqat oxirgisiga javob beriladi (`burst_window_seconds`).
- Guruh va kanallarga javob berilmaydi, agar akkauntda `allow_groups` va chatda `auto_reply_enabled` yoqilmagan bo'lsa.
- O'z chiquvchi xabarlariga va AI yuborgan xabarlarga javob berilmaydi.
- Egasi o'zi qo'lda javob yozgan bo'lsa, AI javobi bekor qilinadi (yuborishdan oldin ham tekshiriladi).
- Global kill switch: yoqilganda hech qanday javob yuborilmaydi, navbatdagilari ham bekor qilinadi.
- Sessiyalar, `api_hash` va API kalitlar bazada Fernet bilan shifrlangan.

## Nega webhook emas

Telegram Bot API webhooklari faqat **botlar** uchun ishlaydi. Shaxsiy akkaunt MTProto protokoli orqali ishlaydi:
Telegram serveri user akkaunt uchun HTTP so'rov yubormaydi, yangilanishlarni faqat ochiq turgan MTProto ulanishi
orqali beradi. Shuning uchun:

- doimiy ishlaydigan bitta `telegram-listener` jarayoni har akkaunt uchun bitta Telethon ulanishini ushlab turadi
  (`events.NewMessage`);
- bitta akkaunt sessiyasini bir nechta jarayonda parallel ishlatish `AUTH_KEY_DUPLICATED` va sessiya bekor
  bo'lishiga olib keladi, shuning uchun Telegram bilan faqat listener gaplashadi, worker esa yuborish buyrug'ini
  Redis navbati orqali qaytaradi;
- og'ir ishlar (AI, transkripsiya, xulosa) Celery worker larda bajariladi va listenerni bloklamaydi.

## Loyiha tuzilishi

```
config/                 Django settings, celery, urls
core/                   modellar, admin, tasks, context, policy, ai_client, bus, media, telegram_login, DRF api
core/management/        run_listener, qr_login
listener/               Telethon servisi (service.py) va DB bilan ishlovchi handlerlar (handlers.py)
ai_services/common/     umumiy pydantic sxemalar, promptlar, ichki token tekshiruvi
ai_services/claude_service/   FastAPI + Anthropic SDK + ffmpeg/faster-whisper
ai_services/gemini_service/   FastAPI + google-genai
tests/                  pytest testlari (barcha tashqi tizimlar mock qilingan)
```
