#!/usr/bin/env python3
"""
Prodigy Content Agent — Интерактивный Telegram бот
Запуск: python3 bot.py

Команды:
  /script А         — готовый сценарий для формата А-З
  /reel [тема]      — сценарий по описанию темы
  /hook [тема]      — 7 вариантов хуков
  /cover ФОРМАТ|ХУК — сгенерировать обложку рилса (DALL-E 3)
  /plan             — план на следующую неделю
  /week             — расписание постов на эту неделю
  /stats            — статистика рилсов
  /trends           — тренды e-commerce этой недели
  /analyze [данные] — разбор поста конкурента
  /add [данные]     — добавить рилс в базу
  /help             — список команд
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv
import anthropic
import openai as _openai

# ── Импорт общих данных из main.py ───────────────────────────────────────────
from main import BRAND, load_data, save_data, FORMAT_NAMES, generate_plan, analyze

load_dotenv()

TG_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "")
claude       = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
openai_client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
BASE_DIR     = Path(__file__).parent


# ── Стили обложек по форматам для DALL-E промптов ────────────────────────────
# Базируются на визуальном стиле бренда: #0D0D0D фон, #3EA832 акцент, Montserrat Bold
COVER_STYLES: dict[str, str] = {
    "А": (
        "A frustrated Russian-speaking entrepreneur staring intensely at a laptop screen in a dark "
        "modern office. Dramatic side lighting. Near-black background. Stressed but determined expression."
    ),
    "Б": (
        "A minimalist dark educational slide design. Three items with bright green checkmark icons "
        "on a near-black background. Clean structured layout, premium modern aesthetic."
    ),
    "В": (
        "Authentic behind-the-scenes workspace: laptop showing a Shopify admin dashboard, a coffee cup, "
        "notebook with handwritten notes. Warm dim lighting, dark cozy atmosphere."
    ),
    "Г": (
        "A bold revenue growth chart line going sharply upward on a dark background, bright green line. "
        "Data numbers visible. Before-and-after split composition showing business transformation."
    ),
    "Д": (
        "A relatable humorous moment: an entrepreneur reacting with exaggerated surprise or disbelief "
        "at their laptop. Meme-style but professional. Dark background, candid expressive pose."
    ),
    "Е": (
        "Stark, confrontational text-heavy composition on near-black background. Bold high-contrast "
        "design, provocative energy. Minimal graphics, pure typography power. No faces."
    ),
    "Ж": (
        "Cinematic first-person POV shot: looking down at a Shopify store on a laptop screen, "
        "hands on keyboard visible. Shallow depth of field, dark moody atmosphere, immersive angle."
    ),
    "З": (
        "A Shopify website mockup on a dark screen being analyzed with annotation arrows, red and green "
        "markers highlighting problems and fixes. Analytical audit UI aesthetic, clean and professional."
    ),
}


# ═════════════════════════════════════════════════════════════════════════════
# TELEGRAM HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def tg_send(chat_id: int, text: str):
    """Отправить сообщение (с разбивкой если длинное)."""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram ошибка: {e}")


def tg_send_photo(chat_id: int, image_url: str, caption: str = ""):
    """Отправить фото в Telegram по URL."""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "photo": image_url,
            "caption": caption,
        }, timeout=30)
    except Exception as e:
        print(f"Telegram photo ошибка: {e}")


def tg_get_updates(offset: int = 0) -> list:
    """Получить новые апдейты."""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": offset, "timeout": 20}, timeout=25)
        return resp.json().get("result", [])
    except Exception:
        return []


# ═════════════════════════════════════════════════════════════════════════════
# CLAUDE
# ═════════════════════════════════════════════════════════════════════════════

def ask_claude(prompt: str, max_tokens: int = 1800) -> str:
    msg = claude.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


# ═════════════════════════════════════════════════════════════════════════════
# DALL-E COVER GENERATION
# ═════════════════════════════════════════════════════════════════════════════

def generate_cover_image(hook: str, fmt: str) -> str:
    """Генерирует обложку рилса через DALL-E 3. Возвращает URL изображения."""
    style = COVER_STYLES.get(fmt, COVER_STYLES["А"])

    prompt = f"""Instagram Reels vertical cover image (9:16 portrait) for @prodigylab.agency — \
a Shopify agency for Russian-speaking entrepreneurs in the USA.

Visual composition: {style}

Text overlay on the image — display this exact Russian text as the main bold white headline:
"{hook}"

Design requirements:
- Aspect ratio: 9:16 vertical portrait
- Background: near-black (#0D0D0D) or very dark gray
- Primary accent color: bright green (#3EA832) for positive/solution elements
- Text: white (#FFFFFF), bold uppercase, large Montserrat-style sans-serif font
- The Russian text "{hook}" must be prominently displayed as the main headline
- Minimal, modern, premium agency aesthetic
- No watermarks, no logos, no decorative borders
- Cinematic quality lighting and composition"""

    response = openai_client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1792",
        quality="standard",
        n=1,
    )
    return response.data[0].url


# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS
# ═════════════════════════════════════════════════════════════════════════════

def get_trends() -> str:
    """Тренды e-commerce за последние 7 дней через pytrends."""
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=360)

        keywords = ["shopify", "ecommerce", "online store", "dropshipping", "instagram shop"]
        pt.build_payload(keywords, timeframe="now 7-d", geo="US")

        related = pt.related_queries()
        lines = ["📈 ТРЕНДЫ E-COMMERCE (США, 7 дней)\n"]

        for kw in keywords:
            data = related.get(kw, {})
            rising = data.get("rising")
            if rising is not None and not rising.empty:
                top = rising.head(3)["query"].tolist()
                lines.append(f"🔍 {kw}: {' / '.join(top)}")

        if len(lines) == 1:
            lines.append("Данные недоступны — попробуй позже")

        return "\n".join(lines)

    except ImportError:
        return "❌ pytrends не установлен. Запусти: pip install pytrends"
    except Exception as e:
        return f"❌ Google Trends недоступен: {e}"


def get_trends_insight(trends_text: str) -> str:
    """Claude анализирует тренды и даёт рекомендации по контенту."""
    if "недоступен" in trends_text or "не установлен" in trends_text:
        return trends_text

    return ask_claude(f"""
Ты — контент-стратег @prodigylab.agency (Shopify-студия, США).

{BRAND}

ТРЕНДЫ E-COMMERCE ЭТОЙ НЕДЕЛИ:
{trends_text}

На основе трендов предложи:
1. 3 темы для рилсов которые актуальны прямо сейчас
2. Для каждой темы: формат (А-З) + точный хук (ЗАГЛАВНЫМИ)
3. Почему именно эти темы сработают сейчас

Конкретно, без воды.
""", max_tokens=1000)


# ═════════════════════════════════════════════════════════════════════════════
# КОМАНДЫ
# ═════════════════════════════════════════════════════════════════════════════

def cmd_help() -> str:
    return (
        "🤖 Prodigy Content Agent\n\n"
        "Команды:\n"
        "/script А         — сценарий для формата (А Б В Г Д Е Ж З)\n"
        "/reel [тема]      — сценарий по описанию темы\n"
        "/hook [тема]      — 7 вариантов хуков\n"
        "/cover А|ХУК      — обложка рилса через DALL-E 3\n"
        "/plan             — план на следующую неделю\n"
        "/week             — расписание постов на эту неделю\n"
        "/stats            — статистика рилсов\n"
        "/trends           — тренды e-commerce этой недели\n"
        "/analyze [данные] — разбор поста конкурента\n"
        "/add [данные]     — добавить рилс в базу\n"
        "/help             — список команд\n\n"
        "Примеры:\n"
        "/script Д\n"
        "/reel почему падает конверсия\n"
        "/hook брошенная корзина\n"
        "/cover А | ЛЬЁТЕ РЕКЛАМУ В ДЫРКУ?\n"
        "/analyze @rival | ТИЛЬДА УБИВАЕТ БИЗНЕС | 50k views | провокация\n"
        "/add А | ЛЬЁТЕ РЕКЛАМУ В ДЫРКУ? | 225 | 7 | 0 | 0 | 0"
    )


def cmd_script(fmt_arg: str) -> str:
    fmt = fmt_arg.strip().upper() if fmt_arg else "А"
    if fmt not in FORMAT_NAMES:
        valid = " ".join(FORMAT_NAMES.keys())
        return f"Неизвестный формат '{fmt}'. Доступны: {valid}"

    name = FORMAT_NAMES[fmt]
    tpl = {
        "А": "Хук→Боль→Усиление→Намёк на решение→CTA. 15-30 сек.",
        "Б": "Хук с цифрой→Тезис→3 пункта→'Сохрани'. 30-60 сек.",
        "В": "Хук→Процесс (экран или руки)→CTA. 15-45 сек.",
        "Г": "Результат→Было/стало→Что сделали→CTA. 30-60 сек.",
        "Д": "Setup→Реакция→Твист→Лёгкий CTA. 15-25 сек.",
        "Е": "Провокация→Логика→Оговорка→Дискуссия. 30-35 сек.",
        "Ж": "'POV:'→Сцена→Мораль. 15-30 сек.",
        "З": "Хук с цифрой→Screen разбор→CTA бесплатного аудита. 45-60 сек.",
    }

    script = ask_claude(f"""
Ты — сценарист Instagram Reels @prodigylab.agency.

{BRAND}

Напиши ОДИН полный сценарий — Формат {fmt} ({name}).
Структура: {tpl.get(fmt, '')}

Оформление:
ХУК (текст на экране): [ЗАГЛАВНЫМИ, max 7 слов]

ТАЙМИНГ:
[00-02 сек] ...
[02-10 сек] ...
...

ТЕКСТ РЕЧИ (дословно):
[весь текст]

CTA: [точная фраза]
МУЗЫКА: [характер трека]
РЕКВИЗИТ: [что нужно в кадре]

Живой разговорный язык. Без рекламных штампов.
""", max_tokens=1500)
    return script + f"\n\n---\nГенерировать обложку? Напиши:\n/cover {fmt} | [ХУК из сценария]"


def cmd_reel(topic: str) -> str:
    if not topic.strip():
        return "Укажи тему: /reel конверсия магазина упала"

    script = ask_claude(f"""
Ты — сценарист Instagram Reels @prodigylab.agency.

{BRAND}

Тема от автора: «{topic}»

1. Выбери лучший формат (А-З) для этой темы. Объясни почему.
2. Напиши полный сценарий:

ФОРМАТ: [буква + название]
ХУК (текст на экране): [ЗАГЛАВНЫМИ]

ТАЙМИНГ:
[00-02 сек] ...
...

ТЕКСТ РЕЧИ (дословно):

CTA:
МУЗЫКА:
РЕКВИЗИТ:
""", max_tokens=1500)
    return script + "\n\n---\nГенерировать обложку? Напиши:\n/cover ФОРМАТ | [ХУК из сценария]"


def cmd_hooks(topic: str) -> str:
    if not topic.strip():
        return "Укажи тему: /hook конверсия"

    return ask_claude(f"""
Ты — копирайтер Instagram Reels @prodigylab.agency.

{BRAND}

Тема: «{topic}»

Напиши 7 вариантов хука для первого кадра. Каждый:
— не длиннее 7 слов
— создаёт интригу или называет боль
— ЗАГЛАВНЫМИ

Формат ответа:
1. [ХУК] — Формат [X], почему сработает: ...
2. ...
""", max_tokens=800)


def cmd_stats(data: dict) -> str:
    reels = data.get("reels", [])
    if not reels:
        return "Нет данных о рилсах.\nДобавь через: python3 main.py → опция 1"

    lines = [f"📊 СТАТИСТИКА ({len(reels)} рилсов)\n"]
    fmt_stats: dict = {}

    for r in reels:
        fmt  = r.get("format", "?")
        views = r.get("metrics", {}).get("views", 0)
        fmt_stats.setdefault(fmt, {"count": 0, "views": 0})
        fmt_stats[fmt]["count"] += 1
        fmt_stats[fmt]["views"] += views

    for fmt, s in sorted(fmt_stats.items()):
        avg  = s["views"] // s["count"] if s["count"] else 0
        name = FORMAT_NAMES.get(fmt, "?")
        lines.append(f"Формат {fmt} ({name}): {s['count']} постов, avg {avg} views")

    top = sorted(reels, key=lambda x: x.get("metrics", {}).get("views", 0), reverse=True)[:3]
    lines.append("\n🏆 ТОП-3:")
    for r in top:
        v = r.get("metrics", {}).get("views", 0)
        lines.append(f"  {v} views — [{r.get('format')}] «{r.get('hook','')[:50]}»")

    return "\n".join(lines)


def cmd_plan(data: dict) -> str:
    analysis = analyze(data, [])
    return generate_plan(analysis, data)


def cmd_trends() -> str:
    raw     = get_trends()
    insight = get_trends_insight(raw)
    return f"{raw}\n\n{insight}"


def cmd_week() -> str:
    """Расписание постов на текущую неделю с датами."""
    from datetime import timedelta
    today          = datetime.now()
    start_of_week  = today - timedelta(days=today.weekday())  # Понедельник

    # (день недели 0=Пн, формат, цель)
    schedule = [
        (0, "Понедельник", "Д или Ж", "Юмор / POV — виральность и охват"),
        (2, "Среда",       "А",        "Боль — острый хук, проблема аудитории"),
        (4, "Пятница",     "Е или Б",  "Провокация / Образование — споры, сохранения"),
        (6, "Воскресенье", "В",         "За кулисами — человечность, доверие"),
    ]

    lines = ["📅 РАСПИСАНИЕ НА НЕДЕЛЮ\n"]
    for offset, day_name, fmt, purpose in schedule:
        post_date = start_of_week + timedelta(days=offset)
        date_str  = post_date.strftime("%d.%m")
        marker    = " ← сегодня" if post_date.date() == today.date() else ""
        lines.append(f"{date_str} {day_name} — Формат {fmt}{marker}")
        lines.append(f"   {purpose}")
        lines.append("")

    lines.append("Ритм: 4 поста в неделю")
    lines.append("Напиши /script [А-З] чтобы получить готовый сценарий")
    return "\n".join(lines)


def cmd_analyze(description: str) -> str:
    """Разбор поста конкурента. Формат: @username | хук | просмотры | почему работает."""
    if not description.strip():
        return (
            "Укажи данные конкурента через |:\n"
            "/analyze @username | хук/тема | просмотры | почему сработало\n\n"
            "Пример:\n"
            "/analyze @shopify_russia | ТИЛЬДА УБИВАЕТ БИЗНЕС | 50k | провокация, злит всех"
        )

    return ask_claude(f"""
Ты — контент-стратег @prodigylab.agency (Shopify-студия, США).

{BRAND}

ДАННЫЕ О ПОСТЕ КОНКУРЕНТА:
{description}

Сделай разбор по 5 пунктам:
1. Формат (А-З): какой формат использован и почему работает
2. Хук: что именно цепляет в первую секунду
3. Что взять себе: конкретный приём (не копируя 1 в 1)
4. Что НЕ копировать: почему именно этот подход может не сработать у нас
5. Готовая идея: похожий рилс для @prodigylab.agency — точный хук (ЗАГЛАВНЫМИ) + формат

Конкретно, actionable.
""", max_tokens=900)


def cmd_cover(args: str, chat_id: int) -> str:
    """Генерирует обложку рилса через DALL-E 3 и отправляет фото в Telegram."""
    if not args.strip():
        return (
            "Укажи формат и хук через |:\n"
            "/cover ФОРМАТ | ХУК\n\n"
            "Примеры:\n"
            "/cover А | ЛЬЁТЕ РЕКЛАМУ В ДЫРКУ?\n"
            "/cover Е | ТИЛЬДА УБИВАЕТ БИЗНЕС\n"
            "/cover Д | POV: ТЫ НАНЯЛ ФРИЛАНСЕРА\n\n"
            "Форматы: А Б В Г Д Е Ж З\n"
            "Результат: вертикальная 9:16 обложка в стиле бренда"
        )

    parts = [p.strip() for p in args.split("|", 1)]
    if len(parts) == 2:
        fmt  = parts[0].upper()
        hook = parts[1]
    else:
        fmt  = "А"
        hook = args.strip()

    if fmt not in FORMAT_NAMES:
        fmt = "А"

    if not hook:
        return "Укажи текст хука — он будет напечатан на обложке."

    if not os.getenv("OPENAI_API_KEY"):
        return "OPENAI_API_KEY не задан в .env — добавь ключ и перезапусти бота."

    try:
        image_url = generate_cover_image(hook, fmt)
        caption   = f"[{fmt}] {hook[:80]}"
        tg_send_photo(chat_id, image_url, caption=caption)
        return (
            f"Обложка готова!\n\n"
            f"Формат: {fmt} — {FORMAT_NAMES[fmt]}\n"
            f"Хук: «{hook}»\n\n"
            "Не нравится? Пришли команду ещё раз — DALL-E генерирует каждый раз новый вариант."
        )
    except Exception as e:
        return f"Ошибка генерации: {e}"


def cmd_add(args: str, data: dict) -> str:
    """Добавить рилс в базу. Формат: ФОРМАТ | ХУК | VIEWS | LIKES | SAVES | SHARES | COMMENTS"""
    if not args.strip():
        fmt_list = " ".join(f"{k}={v}" for k, v in FORMAT_NAMES.items())
        return (
            "Укажи данные рилса через |:\n"
            "/add ФОРМАТ | ХУК | VIEWS | LIKES | SAVES | SHARES | COMMENTS\n\n"
            "Пример:\n"
            "/add А | ЛЬЁТЕ РЕКЛАМУ В ДЫРКУ? | 225 | 7 | 0 | 0 | 0\n\n"
            f"Форматы: {fmt_list}"
        )

    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 2:
        return "Неверный формат. Нужно минимум: /add ФОРМАТ | ХУК"

    fmt = parts[0].upper()
    if fmt not in FORMAT_NAMES:
        return f"Неизвестный формат '{fmt}'. Доступны: {' '.join(FORMAT_NAMES.keys())}"

    hook = parts[1]
    if not hook:
        return "Укажи хук (текст первого кадра)"

    def _int(s: str) -> int:
        s = s.strip()
        return int(s) if s.isdigit() else 0

    reel = {
        "id":          f"reel_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "format":      fmt,
        "format_name": FORMAT_NAMES[fmt],
        "hook":        hook,
        "notes":       "Добавлен через Telegram бот",
        "metrics": {
            "views":    _int(parts[2]) if len(parts) > 2 else 0,
            "likes":    _int(parts[3]) if len(parts) > 3 else 0,
            "saves":    _int(parts[4]) if len(parts) > 4 else 0,
            "shares":   _int(parts[5]) if len(parts) > 5 else 0,
            "comments": _int(parts[6]) if len(parts) > 6 else 0,
            "reach":    0,
            "days_live": 1,
        }
    }

    data["reels"].append(reel)
    save_data(data)

    m = reel["metrics"]
    return (
        f"✅ Рилс добавлен в базу!\n\n"
        f"Формат: {fmt} ({FORMAT_NAMES[fmt]})\n"
        f"Хук: «{hook[:60]}»\n"
        f"Views: {m['views']} | Likes: {m['likes']} | Saves: {m['saves']} | Shares: {m['shares']}\n\n"
        f"Всего рилсов в базе: {len(data['reels'])}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ═════════════════════════════════════════════════════════════════════════════

def dispatch(text: str, data: dict, chat_id: int = 0) -> str | None:
    text = text.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(" ", 1)
    cmd   = parts[0].lower().split("@")[0]   # убираем @botname если есть
    args  = parts[1] if len(parts) > 1 else ""

    commands = {
        "/start":   lambda: cmd_help(),
        "/help":    lambda: cmd_help(),
        "/script":  lambda: cmd_script(args),
        "/reel":    lambda: cmd_reel(args),
        "/hook":    lambda: cmd_hooks(args),
        "/hooks":   lambda: cmd_hooks(args),
        "/cover":   lambda: cmd_cover(args, chat_id),
        "/plan":    lambda: cmd_plan(data),
        "/week":    lambda: cmd_week(),
        "/stats":   lambda: cmd_stats(data),
        "/trends":  lambda: cmd_trends(),
        "/analyze": lambda: cmd_analyze(args),
        "/add":     lambda: cmd_add(args, data),
    }

    handler = commands.get(cmd)
    if handler:
        return handler()
    return f"Неизвестная команда '{cmd}'. Напиши /help"


# ═════════════════════════════════════════════════════════════════════════════
# POLLING LOOP
# ═════════════════════════════════════════════════════════════════════════════

def run():
    print("""
╔═══════════════════════════════════════════════════╗
║     PRODIGY BOT — запущен, слушаю команды        ║
║     Ctrl+C для остановки                         ║
╚═══════════════════════════════════════════════════╝""")

    offset = 0

    while True:
        try:
            updates = tg_get_updates(offset)

            for upd in updates:
                offset = upd["update_id"] + 1
                msg    = upd.get("message", {})
                text   = msg.get("text", "")
                chat   = msg.get("chat", {})
                chat_id = chat.get("id")

                if not text or not chat_id:
                    continue

                sender = chat.get("first_name", "")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {sender}: {text[:60]}")

                data = load_data()
                tg_send(chat_id, "⏳ Генерирую...")

                reply = dispatch(text, data, chat_id)
                if reply:
                    tg_send(chat_id, reply)
                    print(f"  → отправлено ({len(reply)} символов)")

        except KeyboardInterrupt:
            print("\n👋 Бот остановлен")
            break
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)

        time.sleep(1)


if __name__ == "__main__":
    run()
