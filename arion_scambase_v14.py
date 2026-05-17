#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════════╗
  ⚜️  ARION SCAM BASE  v14.0  ⚜️
  ★ ▬▬▬▬▬▬▬▬▬▬ ★
  pip install aiogram==3.7.0 aiosqlite aiohttp python-dotenv
  python arion_scambase_v14.py
  ★ ▬▬▬▬▬▬▬▬▬▬ ★
╚══════════════════════════════════════════════╝

Changelog v14.0:
  [NEW]  Система апелляций для людей из базы
  [NEW]  Двухуровневое рассмотрение апелляций (рассмотритель → модератор)
  [NEW]  Username сохраняется при добавлении сотрудника
  [FIX]  Батчинг рассылки (антилимит Telegram)
  [FIX]  Валидация доказательств при добавлении в базу
  [FIX]  FSM таймеры не дублируются
  [FIX]  Поиск сотрудника по username корректен
  [NEW]  API: эндпоинты для апелляций
  [NEW]  API: поиск по базе
  [NEW]  Лог всех действий модераторов в БД
"""

import asyncio
import csv
import io
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from dotenv import load_dotenv
load_dotenv()

import aiohttp
from aiohttp import web
import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, BotCommand,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo, BufferedInputFile,
)
from aiogram.exceptions import (
    TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest
)

# ============================================
#         НАСТРОЙКИ ИЗ .env
# ============================================

BOT_TOKEN             = os.getenv("ARION_TOKEN", "ТОКЕН_ПУБЛИЧНОГО_БОТА")
MAIN_ADMIN_ID         = int(os.getenv("MAIN_ADMIN_ID", "0"))
CONSIDERATION_CHAT_ID = int(os.getenv("CONSIDERATION_CHAT_ID", "0"))
REPORT_CHAT_ID        = int(os.getenv("REPORT_CHAT_ID", "0"))
CONS_GROUP_CHAT_ID    = int(os.getenv("CONS_GROUP_CHAT_ID", "0"))
APPEAL_CHAT_ID        = int(os.getenv("APPEAL_CHAT_ID", "0"))   # чат для апелляций
API_PORT              = int(os.getenv("API_PORT", "8080"))
API_SECRET            = os.getenv("API_SECRET", "CHANGE_ME_SECRET_KEY")
MINI_APP_URL          = os.getenv("MINI_APP_URL", "https://your-username.github.io/arion-miniapp")

OTHER_BOTS: Dict[str, str] = {
    name: token for name, token in [
        item.split(":") for item in os.getenv("OTHER_BOTS", "").split(",") if ":" in item
    ]
} if os.getenv("OTHER_BOTS") else {
    "Forum":     "ForumBaseRobot",
    "Syndicate": "SyndicateCheckBot",
}

DB_PATH        = "arion_shared.db"
DESIGN_DB_PATH = "arion_design.db"

RATE_LIMIT_SECONDS   = 3
FSM_TIMEOUT_SEC      = 600
ROLE_CACHE_TTL       = 120
BROADCAST_BATCH_SIZE = 25
BROADCAST_COOLDOWN   = 0.05   # 20 msg/s — безопасно

# ============================================
#         СИСТЕМА РАНГОВ
# ============================================

MOD_RANKS: List[Tuple[str, int]] = [
    ("Бронза",   35),
    ("Железо",   35),
    ("Медь",     35),
    ("Серебро",  50),
    ("Золото",   50),
    ("Платина",  50),
    ("Алмаз",    75),
    ("Сапфир",   75),
    ("Рубин",    75),
    ("Семицвет",  0),
]

RANK_EMOJI: Dict[str, str] = {
    "Бронза":   "🥉", "Железо":  "⚙️", "Медь":    "🔶",
    "Серебро":  "🥈", "Золото":  "🥇", "Платина": "💎",
    "Алмаз":   "💠", "Сапфир":  "🔷", "Рубин":   "🔴",
    "Семицвет": "🌈",
}

# ============================================
#         ДИЗАЙН
# ============================================

DIVIDER      = "★ ▬▬▬▬▬▬▬▬▬▬ ★"
HEADER       = "⚜️ ⋙ ARION SCAM BASE ⋘ ⚜️"
FOOTER       = "🛡️ Защищено системой ARION | v14.0"
LINE         = "━━━━━━━━━━━━━━━━━━━━━━"

STATUS_EMOJI: Dict[str, str] = {
    "scammer":   "🔥",
    "guarantor": "💎",
    "trusted":   "🫧",
}

ROLE_LABELS: Dict[str, str] = {
    "head_admin": "👑 Главный Администратор",
    "admin":      "🛡️ Администратор",
    "guarantor":  "💎 Гарант",
    "reviewer":   "🔍 Рассмотритель",
    "moderator":  "🔨 Модератор",
}

DEFAULT_TEXTS: Dict[str, str] = {
    "welcome_admin": (
        f"{HEADER}\n{DIVIDER}\n\n💎 *ДОБРО ПОЖАЛОВАТЬ В ARION SCAM BASE*\n\n"
        f"Вы вошли в единую систему защиты от мошенников.\n\n{DIVIDER}\n\n"
        f"⚔️ *ДОСТУПНЫЕ ОПЕРАЦИИ:*\n\n"
        f"🔎 ПРОВЕРИТЬ — пробить по базе\n📋 ИСТОРИЯ — архив ваших проверок\n"
        f"📊 СТАТИСТИКА — боевая сводка\n🗑 СБРОС — очистка данных\n📱 MINI APP — быстрый доступ\n\n"
        f"{DIVIDER}\n{FOOTER}"
    ),
    "welcome_user": (
        f"{HEADER}\n{DIVIDER}\n\n💎 *ДОБРО ПОЖАЛОВАТЬ В ARION SCAM BASE*\n\n"
        f"Вы вошли в единую систему защиты от мошенников.\n\n{DIVIDER}\n\n"
        f"⚔️ *ДОСТУПНЫЕ ОПЕРАЦИИ:*\n\n"
        f"🔎 ПРОВЕРИТЬ — пробить по базе\n🚨 ПОЖАЛОВАТЬСЯ — сообщить о скамере\n"
        f"📋 ИСТОРИЯ — архив ваших проверок\n📱 MINI APP — быстрый доступ\n\n"
        f"{DIVIDER}\n{FOOTER}"
    ),
    "check_start":   f"{HEADER}\n{DIVIDER}\n\n🔎 *ЗАПУЩЕНА ПРОВЕРКА*\n\n⚙️ Анализ цели...\n🔒 Запрос защищён\n\n",
    "scammer_found": f"{HEADER}\n{DIVIDER}\n\n🔥 *ВНИМАНИЕ! ЦЕЛЬ ОБНАРУЖЕНА!*\n\n⚠️ Статус: *МОШЕННИК*\n🚫 Рекомендация: *НЕ СВЯЗЫВАТЬСЯ*\n\n",
    "user_clean":    f"{HEADER}\n{DIVIDER}\n\n🫧 *ПРОВЕРКА ЗАВЕРШЕНА*\n\n💎 Статус: *ЧИСТ*\n\n✅ Компромата в нашей базе не обнаружено.\n⚠️ Сохраняйте бдительность.\n\n{DIVIDER}\n{FOOTER}",
    "report_start":  f"{HEADER}\n{DIVIDER}\n\n🚨 *ПОДАЧА ЖАЛОБЫ*\n\n📋 Укажите данные нарушителя.\n🔍 Все жалобы проходят модерацию.\n⚡ Ложные доносы строго запрещены.\n\n",
    "report_success":f"{HEADER}\n{DIVIDER}\n\n✅ *ЖАЛОБА УСПЕШНО ПРИНЯТА!*\n\n🙏 Спасибо за помощь!\n🔍 Рассмотрители изучат её в ближайшее время.\n\n{DIVIDER}\n{FOOTER}",
    "cons_form":     f"{HEADER}\n{DIVIDER}\n\n📝 *ФОРМА ЖАЛОБЫ (/cons)*\n\nЗаполните жалобу:\n\n1️⃣ *ID и @username* нарушителя\n2️⃣ *Причина* — скам / фейк / невозврат\n3️⃣ *Краткое пояснение*\n4️⃣ *Медиа* — скриншоты или видео\n\n{DIVIDER}\n⚡ Когда закончите — отправьте команду */Not*\n\n{FOOTER}",
    "stats":         f"{HEADER}\n{DIVIDER}\n\n📈 *БОЕВАЯ СВОДКА СИСТЕМЫ*\n\n",
    "history_empty": f"{HEADER}\n{DIVIDER}\n\n📜 *АРХИВ ПРОВЕРОК*\n\n🔍 Вы ещё не проводили проверки.\n\n{DIVIDER}\n{FOOTER}",
}

# ============================================
#         ЛОГГИРОВАНИЕ
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ArionV14] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scambase.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("ArionV14")

# ============================================
#         БД — КОНТЕКСТ-МЕНЕДЖЕР
# ============================================

class _DB:
    __slots__ = ("path", "db")
    def __init__(self, path: str):
        self.path = path
        self.db   = None
    async def __aenter__(self):
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        return self.db
    async def __aexit__(self, *a):
        if self.db:
            await self.db.close()

def mdb(): return _DB(DB_PATH)
def ddb(): return _DB(DESIGN_DB_PATH)

# ============================================
#         ИНИЦИАЛИЗАЦИЯ БД
# ============================================

async def init_db():
    async with mdb() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE,
                username TEXT,
                status TEXT DEFAULT 'scammer',
                reason TEXT,
                evidence TEXT,
                added_by TEXT,
                added_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS check_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checker_id TEXT,
                target_id TEXT,
                result TEXT,
                checked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS bot_users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id TEXT,
                target_id TEXT,
                target_un TEXT,
                report_type TEXT,
                description TEXT,
                evidence TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cons_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id TEXT,
                message_text TEXT,
                media_file_id TEXT,
                media_type TEXT,
                status TEXT DEFAULT 'pending_review',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staff (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'reviewer',
                added_by INTEGER,
                added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_url TEXT,
                title TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS mod_ranks (
                telegram_id INTEGER PRIMARY KEY,
                rank TEXT DEFAULT 'Бронза',
                total_actions INTEGER DEFAULT 0,
                rank_actions INTEGER DEFAULT 0,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS system_stats (
                stat_key TEXT PRIMARY KEY,
                stat_value TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS mod_action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moderator_id TEXT,
                action TEXT,
                target TEXT,
                details TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appellant_id TEXT,
                appellant_username TEXT,
                target_id TEXT,
                reason TEXT,
                evidence TEXT,
                status TEXT DEFAULT 'pending',
                reviewer_id TEXT,
                moderator_id TEXT,
                reviewer_note TEXT,
                moderator_note TEXT,
                created_at TEXT,
                updated_at TEXT
            );
        """)
        await db.commit()

        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        for key in ["checks", "found", "clean", "reports", "appeals_approved", "appeals_rejected"]:
            await db.execute(
                "INSERT OR IGNORE INTO system_stats (stat_key, stat_value, updated_at) VALUES (?, '0', ?)",
                (key, now_str)
            )
        await db.commit()

    await init_design_db()
    log.info("✅ БД готова")

async def init_design_db():
    async with ddb() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS banners (
                name TEXT PRIMARY KEY,
                file_id TEXT,
                file_type TEXT DEFAULT 'gif',
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS texts (
                name TEXT PRIMARY KEY,
                content TEXT,
                updated_at TEXT
            );
        """)
        await db.commit()

    async with ddb() as db:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        for name, content in DEFAULT_TEXTS.items():
            await db.execute(
                "INSERT OR IGNORE INTO texts (name, content, updated_at) VALUES (?, ?, ?)",
                (name, content, now_str)
            )
        await db.commit()

# ============================================
#         СТАТИСТИКА
# ============================================

async def inc_stat(key: str, delta: int = 1):
    async with mdb() as db:
        cur = await db.execute("SELECT stat_value FROM system_stats WHERE stat_key=?", (key,))
        row = await cur.fetchone()
        val = int(row[0]) if row else 0
        await db.execute(
            "INSERT OR REPLACE INTO system_stats (stat_key, stat_value, updated_at) VALUES (?, ?, ?)",
            (key, str(val + delta), datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        await db.commit()

async def get_all_stats() -> Dict[str, int]:
    stats = {"checks": 0, "found": 0, "clean": 0, "reports": 0,
             "appeals_approved": 0, "appeals_rejected": 0}
    async with mdb() as db:
        for key in stats:
            cur = await db.execute("SELECT stat_value FROM system_stats WHERE stat_key=?", (key,))
            row = await cur.fetchone()
            if row:
                stats[key] = int(row[0])
    return stats

# ============================================
#         ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")

def sanitize(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def validate_identifier(identifier: str) -> Optional[str]:
    ident = identifier.strip().lstrip("@")
    if re.match(r"^[a-zA-Z0-9_]{4,32}$|^\d{5,15}$", ident):
        return ident
    return None

def bar(pct: int) -> str:
    filled = int(10 * pct / 100)
    return f"[{'█' * filled}{'░' * (10 - filled)}] {pct}%"

# Rate limiter
_rl_cache: Dict[int, float] = {}
_rl_lock = asyncio.Lock()

async def rate_ok(user_id: int) -> bool:
    async with _rl_lock:
        t = time.monotonic()
        if t - _rl_cache.get(user_id, 0) < RATE_LIMIT_SECONDS:
            return False
        _rl_cache[user_id] = t
        if len(_rl_cache) > 50000:
            cutoff = t - 3600
            for uid in [u for u, ts in list(_rl_cache.items()) if ts < cutoff]:
                del _rl_cache[uid]
        return True

# Role cache
_role_cache: Dict[int, Tuple[Optional[str], float]] = {}
_role_lock = asyncio.Lock()

async def get_role(telegram_id: int) -> Optional[str]:
    if telegram_id == MAIN_ADMIN_ID:
        return "head_admin"
    async with _role_lock:
        entry = _role_cache.get(telegram_id)
        if entry and time.monotonic() - entry[1] < ROLE_CACHE_TTL:
            return entry[0]
    try:
        async with mdb() as db:
            cur = await db.execute("SELECT role FROM staff WHERE telegram_id=?", (telegram_id,))
            row = await cur.fetchone()
        role = row["role"] if row else None
    except Exception:
        role = None
    async with _role_lock:
        _role_cache[telegram_id] = (role, time.monotonic())
    return role

def invalidate_role(telegram_id: int):
    _role_cache.pop(telegram_id, None)

# FSM таймеры
_fsm_timers: Dict[int, asyncio.TimerHandle] = {}

def fsm_schedule(user_id: int, state: FSMContext, loop: asyncio.AbstractEventLoop):
    if user_id in _fsm_timers:
        _fsm_timers[user_id].cancel()
    async def clear():
        if await state.get_state():
            await state.clear()
    handle = loop.call_later(FSM_TIMEOUT_SEC, lambda: asyncio.create_task(clear()))
    _fsm_timers[user_id] = handle

def fsm_cancel(user_id: int):
    handle = _fsm_timers.pop(user_id, None)
    if handle:
        handle.cancel()

# Лог действий модераторов
async def mod_log(moderator_id: str, action: str, target: str, details: str = ""):
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT INTO mod_action_log (moderator_id, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (moderator_id, action, target, details, now())
            )
            await db.commit()
    except Exception as e:
        log.error(f"mod_log: {e}")

# ============================================
#         БД ОПЕРАЦИИ — ПОЛЬЗОВАТЕЛИ
# ============================================

async def db_register_user(user) -> None:
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT OR IGNORE INTO bot_users (telegram_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.first_name, now())
            )
            await db.commit()
    except Exception as e:
        log.error(f"db_register_user: {e}")

async def db_get_user(identifier: str):
    try:
        ident = identifier.lstrip("@").lower()
        async with mdb() as db:
            cur = await db.execute(
                "SELECT * FROM users WHERE LOWER(telegram_id)=? OR LOWER(username)=?",
                (ident, ident)
            )
            return await cur.fetchone()
    except Exception:
        return None

async def db_add_user(telegram_id: str, username: Optional[str], status: str,
                      reason: str, evidence: Optional[str], added_by: str) -> bool:
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT OR REPLACE INTO users "
                "(telegram_id, username, status, reason, evidence, added_by, added_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (telegram_id, username, status, reason, evidence, added_by, now(), now())
            )
            await db.commit()
        await mod_log(added_by, "add_user", telegram_id, f"status={status} reason={reason[:80]}")
        return True
    except Exception as e:
        log.error(f"db_add_user: {e}")
        return False

async def db_delete_user(identifier: str, deleted_by: str = "system") -> bool:
    try:
        ident = identifier.lstrip("@").lower()
        async with mdb() as db:
            cur = await db.execute(
                "DELETE FROM users WHERE LOWER(telegram_id)=? OR LOWER(username)=?",
                (ident, ident)
            )
            await db.commit()
        if cur.rowcount > 0:
            await mod_log(deleted_by, "delete_user", identifier)
        return cur.rowcount > 0
    except Exception:
        return False

async def db_count(table: str, where: str = "") -> int:
    try:
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        async with mdb() as db:
            cur = await db.execute(q)
            row = await cur.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0

async def db_add_history(checker_id: str, target_id: str, result: str):
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT INTO check_history (checker_id, target_id, result, checked_at) VALUES (?, ?, ?, ?)",
                (checker_id, target_id, result, now())
            )
            await db.commit()
    except Exception as e:
        log.error(f"db_add_history: {e}")

async def db_get_history(checker_id: str, limit: int = 5):
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT target_id, result, checked_at FROM check_history "
                "WHERE checker_id=? ORDER BY id DESC LIMIT ?",
                (str(checker_id), limit)
            )
            return await cur.fetchall()
    except Exception:
        return []

# ============================================
#         БД ОПЕРАЦИИ — ЖАЛОБЫ
# ============================================

async def db_add_report(reporter_id: str, target_id: str, target_un: str,
                        report_type: str, description: str, evidence: Optional[str]) -> Optional[int]:
    try:
        async with mdb() as db:
            cur = await db.execute(
                "INSERT INTO reports (reporter_id, target_id, target_un, report_type, "
                "description, evidence, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (reporter_id, target_id, target_un, report_type, description, evidence, now())
            )
            await db.commit()
            return cur.lastrowid
    except Exception:
        return None

async def db_update_report_status(report_id: int, status: str):
    try:
        async with mdb() as db:
            await db.execute(
                "UPDATE reports SET status=?, updated_at=? WHERE id=?",
                (status, now(), report_id)
            )
            await db.commit()
    except Exception as e:
        log.error(f"db_update_report_status: {e}")

async def db_pending_reports(limit: int = 5):
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT * FROM reports WHERE status='pending' ORDER BY id ASC LIMIT ?", (limit,)
            )
            return await cur.fetchall()
    except Exception:
        return []

# ============================================
#         БД ОПЕРАЦИИ — /cons
# ============================================

async def db_save_cons(reporter_id: str, text: str,
                       media_id: Optional[str], media_type: Optional[str]) -> Optional[int]:
    try:
        async with mdb() as db:
            cur = await db.execute(
                "INSERT INTO cons_reports (reporter_id, message_text, media_file_id, media_type, "
                "status, created_at) VALUES (?, ?, ?, ?, 'pending_review', ?)",
                (reporter_id, text, media_id, media_type, now())
            )
            await db.commit()
            return cur.lastrowid
    except Exception:
        return None

async def db_get_cons(cons_id: int):
    try:
        async with mdb() as db:
            cur = await db.execute("SELECT * FROM cons_reports WHERE id=?", (cons_id,))
            return await cur.fetchone()
    except Exception:
        return None

async def db_update_cons_status(cons_id: int, status: str):
    try:
        async with mdb() as db:
            await db.execute(
                "UPDATE cons_reports SET status=?, updated_at=? WHERE id=?",
                (status, now(), cons_id)
            )
            await db.commit()
    except Exception:
        pass

async def db_pending_cons(limit: int = 10):
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT * FROM cons_reports WHERE status='pending_review' ORDER BY id ASC LIMIT ?",
                (limit,)
            )
            return await cur.fetchall()
    except Exception:
        return []

# ============================================
#         БД ОПЕРАЦИИ — АПЕЛЛЯЦИИ
# ============================================

async def db_create_appeal(appellant_id: str, appellant_username: str,
                           target_id: str, reason: str, evidence: Optional[str]) -> Optional[int]:
    try:
        async with mdb() as db:
            cur = await db.execute(
                "INSERT INTO appeals (appellant_id, appellant_username, target_id, reason, "
                "evidence, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (appellant_id, appellant_username, target_id, reason, evidence, now())
            )
            await db.commit()
            return cur.lastrowid
    except Exception as e:
        log.error(f"db_create_appeal: {e}")
        return None

async def db_get_appeal(appeal_id: int):
    try:
        async with mdb() as db:
            cur = await db.execute("SELECT * FROM appeals WHERE id=?", (appeal_id,))
            return await cur.fetchone()
    except Exception:
        return None

async def db_update_appeal(appeal_id: int, **kwargs):
    try:
        sets  = ", ".join(f"{k}=?" for k in kwargs)
        vals  = list(kwargs.values()) + [now(), appeal_id]
        async with mdb() as db:
            await db.execute(
                f"UPDATE appeals SET {sets}, updated_at=? WHERE id=?", vals
            )
            await db.commit()
    except Exception as e:
        log.error(f"db_update_appeal: {e}")

async def db_pending_appeals(stage: str = "pending", limit: int = 10):
    """stage: 'pending' — новые, 'reviewer_approved' — ждут модератора"""
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT * FROM appeals WHERE status=? ORDER BY id ASC LIMIT ?",
                (stage, limit)
            )
            return await cur.fetchall()
    except Exception:
        return []

async def db_check_open_appeal(target_id: str) -> bool:
    """Есть ли уже открытая апелляция для данного target_id"""
    try:
        ident = target_id.lstrip("@").lower()
        async with mdb() as db:
            cur = await db.execute(
                "SELECT id FROM appeals WHERE LOWER(target_id)=? "
                "AND status NOT IN ('approved','rejected') LIMIT 1",
                (ident,)
            )
            return await cur.fetchone() is not None
    except Exception:
        return False

# ============================================
#         БД ОПЕРАЦИИ — РАНГИ
# ============================================

async def get_mod_rank(telegram_id: int) -> Tuple[str, int, int]:
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT rank, total_actions, rank_actions FROM mod_ranks WHERE telegram_id=?",
                (telegram_id,)
            )
            row = await cur.fetchone()
        if row:
            return row["rank"], row["total_actions"], row["rank_actions"]
    except Exception:
        pass
    return "Бронза", 0, 0

async def update_mod_rank(telegram_id: int, increment: int = 1) -> Optional[str]:
    role = await get_role(telegram_id)
    if role not in ("moderator", "reviewer", "admin", "head_admin"):
        return None

    cur_rank, total, rank_actions = await get_mod_rank(telegram_id)
    new_rank         = cur_rank
    new_rank_actions = rank_actions + increment
    new_total        = total + increment
    promoted         = False

    rank_index = next((i for i, (r, _) in enumerate(MOD_RANKS) if r == cur_rank), None)
    if rank_index is None:
        return None

    need = MOD_RANKS[rank_index][1]

    if cur_rank == "Семицвет":
        new_rank_actions = rank_actions
    elif need > 0 and new_rank_actions >= need:
        if rank_index + 1 < len(MOD_RANKS):
            new_rank         = MOD_RANKS[rank_index + 1][0]
            new_rank_actions = 0
            promoted         = True

    async with mdb() as db:
        await db.execute(
            "INSERT OR REPLACE INTO mod_ranks "
            "(telegram_id, rank, total_actions, rank_actions, updated_at) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, new_rank, new_total, new_rank_actions, now())
        )
        await db.commit()

    return new_rank if promoted else None

async def set_mod_rank_by_admin(telegram_id: int, new_rank: str) -> bool:
    if new_rank not in RANK_EMOJI:
        return False
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT total_actions FROM mod_ranks WHERE telegram_id=?", (telegram_id,)
            )
            row   = await cur.fetchone()
            total = row["total_actions"] if row else 0
            await db.execute(
                "INSERT OR REPLACE INTO mod_ranks "
                "(telegram_id, rank, total_actions, rank_actions, updated_at) VALUES (?, ?, ?, 0, ?)",
                (telegram_id, new_rank, total, now())
            )
            await db.commit()
        return True
    except Exception:
        return False

async def get_top_moderators(limit: int = 10):
    async with mdb() as db:
        cur = await db.execute(
            "SELECT telegram_id, rank, total_actions FROM mod_ranks "
            "ORDER BY total_actions DESC LIMIT ?", (limit,)
        )
        return await cur.fetchall()

# ============================================
#         БД ОПЕРАЦИИ — КАНАЛЫ / ЭКСПОРТ
# ============================================

async def db_get_channels() -> list:
    try:
        async with mdb() as db:
            cur = await db.execute("SELECT * FROM required_channels WHERE active=1")
            return await cur.fetchall()
    except Exception:
        return []

async def db_add_channel(channel_id: str, url: str, title: str) -> bool:
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT OR REPLACE INTO required_channels (channel_id, channel_url, title, active) "
                "VALUES (?, ?, ?, 1)",
                (channel_id, url, title)
            )
            await db.commit()
        return True
    except Exception:
        return False

async def db_delete_channel(channel_id: str) -> bool:
    try:
        async with mdb() as db:
            cur = await db.execute("DELETE FROM required_channels WHERE channel_id=?", (channel_id,))
            await db.commit()
        return cur.rowcount > 0
    except Exception:
        return False

async def db_get_all_users() -> list:
    try:
        async with mdb() as db:
            cur = await db.execute("SELECT telegram_id FROM bot_users")
            return await cur.fetchall()
    except Exception:
        return []

async def db_export_csv() -> bytes:
    async with mdb() as db:
        cur = await db.execute(
            "SELECT telegram_id, username, status, reason, evidence, added_by, added_at "
            "FROM users ORDER BY added_at DESC"
        )
        rows = await cur.fetchall()
    buf    = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["telegram_id", "username", "status", "reason", "evidence", "added_by", "added_at"])
    for row in rows:
        writer.writerow([row["telegram_id"], row["username"], row["status"],
                         row["reason"], row["evidence"], row["added_by"], row["added_at"]])
    return buf.getvalue().encode("utf-8-sig")

async def db_clear(target: str):
    tables = {"reports": "reports", "users": "users", "history": "check_history"}
    async with mdb() as db:
        if target == "all":
            for t in tables.values():
                await db.execute(f"DELETE FROM {t}")
        elif target in tables:
            await db.execute(f"DELETE FROM {tables[target]}")
        await db.commit()

# ============================================
#         ДИЗАЙН
# ============================================

async def get_banner(name: str) -> Optional[str]:
    try:
        async with ddb() as db:
            cur = await db.execute("SELECT file_id FROM banners WHERE name=?", (name,))
            row = await cur.fetchone()
        return row["file_id"] if row else None
    except Exception:
        return None

async def get_text(name: str) -> str:
    try:
        async with ddb() as db:
            cur = await db.execute("SELECT content FROM texts WHERE name=?", (name,))
            row = await cur.fetchone()
        return row["content"] if row else DEFAULT_TEXTS.get(name, "")
    except Exception:
        return DEFAULT_TEXTS.get(name, "")

# ============================================
#         ПРОВЕРКА ПОДПИСКИ
# ============================================

async def check_unsubscribed(bot: Bot, user_id: int) -> List[dict]:
    channels      = await db_get_channels()
    unsubscribed  = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked", "banned"):
                unsubscribed.append(dict(ch))
        except Exception:
            unsubscribed.append(dict(ch))
    return unsubscribed

async def subscription_gate(message: Message) -> bool:
    if await get_role(message.from_user.id) is not None:
        return True
    unsubscribed = await check_unsubscribed(message.bot, message.from_user.id)
    if not unsubscribed:
        return True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch["channel_url"])]
        for ch in unsubscribed
    ] + [[InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="sub_check")]])
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n👋 Для доступа подпишитесь на каналы:\n\n{DIVIDER}\n{FOOTER}",
        parse_mode="Markdown", reply_markup=kb
    )
    return False

# ============================================
#         КЛАВИАТУРЫ
# ============================================

def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔎 ПРОВЕРИТЬ"), KeyboardButton(text="📜 ИСТОРИЯ")],
            [KeyboardButton(text="🚨 ПОЖАЛОВАТЬСЯ"), KeyboardButton(text="⚖️ АПЕЛЛЯЦИЯ")],
            [KeyboardButton(text="📱 MINI APP", web_app=WebAppInfo(url=MINI_APP_URL))],
        ],
        resize_keyboard=True,
        input_field_placeholder="Введите @username или ID..."
    )

def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔎 ПРОВЕРИТЬ"), KeyboardButton(text="📜 ИСТОРИЯ")],
            [KeyboardButton(text="📈 СТАТИСТИКА"), KeyboardButton(text="🗑 СБРОС")],
            [KeyboardButton(text="📱 MINI APP", web_app=WebAppInfo(url=MINI_APP_URL))],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите операцию..."
    )

def other_bases_keyboard(identifier: str) -> InlineKeyboardMarkup:
    items = list(OTHER_BOTS.items())
    rows  = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(
                text=f"🔍 {name}",
                url=f"https://t.me/{username}?start=check_{identifier}"
            )
            for name, username in items[i:i+2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def report_types_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 СКАМ",        callback_data="rt:scam"),
         InlineKeyboardButton(text="⚡ ПОДОЗРИТ.",   callback_data="rt:suspicious")],
        [InlineKeyboardButton(text="💸 НЕВОЗВРАТ",   callback_data="rt:money"),
         InlineKeyboardButton(text="🤖 ФЕЙК",        callback_data="rt:fake")],
        [InlineKeyboardButton(text="❌ ОТМЕНА",       callback_data="report:cancel")],
    ])

def reset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📛 ЖАЛОБЫ",   callback_data="reset:reports"),
         InlineKeyboardButton(text="👥 БАЗУ",      callback_data="reset:users")],
        [InlineKeyboardButton(text="📜 ИСТОРИЮ",   callback_data="reset:history"),
         InlineKeyboardButton(text="🗄 ВСЁ",       callback_data="reset:all")],
        [InlineKeyboardButton(text="❌ ОТМЕНА",    callback_data="reset:cancel")],
    ])

def statuses_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Скамер",      callback_data="adm_s:scammer"),
         InlineKeyboardButton(text="💎 Гарант",      callback_data="adm_s:guarantor"),
         InlineKeyboardButton(text="🫧 Доверенный",  callback_data="adm_s:trusted")],
        [InlineKeyboardButton(text="❌ Отмена",      callback_data="adm_s:cancel")],
    ])

def pending_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять",   callback_data=f"pnd:approve:{report_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pnd:reject:{report_id}")],
        [InlineKeyboardButton(text="⏩ Следующая", callback_data=f"pnd:next:{report_id}")],
    ])

def cons_reviewer_keyboard(cons_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять",         callback_data=f"cons:ok:{cons_id}"),
         InlineKeyboardButton(text="❌ Отклонить",       callback_data=f"cons:no:{cons_id}")],
        [InlineKeyboardButton(text="🔄 Переписать заново", callback_data=f"cons:redo:{cons_id}")],
    ])

def cons_mod_keyboard(cons_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять в базу", callback_data=f"modcons:approve:{cons_id}"),
         InlineKeyboardButton(text="❌ Отклонить",      callback_data=f"modcons:reject:{cons_id}")],
    ])

def cons_user_keyboard(cons_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Моя жалоба",    callback_data=f"cshow:{cons_id}"),
         InlineKeyboardButton(text="✏️ Написать заново", callback_data=f"cnew:{cons_id}")],
    ])

def staff_roles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Администратор",  callback_data="sr:admin"),
         InlineKeyboardButton(text="💎 Гарант",         callback_data="sr:guarantor")],
        [InlineKeyboardButton(text="🔍 Рассмотритель",  callback_data="sr:reviewer"),
         InlineKeyboardButton(text="🔨 Модератор",      callback_data="sr:moderator")],
        [InlineKeyboardButton(text="❌ Отмена",         callback_data="sr:cancel")],
    ])

def channels_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить",  callback_data="chan:add"),
         InlineKeyboardButton(text="🗑 Удалить",   callback_data="chan:del")],
        [InlineKeyboardButton(text="📋 Список",    callback_data="chan:list"),
         InlineKeyboardButton(text="❌ Закрыть",   callback_data="chan:close")],
    ])

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 ОТМЕНА", callback_data="cancel_action")],
    ])

# --- Апелляции ---

def appeal_reviewer_keyboard(appeal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить",    callback_data=f"aprev:ok:{appeal_id}"),
         InlineKeyboardButton(text="❌ Отклонить",  callback_data=f"aprev:no:{appeal_id}")],
        [InlineKeyboardButton(text="⏩ Следующая",  callback_data=f"aprev:next:{appeal_id}")],
    ])

def appeal_mod_keyboard(appeal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Удалить из базы",   callback_data=f"apmod:approve:{appeal_id}"),
         InlineKeyboardButton(text="❌ Оставить в базе",  callback_data=f"apmod:reject:{appeal_id}")],
    ])

# ============================================
#         FSM СОСТОЯНИЯ
# ============================================

class CheckState(StatesGroup):
    waiting = State()

class ReportState(StatesGroup):
    target      = State()
    report_type = State()
    description = State()
    evidence    = State()

class ConsState(StatesGroup):
    collecting = State()

class AppealState(StatesGroup):
    target      = State()
    reason      = State()
    evidence    = State()

class AdminAddState(StatesGroup):
    target   = State()
    status   = State()
    reason   = State()
    evidence = State()

class AdminDeleteState(StatesGroup):
    target = State()

class StaffAddState(StatesGroup):
    target = State()
    role   = State()

class StaffDeleteState(StatesGroup):
    target = State()

class ChannelAddState(StatesGroup):
    channel_id = State()
    url        = State()
    title      = State()

class ChannelDeleteState(StatesGroup):
    channel_id = State()

class BroadcastState(StatesGroup):
    text = State()

# ============================================
#         ФИЛЬТРЫ
# ============================================

class IsStaffFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await get_role(user.id) is not None

class IsHeadAdminFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await get_role(user.id) == "head_admin"

# ============================================
#         ОТПРАВКА С БАННЕРОМ
# ============================================

async def send_with_banner(message: Message, banner_name: str, text: str, **kwargs):
    file_id = await get_banner(banner_name)
    if file_id:
        try:
            return await message.answer_animation(
                animation=file_id, caption=text, parse_mode="Markdown", **kwargs
            )
        except Exception:
            pass
    return await message.answer(text, parse_mode="Markdown", **kwargs)

# ============================================
#         HTTP API
# ============================================

async def verify_api_token(request: web.Request) -> bool:
    return request.headers.get("Authorization", "") == f"Bearer {API_SECRET}"

async def api_get_stats(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    stats         = await get_all_stats()
    total_users   = await db_count("users")
    scammers      = await db_count("users", "status='scammer'")
    guarantors    = await db_count("users", "status='guarantor'")
    trusted       = await db_count("users", "status='trusted'")
    pending_rep   = await db_count("reports", "status='pending'")
    pending_cons  = await db_count("cons_reports", "status='pending_review'")
    pending_ap    = await db_count("appeals", "status='pending'")
    waiting_ap    = await db_count("appeals", "status='reviewer_approved'")
    return web.json_response({
        "total_users": total_users, "scammers": scammers,
        "guarantors": guarantors, "trusted": trusted,
        "pending_reports": pending_rep, "pending_cons": pending_cons,
        "pending_appeals": pending_ap, "waiting_appeals": waiting_ap,
        **stats,
    })

async def api_get_top_moderators(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    top = await get_top_moderators(50)
    return web.json_response([
        {"telegram_id": r["telegram_id"], "rank": r["rank"], "total_actions": r["total_actions"]}
        for r in top
    ])

async def api_get_pending_cons(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    pending = await db_pending_cons(20)
    return web.json_response([
        {"id": r["id"], "reporter_id": r["reporter_id"],
         "message_text": r["message_text"][:500],
         "has_media": bool(r["media_file_id"]), "created_at": r["created_at"]}
        for r in pending
    ])

async def api_get_cons_detail(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    cons_id = int(request.match_info.get("cons_id", 0))
    row = await db_get_cons(cons_id)
    if not row:
        return web.json_response({"error": "Not found"}, status=404)
    return web.json_response(dict(row))

async def api_moderate_cons(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data         = await request.json()
        cons_id      = data.get("cons_id")
        action       = data.get("action")
        moderator_id = data.get("moderator_id")
        if not cons_id or action not in ("approve", "reject"):
            return web.json_response({"error": "Invalid data"}, status=400)
        row = await db_get_cons(cons_id)
        if not row:
            return web.json_response({"error": "Not found"}, status=404)
        if action == "approve":
            match  = re.search(r"(@\w+|\d{5,15})", row["message_text"])
            target = match.group(1) if match else f"cons_{cons_id}"
            await db_add_user(target, None, "scammer",
                              f"Жалоба #{cons_id}: {row['message_text'][:200]}",
                              None, str(moderator_id))
            await db_update_cons_status(cons_id, "moderated_approved")
        else:
            await db_update_cons_status(cons_id, "moderated_rejected")
        await update_mod_rank(moderator_id, 1)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_search_db(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    query = request.rel_url.query.get("q", "").strip().lstrip("@").lower()
    if not query:
        return web.json_response({"error": "No query"}, status=400)
    try:
        async with mdb() as db:
            cur = await db.execute(
                "SELECT * FROM users WHERE LOWER(telegram_id) LIKE ? OR LOWER(username) LIKE ? LIMIT 20",
                (f"%{query}%", f"%{query}%")
            )
            rows = await cur.fetchall()
        return web.json_response([dict(r) for r in rows])
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_get_pending_appeals(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    stage   = request.rel_url.query.get("stage", "pending")
    appeals = await db_pending_appeals(stage, 20)
    return web.json_response([dict(r) for r in appeals])

async def api_get_design(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    async with ddb() as db:
        cur  = await db.execute("SELECT name, file_id, file_type FROM banners")
        rows = await cur.fetchall()
        banners = {r["name"]: {"file_id": r["file_id"], "file_type": r["file_type"]} for r in rows}
        cur  = await db.execute("SELECT name, content FROM texts")
        rows = await cur.fetchall()
        texts = {r["name"]: r["content"] for r in rows}
    return web.json_response({"banners": banners, "texts": texts})

async def api_update_banner(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data      = await request.json()
        name      = data.get("name")
        file_id   = data.get("file_id")
        file_type = data.get("file_type", "gif")
        async with ddb() as db:
            await db.execute(
                "INSERT OR REPLACE INTO banners (name, file_id, file_type, updated_at) VALUES (?, ?, ?, ?)",
                (name, file_id, file_type, now())
            )
            await db.commit()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_update_text(request: web.Request):
    if not await verify_api_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data    = await request.json()
        name    = data.get("name")
        content = data.get("content", "")
        async with ddb() as db:
            if not content or not content.strip():
                await db.execute("DELETE FROM texts WHERE name=?", (name,))
            else:
                await db.execute(
                    "INSERT OR REPLACE INTO texts (name, content, updated_at) VALUES (?, ?, ?)",
                    (name, content, now())
                )
            await db.commit()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_api_server():
    app = web.Application()
    app.router.add_get("/api/stats",              api_get_stats)
    app.router.add_get("/api/moderators/top",     api_get_top_moderators)
    app.router.add_get("/api/cons/pending",       api_get_pending_cons)
    app.router.add_get("/api/cons/{cons_id}",     api_get_cons_detail)
    app.router.add_post("/api/cons/moderate",     api_moderate_cons)
    app.router.add_get("/api/search",             api_search_db)
    app.router.add_get("/api/appeals/pending",    api_get_pending_appeals)
    app.router.add_get("/api/design",             api_get_design)
    app.router.add_post("/api/design/banner",     api_update_banner)
    app.router.add_post("/api/design/text",       api_update_text)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", API_PORT).start()
    log.info(f"✅ API запущен на порту {API_PORT}")

# ============================================
#         РОУТЕР
# ============================================

router = Router()

# ---------- СТАРТ ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    await state.clear()
    await db_register_user(message.from_user)
    if not await subscription_gate(message):
        return
    role = await get_role(message.from_user.id)
    text = await get_text("welcome_admin" if role else "welcome_user")
    kb   = admin_keyboard() if role else user_keyboard()
    await send_with_banner(message, "start", text, reply_markup=kb)

@router.callback_query(F.data == "sub_check")
async def sub_check_callback(callback: CallbackQuery):
    if await check_unsubscribed(callback.message.bot, callback.from_user.id):
        await callback.answer("❌ Вы ещё не подписались на все каналы!", show_alert=True)
        return
    await callback.message.delete()
    role = await get_role(callback.from_user.id)
    text = await get_text("welcome_admin" if role else "welcome_user")
    kb   = admin_keyboard() if role else user_keyboard()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer("✅ Добро пожаловать!")

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    fsm_cancel(callback.from_user.id)
    await state.clear()
    await callback.answer("🚫 Действие отменено")
    try:
        await callback.message.delete()
    except Exception:
        pass
    role = await get_role(callback.from_user.id)
    text = await get_text("welcome_admin" if role else "welcome_user")
    kb   = admin_keyboard() if role else user_keyboard()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

# ---------- ПРОВЕРКА ----------

@router.message(Command("check"))
async def cmd_check(message: Message, state: FSMContext):
    await state.clear()
    if not await subscription_gate(message):
        return
    if not await rate_ok(message.from_user.id):
        await message.answer(f"⚡ Подождите {RATE_LIMIT_SECONDS} сек.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❓ Формат: `/check @username` или `/check 123456`", parse_mode="Markdown")
        return
    identifier = validate_identifier(parts[1])
    if not identifier:
        await message.answer("❌ Неверный формат!")
        return
    asyncio.create_task(run_check(message, identifier))

@router.message(F.text == "🔎 ПРОВЕРИТЬ")
async def button_check(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    await state.clear()
    if not await subscription_gate(message):
        return
    if not await rate_ok(message.from_user.id):
        await message.answer(f"⚡ Подождите {RATE_LIMIT_SECONDS} сек.")
        return
    await message.answer("🔎 Введите @username или ID для проверки:")
    await state.set_state(CheckState.waiting)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(CheckState.waiting)
async def check_input(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    identifier = validate_identifier(message.text or "")
    if not identifier:
        await message.answer("❌ Неверный формат! Пример: @username или 123456789")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.clear()
    asyncio.create_task(run_check(message, identifier))

async def run_check(message: Message, identifier: str):
    try:
        await inc_stat("checks")
        loading_text = await get_text("check_start")
        loading_text += f"🎯 Цель: `{identifier}`\n\n{bar(0)}"
        status_msg = await message.answer(loading_text, parse_mode="Markdown")

        for percent in (25, 50, 75, 100):
            await asyncio.sleep(0.3)
            t = await get_text("check_start")
            t += f"🎯 Цель: `{identifier}`\n\n{bar(percent)}"
            try:
                await status_msg.edit_text(t, parse_mode="Markdown")
            except Exception:
                pass

        # Проверяем: является ли целью сотрудник
        staff_role = None
        if identifier.isdigit():
            staff_role = await get_role(int(identifier))
        else:
            async with mdb() as db:
                cur = await db.execute(
                    "SELECT telegram_id, role FROM staff WHERE LOWER(username)=?",
                    (identifier.lower(),)
                )
                row = await cur.fetchone()
            if row:
                staff_role = row["role"]

        user_row = await db_get_user(identifier)

        if staff_role:
            await inc_stat("clean")
            role_label  = ROLE_LABELS.get(staff_role, staff_role)
            result_text = (
                f"{HEADER}\n{DIVIDER}\n\n"
                f"🛡️ *ПРОВЕРКА ЗАВЕРШЕНА*\n\n"
                f"🆔 `{identifier}`\n\n"
                f"{LINE}\n👑 Это {role_label} системы ARION!\n{LINE}\n\n"
                f"🔒 Верифицирован системой *ARION*\n"
            )
            if staff_role in ("moderator", "reviewer"):
                tid = int(identifier) if identifier.isdigit() else 0
                rank, total_actions, _ = await get_mod_rank(tid)
                if rank:
                    emoji = RANK_EMOJI.get(rank, "🏅")
                    result_text += f"\n🏅 *Ранг:* {emoji} {rank} (действий: {total_actions})"
            result_text += f"\n\n{DIVIDER}\n{FOOTER}"
            await db_add_history(str(message.from_user.id), identifier, "clean")

        elif user_row:
            await inc_stat("found")
            status = user_row["status"]
            emoji  = STATUS_EMOJI.get(status, "🔥")
            tag    = f"@{user_row['username']}" if user_row["username"] else f"ID: {user_row['telegram_id']}"
            base_text   = await get_text("scammer_found")
            result_text = (
                f"{base_text}"
                f"🆔 {sanitize(tag)} | `{user_row['telegram_id']}`\n\n"
                f"{LINE}\n📋 *ДОСЬЕ:*\n«{sanitize(user_row['reason'])}»\n\n"
            )
            if user_row["evidence"]:
                result_text += f"🔗 Улики: {sanitize(user_row['evidence'])}\n"
            result_text += (
                f"📅 Внесён: {user_row['added_at']}\n{LINE}\n\n"
                f"⚡ *ВЕРДИКТ: НЕ СВЯЗЫВАТЬСЯ*\n"
                f"🚫 Все операции с данным лицом запрещены!\n\n"
                f"⚖️ Если это ошибка — используйте /appeal для подачи апелляции.\n\n"
                f"{DIVIDER}\n{FOOTER}"
            )
            await db_add_history(str(message.from_user.id), identifier, "found")

        else:
            await inc_stat("clean")
            result_text  = await get_text("user_clean")
            result_text += f"\n\n🆔 `{identifier}`\n\n{DIVIDER}\n{FOOTER}"
            await db_add_history(str(message.from_user.id), identifier, "clean")

        result_text += f"\n\n{DIVIDER}\n🔎 *ПРОВЕРИТЬ В ДРУГИХ БАЗАХ:*"
        await status_msg.edit_text(
            result_text, parse_mode="Markdown", reply_markup=other_bases_keyboard(identifier)
        )
        log.info(f"check {identifier} by {message.from_user.id}")

    except Exception as e:
        log.error(f"run_check: {e}")
        await message.answer("❌ Ошибка проверки. Попробуйте позже.")

# ---------- ЖАЛОБЫ (БЫСТРАЯ ФОРМА) ----------

@router.message(Command("report"))
@router.message(F.text == "🚨 ПОЖАЛОВАТЬСЯ")
async def start_report(message: Message, state: FSMContext):
    await state.clear()
    if not await subscription_gate(message):
        return
    role = await get_role(message.from_user.id)
    if role:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n"
            "⚠️ Сотрудники системы используют /addscam.\n\n"
            f"{FOOTER}", parse_mode="Markdown"
        )
        return
    text = await get_text("report_start")
    await message.answer(f"{text}\nВведите @username или ID нарушителя:", parse_mode="Markdown")
    await state.set_state(ReportState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(ReportState.target)
async def report_target(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    target = (message.text or "").strip().lstrip("@")
    if not target:
        await message.answer("❌ Введите ID или @username:")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(target_id=target, target_un=message.text)
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n📋 Выберите тип жалобы:",
        parse_mode="Markdown", reply_markup=report_types_keyboard()
    )
    await state.set_state(ReportState.report_type)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.callback_query(F.data.startswith("rt:"))
async def report_type_cb(callback: CallbackQuery, state: FSMContext):
    fsm_cancel(callback.from_user.id)
    type_map = {"scam": "СКАМ", "suspicious": "ПОДОЗРИТЕЛЬНО", "money": "НЕВОЗВРАТ", "fake": "ФЕЙК"}
    rtype    = type_map.get(callback.data.split(":")[1], "ДРУГОЕ")
    await state.update_data(report_type=rtype)
    await callback.message.edit_text(
        f"{HEADER}\n{DIVIDER}\n\n📝 *ОПИШИТЕ СИТУАЦИЮ*\n\n🏷 Тип: *{rtype}*\n\nМаксимум 500 символов:",
        parse_mode="Markdown"
    )
    await state.set_state(ReportState.description)
    fsm_schedule(callback.from_user.id, state, asyncio.get_event_loop())
    await callback.answer()

@router.message(ReportState.description)
async def report_description(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    desc = (message.text or "").strip()
    if not desc or len(desc) > 500:
        await message.answer("❌ От 1 до 500 символов!")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(description=desc)
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n🔗 *ДОКАЗАТЕЛЬСТВА*\n\nСсылка на скриншот/видео или «-» если нет:",
        parse_mode="Markdown"
    )
    await state.set_state(ReportState.evidence)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(ReportState.evidence)
async def report_evidence(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    evidence = (message.text or "").strip()
    data     = await state.get_data()
    await state.clear()
    report_id = await db_add_report(
        str(message.from_user.id), data.get("target_id", ""),
        data.get("target_un", ""), data.get("report_type", ""),
        data.get("description", ""), evidence if evidence != "-" else None
    )
    if not report_id:
        await message.answer("❌ Ошибка сохранения жалобы.")
        return
    await inc_stat("reports")
    text  = await get_text("report_success")
    text += f"\n\n📌 Номер жалобы: *#{report_id}*"
    await message.answer(text, parse_mode="Markdown")

@router.callback_query(F.data == "report:cancel")
async def report_cancel(callback: CallbackQuery, state: FSMContext):
    fsm_cancel(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("❌ Жалоба отменена.")
    await callback.answer()

# ---------- /cons ----------

@router.message(Command("cons"))
async def cmd_cons(message: Message, state: FSMContext):
    if message.chat.type != "private" and message.chat.id != CONS_GROUP_CHAT_ID:
        return
    await state.clear()
    if not await subscription_gate(message):
        return
    text = await get_text("cons_form")
    await message.answer(text, parse_mode="Markdown")
    await state.set_state(ConsState.collecting)
    await state.update_data(draft="", media_id=None, media_type=None)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(ConsState.collecting, Command("Not"))
async def cons_submit(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    data  = await state.get_data()
    await state.clear()
    draft = data.get("draft", "").strip()
    if not draft:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n❌ Текст жалобы пустой!\n\n{FOOTER}", parse_mode="Markdown"
        )
        return
    cons_id = await db_save_cons(str(message.from_user.id), draft, data.get("media_id"), data.get("media_type"))
    if not cons_id:
        await message.answer("❌ Ошибка сохранения.")
        return
    pending_count = await db_count("cons_reports", "status='pending_review'")
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n✅ *ЖАЛОБА ОТПРАВЛЕНА НА РАССМОТРЕНИЕ!*\n\n"
        f"📌 Номер: *#{cons_id}*\n\n🔍 Рассмотрители изучат жалобу.\n\n{DIVIDER}\n{FOOTER}",
        parse_mode="Markdown"
    )
    header_text = (
        f"{HEADER}\n{DIVIDER}\n\n📋 *{pending_count} жалоб в очереди*\n\n"
        f"🆕 *ЖАЛОБА #{cons_id}*\n👤 От: `{message.from_user.id}`"
        + (f" (@{message.from_user.username})" if message.from_user.username else "")
        + f"\n📅 {now()}\n\n{DIVIDER}\n\n📝 *ТЕКСТ:*\n\n{draft}\n\n{DIVIDER}"
    )
    kb = cons_reviewer_keyboard(cons_id)
    try:
        mid = data.get("media_id")
        mtype = data.get("media_type")
        if mid and mtype == "photo":
            await message.bot.send_photo(CONSIDERATION_CHAT_ID, photo=mid,
                                          caption=header_text, parse_mode="Markdown", reply_markup=kb)
        elif mid and mtype == "video":
            await message.bot.send_video(CONSIDERATION_CHAT_ID, video=mid,
                                          caption=header_text, parse_mode="Markdown", reply_markup=kb)
        else:
            await message.bot.send_message(CONSIDERATION_CHAT_ID, header_text,
                                            parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        log.error(f"cons send error: {e}")

@router.message(ConsState.collecting)
async def cons_collect(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    data  = await state.get_data()
    draft = data.get("draft", "")
    if message.text:
        draft = (draft + "\n" + message.text).strip()
        await state.update_data(draft=draft)
    if message.photo:
        await state.update_data(media_id=message.photo[-1].file_id, media_type="photo")
    elif message.video:
        await state.update_data(media_id=message.video.file_id, media_type="video")
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
    await message.answer("✏️ Данные сохранены. Продолжайте или отправьте */Not* для подачи.",
                         parse_mode="Markdown")

# ---------- ОБРАБОТКА /cons (РАССМОТРИТЕЛИ) ----------

@router.callback_query(F.data.startswith("cons:"))
async def cons_reviewer_action(callback: CallbackQuery):
    _, action, cons_id_str = callback.data.split(":")
    cons_id    = int(cons_id_str)
    row        = await db_get_cons(cons_id)
    if not row:
        await callback.answer("❌ Жалоба не найдена.", show_alert=True)
        return
    reporter_id   = int(row["reporter_id"])
    reviewer_name = callback.from_user.first_name or str(callback.from_user.id)

    if action == "ok":
        await db_update_cons_status(cons_id, "approved")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"✅ *Жалоба #{cons_id} принята* рассмотрителем {reviewer_name}\n📤 Отправлена на модерацию.",
            parse_mode="Markdown"
        )
        try:
            await callback.message.bot.send_message(
                reporter_id,
                f"{HEADER}\n{DIVIDER}\n\n✅ *ЖАЛОБА ПРОШЛА РАССМОТРЕНИЕ!*\n\n"
                f"📌 Номер: *#{cons_id}*\n\n{DIVIDER}\n{FOOTER}", parse_mode="Markdown"
            )
        except Exception:
            pass
        report_text = (
            f"{HEADER}\n{DIVIDER}\n\n📋 *ЖАЛОБА #{cons_id} — НА МОДЕРАЦИЮ*\n\n"
            f"👤 Отправитель: `{reporter_id}`\n✅ Принята: {reviewer_name}\n📅 {now()}\n\n"
            f"{LINE}\n\n📝 *ТЕКСТ:*\n\n{row['message_text']}\n\n{LINE}\n{FOOTER}"
        )
        try:
            await callback.message.bot.send_message(
                REPORT_CHAT_ID, report_text, parse_mode="Markdown",
                reply_markup=cons_mod_keyboard(cons_id)
            )
        except Exception as e:
            log.error(f"cons->report_chat: {e}")

    elif action == "no":
        await db_update_cons_status(cons_id, "rejected")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"❌ *Жалоба #{cons_id} отклонена* рассмотрителем {reviewer_name}", parse_mode="Markdown"
        )
        try:
            await callback.message.bot.send_message(
                reporter_id,
                f"{HEADER}\n{DIVIDER}\n\n❌ *ЖАЛОБА ОТКЛОНЕНА*\n\n"
                f"📌 Номер: *#{cons_id}*\n\nПодайте новую жалобу через /cons\n\n{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif action == "redo":
        await db_update_cons_status(cons_id, "rewrite_requested")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"🔄 *Жалоба #{cons_id} — запрошена переработка* ({reviewer_name})", parse_mode="Markdown"
        )
        try:
            await callback.message.bot.send_message(
                reporter_id,
                f"{HEADER}\n{DIVIDER}\n\n🔄 *ЖАЛОБА ТРЕБУЕТ ДОРАБОТКИ*\n\n"
                f"📌 Номер: *#{cons_id}*\n\nПерепишите и отправьте снова.\n\n{DIVIDER}",
                parse_mode="Markdown", reply_markup=cons_user_keyboard(cons_id)
            )
        except Exception:
            pass

    await callback.answer()

# ---------- ОБРАБОТКА /cons (МОДЕРАТОРЫ) ----------

@router.callback_query(F.data.startswith("modcons:"))
async def cons_moderator_action(callback: CallbackQuery):
    _, action, cons_id_str = callback.data.split(":")
    cons_id     = int(cons_id_str)
    row         = await db_get_cons(cons_id)
    if not row:
        await callback.answer("❌ Жалоба не найдена.", show_alert=True)
        return
    reporter_id = int(row["reporter_id"])

    if action == "approve":
        match  = re.search(r"(@\w+|\d{5,15})", row["message_text"])
        target = match.group(1) if match else f"cons_{cons_id}"
        await db_add_user(target, None, "scammer",
                          f"Жалоба #{cons_id}: {row['message_text'][:200]}",
                          None, str(callback.from_user.id))
        await db_update_cons_status(cons_id, "moderated_approved")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        await callback.message.edit_reply_markup(reply_markup=None)
        reply = f"✅ Жалоба #{cons_id} принята модератором {callback.from_user.first_name}."
        if new_rank:
            reply += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.reply(reply, parse_mode="Markdown")
        try:
            await callback.message.bot.send_message(
                reporter_id,
                f"{HEADER}\n{DIVIDER}\n\n✅ *ВАША ЖАЛОБА ОДОБРЕНА!*\n\n"
                f"📌 Номер: *#{cons_id}*\n\nСпасибо за вклад! 🙏\n\n{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif action == "reject":
        await db_update_cons_status(cons_id, "moderated_rejected")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        await callback.message.edit_reply_markup(reply_markup=None)
        reply = f"❌ Жалоба #{cons_id} отклонена модератором {callback.from_user.first_name}."
        if new_rank:
            reply += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.reply(reply, parse_mode="Markdown")
        try:
            await callback.message.bot.send_message(
                reporter_id,
                f"{HEADER}\n{DIVIDER}\n\n❌ *ВАША ЖАЛОБА ОТКЛОНЕНА*\n\n"
                f"📌 Номер: *#{cons_id}*\n\nПодайте новую через /cons\n\n{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data.startswith("cshow:"))
async def cons_show_original(callback: CallbackQuery):
    cons_id = int(callback.data.split(":")[1])
    row     = await db_get_cons(cons_id)
    if not row:
        await callback.answer("❌ Жалоба не найдена.", show_alert=True)
        return
    await callback.message.answer(
        f"{HEADER}\n{DIVIDER}\n\n📄 *ВАША ЖАЛОБА #{cons_id}:*\n\n"
        f"{row['message_text']}\n\n{DIVIDER}\n{FOOTER}", parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("cnew:"))
async def cons_rewrite(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = await get_text("cons_form")
    await callback.message.answer(text, parse_mode="Markdown")
    await state.set_state(ConsState.collecting)
    await state.update_data(draft="", media_id=None, media_type=None)
    fsm_schedule(callback.from_user.id, state, asyncio.get_event_loop())
    await callback.answer()

# ============================================
#         СИСТЕМА АПЕЛЛЯЦИЙ
# ============================================

@router.message(Command("appeal"))
@router.message(F.text == "⚖️ АПЕЛЛЯЦИЯ")
async def cmd_appeal(message: Message, state: FSMContext):
    await state.clear()
    if not await subscription_gate(message):
        return

    # Сотрудники не могут подавать апелляции
    role = await get_role(message.from_user.id)
    if role:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n⚠️ Сотрудники не могут подавать апелляции.\n\n{FOOTER}",
            parse_mode="Markdown"
        )
        return

    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *ПОДАЧА АПЕЛЛЯЦИИ*\n\n"
        f"Апелляция — это запрос на пересмотр вашей записи в базе.\n\n"
        f"📋 *ТРЕБОВАНИЯ:*\n"
        f"• Необходимо предоставить доказательства\n"
        f"• Апелляция рассматривается рассмотрителем, затем модератором\n"
        f"• Ложные апелляции могут повлечь последствия\n\n"
        f"{DIVIDER}\n\n"
        f"Введите ваш *@username или ID* (тот, что занесён в базу):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AppealState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AppealState.target)
async def appeal_target(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    target = validate_identifier(message.text or "")
    if not target:
        await message.answer("❌ Неверный формат! Введите @username или ID:")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return

    # Проверяем — есть ли цель в базе
    user_row = await db_get_user(target)
    if not user_row:
        await state.clear()
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n"
            f"⚠️ *ЗАПИСЬ НЕ НАЙДЕНА*\n\n"
            f"`{target}` не найден в базе.\n\n"
            f"{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
        return

    # Проверяем — нет ли уже открытой апелляции
    if await db_check_open_appeal(target):
        await state.clear()
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n"
            f"⏳ *АПЕЛЛЯЦИЯ УЖЕ ПОДАНА*\n\n"
            f"По записи `{target}` уже есть активная апелляция на рассмотрении.\n\n"
            f"{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
        return

    await state.update_data(target_id=target)
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *АПЕЛЛЯЦИЯ*\n\n"
        f"🎯 Запись: `{target}`\n"
        f"📋 Причина внесения: *{sanitize(user_row['reason'])}*\n\n"
        f"{DIVIDER}\n\n"
        f"📝 Опишите подробно *почему запись ошибочна* (до 1000 символов):\n"
        f"Укажите факты, хронологию событий, что произошло на самом деле.",
        parse_mode="Markdown"
    )
    await state.set_state(AppealState.reason)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AppealState.reason)
async def appeal_reason(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    reason = (message.text or "").strip()
    if len(reason) < 30:
        await message.answer("❌ Слишком коротко! Опишите ситуацию подробнее (минимум 30 символов):")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    if len(reason) > 1000:
        await message.answer("❌ Максимум 1000 символов!")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(reason=reason)
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"🔗 *ДОКАЗАТЕЛЬСТВА*\n\n"
        f"Прикрепите ссылки на доказательства (скриншоты, переписки).\n\n"
        f"⚠️ Апелляции *без доказательств* имеют меньше шансов на одобрение.\n\n"
        f"Введите ссылки через запятую или «-» если нет:",
        parse_mode="Markdown"
    )
    await state.set_state(AppealState.evidence)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AppealState.evidence)
async def appeal_evidence(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    evidence = (message.text or "").strip()
    data     = await state.get_data()
    await state.clear()

    target    = data.get("target_id", "")
    reason    = data.get("reason", "")
    ev_saved  = evidence if evidence != "-" else None
    username  = message.from_user.username or ""

    appeal_id = await db_create_appeal(
        str(message.from_user.id), username, target, reason, ev_saved
    )
    if not appeal_id:
        await message.answer("❌ Ошибка сохранения апелляции.")
        return

    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"✅ *АПЕЛЛЯЦИЯ ПОДАНА!*\n\n"
        f"📌 Номер: *#{appeal_id}*\n\n"
        f"🔍 Рассмотрители изучат вашу апелляцию.\n"
        f"📬 Вы получите уведомление о решении.\n\n"
        f"⏱ Средний срок рассмотрения: 24–72 часа\n\n"
        f"{DIVIDER}\n{FOOTER}",
        parse_mode="Markdown"
    )
    log.info(f"appeal #{appeal_id} from {message.from_user.id} target={target}")

    # Отправляем в чат рассмотрителей
    appeal_text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *НОВАЯ АПЕЛЛЯЦИЯ #{appeal_id}*\n\n"
        f"👤 Заявитель: `{message.from_user.id}`"
        + (f" (@{username})" if username else "") +
        f"\n🎯 Запись: `{target}`\n"
        f"📅 {now()}\n\n{LINE}\n\n"
        f"📝 *ОБОСНОВАНИЕ:*\n\n{sanitize(reason)}\n\n"
    )
    if ev_saved:
        appeal_text += f"🔗 *Доказательства:* {sanitize(ev_saved)}\n\n"
    appeal_text += f"{LINE}\n{FOOTER}"

    try:
        chat_id = APPEAL_CHAT_ID if APPEAL_CHAT_ID else CONSIDERATION_CHAT_ID
        await message.bot.send_message(
            chat_id, appeal_text,
            parse_mode="Markdown",
            reply_markup=appeal_reviewer_keyboard(appeal_id)
        )
    except Exception as e:
        log.error(f"appeal send error: {e}")

# ---------- РАССМОТРЕНИЕ АПЕЛЛЯЦИЙ (РАССМОТРИТЕЛИ) ----------

@router.callback_query(F.data.startswith("aprev:"))
async def appeal_reviewer_action(callback: CallbackQuery):
    parts     = callback.data.split(":")
    action    = parts[1]
    appeal_id = int(parts[2])
    row       = await db_get_appeal(appeal_id)
    if not row:
        await callback.answer("❌ Апелляция не найдена.", show_alert=True)
        return

    rev_name    = callback.from_user.first_name or str(callback.from_user.id)
    appellant_id = int(row["appellant_id"])

    if action == "ok":
        await db_update_appeal(appeal_id, status="reviewer_approved",
                               reviewer_id=str(callback.from_user.id))
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"✅ *Апелляция #{appeal_id}* одобрена рассмотрителем {rev_name}\n📤 Отправлена модератору.",
            parse_mode="Markdown"
        )
        try:
            await callback.message.bot.send_message(
                appellant_id,
                f"{HEADER}\n{DIVIDER}\n\n"
                f"🔍 *АПЕЛЛЯЦИЯ ПРОШЛА РАССМОТРЕНИЕ*\n\n"
                f"📌 Номер: *#{appeal_id}*\n\n"
                f"Рассмотритель одобрил вашу апелляцию.\n"
                f"Теперь её изучит модератор.\n\n{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # Отправляем модераторам
        mod_text = (
            f"{HEADER}\n{DIVIDER}\n\n"
            f"⚖️ *АПЕЛЛЯЦИЯ #{appeal_id} — НА МОДЕРАЦИЮ*\n\n"
            f"👤 Заявитель: `{row['appellant_id']}`"
            + (f" (@{row['appellant_username']})" if row["appellant_username"] else "")
            + f"\n🎯 Запись: `{row['target_id']}`\n"
            f"✅ Рассмотритель: {rev_name}\n📅 {now()}\n\n{LINE}\n\n"
            f"📝 *ОБОСНОВАНИЕ:*\n\n{sanitize(row['reason'])}\n\n"
        )
        if row["evidence"]:
            mod_text += f"🔗 *Доказательства:* {sanitize(row['evidence'])}\n\n"
        mod_text += f"{LINE}\n{FOOTER}"

        try:
            await callback.message.bot.send_message(
                REPORT_CHAT_ID, mod_text,
                parse_mode="Markdown",
                reply_markup=appeal_mod_keyboard(appeal_id)
            )
        except Exception as e:
            log.error(f"appeal->mod: {e}")

    elif action == "no":
        await db_update_appeal(appeal_id, status="rejected",
                               reviewer_id=str(callback.from_user.id),
                               reviewer_note="Отклонено рассмотрителем")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"❌ *Апелляция #{appeal_id}* отклонена рассмотрителем {rev_name}", parse_mode="Markdown"
        )
        try:
            await callback.message.bot.send_message(
                appellant_id,
                f"{HEADER}\n{DIVIDER}\n\n"
                f"❌ *АПЕЛЛЯЦИЯ ОТКЛОНЕНА*\n\n"
                f"📌 Номер: *#{appeal_id}*\n\n"
                f"Рассмотритель отклонил вашу апелляцию.\n"
                f"Для повторной подачи необходимы новые доказательства.\n\n"
                f"{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await inc_stat("appeals_rejected")

    elif action == "next":
        rows      = await db_pending_appeals("pending", 5)
        next_row  = next((r for r in rows if r["id"] != appeal_id), None)
        if next_row:
            await callback.message.delete()
            await send_appeal_to_chat(callback.message, next_row)
        else:
            await callback.message.edit_text(
                f"{HEADER}\n{DIVIDER}\n\n✨ Апелляций больше нет!\n\n{FOOTER}", parse_mode="Markdown"
            )

    await callback.answer()

async def send_appeal_to_chat(message: Message, row):
    text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *АПЕЛЛЯЦИЯ #{row['id']}*\n\n"
        f"👤 `{row['appellant_id']}`\n🎯 Запись: `{row['target_id']}`\n📅 {row['created_at']}\n\n"
        f"{LINE}\n\n📝 {sanitize(row['reason'])}\n\n{LINE}"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=appeal_reviewer_keyboard(row["id"]))

# ---------- РАССМОТРЕНИЕ АПЕЛЛЯЦИЙ (МОДЕРАТОРЫ) ----------

@router.callback_query(F.data.startswith("apmod:"))
async def appeal_mod_action(callback: CallbackQuery):
    parts     = callback.data.split(":")
    action    = parts[1]
    appeal_id = int(parts[2])
    row       = await db_get_appeal(appeal_id)
    if not row:
        await callback.answer("❌ Апелляция не найдена.", show_alert=True)
        return

    mod_name     = callback.from_user.first_name or str(callback.from_user.id)
    appellant_id = int(row["appellant_id"])

    if action == "approve":
        # Удаляем запись из базы
        deleted = await db_delete_user(row["target_id"], str(callback.from_user.id))
        await db_update_appeal(appeal_id, status="approved",
                               moderator_id=str(callback.from_user.id),
                               moderator_note="Запись удалена из базы")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        await inc_stat("appeals_approved")

        await callback.message.edit_reply_markup(reply_markup=None)
        reply = (
            f"✅ Апелляция #{appeal_id} *ОДОБРЕНА* модератором {mod_name}.\n"
            f"{'🗑 Запись удалена из базы.' if deleted else '⚠️ Запись не найдена (возможно уже удалена).'}"
        )
        if new_rank:
            reply += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.reply(reply, parse_mode="Markdown")

        try:
            await callback.message.bot.send_message(
                appellant_id,
                f"{HEADER}\n{DIVIDER}\n\n"
                f"🎉 *АПЕЛЛЯЦИЯ ОДОБРЕНА!*\n\n"
                f"📌 Номер: *#{appeal_id}*\n\n"
                f"✅ Модератор принял решение удалить запись из базы.\n"
                f"Вы больше не числитесь в базе ARION.\n\n"
                f"{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        log.info(f"appeal #{appeal_id} approved by {callback.from_user.id}, target={row['target_id']}")

    elif action == "reject":
        await db_update_appeal(appeal_id, status="rejected",
                               moderator_id=str(callback.from_user.id),
                               moderator_note="Отклонено модератором, запись оставлена")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        await inc_stat("appeals_rejected")

        await callback.message.edit_reply_markup(reply_markup=None)
        reply = f"❌ Апелляция #{appeal_id} *отклонена* модератором {mod_name}. Запись оставлена."
        if new_rank:
            reply += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.reply(reply, parse_mode="Markdown")

        try:
            await callback.message.bot.send_message(
                appellant_id,
                f"{HEADER}\n{DIVIDER}\n\n"
                f"❌ *АПЕЛЛЯЦИЯ ОТКЛОНЕНА*\n\n"
                f"📌 Номер: *#{appeal_id}*\n\n"
                f"Модератор изучил доказательства и принял решение оставить запись.\n\n"
                f"Если у вас появились новые доказательства — вы можете подать новую апелляцию через /appeal\n\n"
                f"{DIVIDER}\n{FOOTER}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await callback.answer()

# ---------- КОМАНДА /pending_appeals ----------

@router.message(Command("pending_appeals"), IsStaffFilter())
async def cmd_pending_appeals(message: Message):
    role = await get_role(message.from_user.id)
    if role not in ("reviewer", "moderator", "admin", "head_admin"):
        await message.answer("❌ Нет доступа.")
        return

    # Рассмотрители видят новые апелляции, модераторы — одобренные рассмотрителями
    if role in ("reviewer", "admin", "head_admin"):
        rows  = await db_pending_appeals("pending", 1)
        stage = "pending"
    else:
        rows  = await db_pending_appeals("reviewer_approved", 1)
        stage = "reviewer_approved"

    if not rows:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✨ Апелляций нет!\n\n{DIVIDER}\n{FOOTER}", parse_mode="Markdown"
        )
        return

    row  = rows[0]
    text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *АПЕЛЛЯЦИЯ #{row['id']}*\n\n"
        f"👤 Заявитель: `{row['appellant_id']}`"
        + (f" (@{row['appellant_username']})" if row["appellant_username"] else "")
        + f"\n🎯 Запись: `{row['target_id']}`\n"
        f"📅 {row['created_at']}\n\n{LINE}\n\n"
        f"📝 *ОБОСНОВАНИЕ:*\n\n{sanitize(row['reason'])}\n\n"
    )
    if row["evidence"]:
        text += f"🔗 *Доказательства:* {sanitize(row['evidence'])}\n\n"
    text += f"{LINE}"

    kb = appeal_reviewer_keyboard(row["id"]) if stage == "pending" else appeal_mod_keyboard(row["id"])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

# ---------- АДМИН-ЦЕНТР ----------

@router.message(Command("admin"), IsStaffFilter())
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    role       = await get_role(message.from_user.id)
    role_label = ROLE_LABELS.get(role, role)
    total      = await db_count("users")
    p_reports  = await db_count("reports", "status='pending'")
    p_cons     = await db_count("cons_reports", "status='pending_review'")
    p_appeals  = await db_count("appeals", "status='pending'")
    w_appeals  = await db_count("appeals", "status='reviewer_approved'")
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"🛠 *АДМИН-ЦЕНТР*\n\n"
        f"👤 Роль: *{role_label}*\n\n"
        f"👥 В базе: `{total}`\n"
        f"🆕 Жалоб (report): `{p_reports}`\n"
        f"📝 Жалоб (cons): `{p_cons}`\n"
        f"⚖️ Апелляций (новых): `{p_appeals}`\n"
        f"⚖️ Апелляций (у модераторов): `{w_appeals}`\n\n"
        f"{DIVIDER}\n\n📋 *КОМАНДЫ:*\n\n"
        f"/addscam — ➕ добавить в базу\n"
        f"/delscam — 🗑 удалить из базы\n"
        f"/addstaff — 👤 добавить сотрудника\n"
        f"/delstaff — ❌ удалить сотрудника\n"
        f"/pending — 📋 жалобы\n"
        f"/pending_appeals — ⚖️ апелляции\n"
        f"/channels — 📢 каналы подписки\n"
        f"/export — 📊 экспорт CSV\n"
        f"/broadcast — 📢 рассылка\n"
        f"/myrank — 🏅 мой ранг\n"
        f"/modstop — 🏆 топ модераторов\n"
        f"/setrank — 👑 установить ранг\n",
        parse_mode="Markdown"
    )

# ---------- РАНГИ ----------

@router.message(Command("myrank"), IsStaffFilter())
async def cmd_myrank(message: Message):
    role = await get_role(message.from_user.id)
    if role not in ("moderator", "reviewer", "admin", "head_admin"):
        await message.answer("❌ Только для сотрудников.")
        return
    rank, total, rank_actions = await get_mod_rank(message.from_user.id)
    need      = next((r for rn, r in MOD_RANKS if rn == rank), 0)
    emoji     = RANK_EMOJI.get(rank, "🏅")
    remaining = max(0, need - rank_actions)
    text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"{emoji} *ВАШ РАНГ* {emoji}\n\n"
        f"🏷 Ранг: *{rank}*\n"
        f"📊 Всего обработано: `{total}`\n"
        f"📈 В текущем ранге: `{rank_actions}` / `{need if need > 0 else '∞'}`\n"
    )
    if need > 0 and remaining > 0:
        text += f"🎯 До следующего ранга: `{remaining}`\n"
    elif rank == "Семицвет":
        text += "\n🌈 Вы достигли высшего ранга!\n"
    text += f"\n{DIVIDER}\n{FOOTER}"
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("modstop"), IsStaffFilter())
async def cmd_modstop(message: Message):
    top = await get_top_moderators(10)
    if not top:
        await message.answer("📊 Нет данных.")
        return
    text = f"{HEADER}\n{DIVIDER}\n\n🏆 *ТОП МОДЕРАТОРОВ* 🏆\n\n"
    for i, row in enumerate(top, 1):
        emoji = RANK_EMOJI.get(row["rank"], "🏅")
        text += f"{i}. {emoji} `{row['telegram_id']}` — {row['rank']} — {row['total_actions']} жалоб\n"
    text += f"\n{DIVIDER}\n{FOOTER}"
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("setrank"), IsHeadAdminFilter())
async def cmd_setrank(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ Формат: `/setrank <id> <ранг>`\n\nРанги: " + ", ".join(RANK_EMOJI.keys()),
            parse_mode="Markdown"
        )
        return
    if not args[1].isdigit():
        await message.answer("❌ ID должен быть числом.")
        return
    if args[2] not in RANK_EMOJI:
        await message.answer("❌ Неверный ранг.")
        return
    if await set_mod_rank_by_admin(int(args[1]), args[2]):
        await message.answer(f"✅ Ранг *{args[2]}* установлен для `{args[1]}`", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка.")

# ---------- УПРАВЛЕНИЕ СОТРУДНИКАМИ ----------

@router.message(Command("addstaff"), IsStaffFilter())
async def cmd_addstaff(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n👤 *ДОБАВЛЕНИЕ СОТРУДНИКА*\n\nВведите Telegram ID:",
        parse_mode="Markdown"
    )
    await state.set_state(StaffAddState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(StaffAddState.target)
async def addstaff_target(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    target = (message.text or "").strip()
    if not target.isdigit():
        await message.answer("❌ Введите числовой ID:")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(target_id=int(target))
    await message.answer(
        f"🎯 ID: `{target}`\n\nВыберите роль:", parse_mode="Markdown",
        reply_markup=staff_roles_keyboard()
    )
    await state.set_state(StaffAddState.role)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.callback_query(F.data.startswith("sr:"), IsStaffFilter())
async def addstaff_role(callback: CallbackQuery, state: FSMContext):
    fsm_cancel(callback.from_user.id)
    role_key = callback.data.split(":")[1]
    if role_key == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено.")
        await callback.answer()
        return
    data        = await state.get_data()
    telegram_id = data["target_id"]
    await state.clear()
    # Получаем username через Telegram API если возможно
    username = None
    try:
        chat    = await callback.message.bot.get_chat(telegram_id)
        username = chat.username
    except Exception:
        pass
    try:
        async with mdb() as db:
            await db.execute(
                "INSERT OR REPLACE INTO staff (telegram_id, username, role, added_by, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (telegram_id, username, role_key, callback.from_user.id, now())
            )
            await db.commit()
        invalidate_role(telegram_id)
    except Exception as e:
        log.error(f"addstaff: {e}")
        await callback.message.edit_text("❌ Ошибка.")
        await callback.answer()
        return
    role_label = ROLE_LABELS.get(role_key, role_key)
    await callback.message.edit_text(
        f"{HEADER}\n{DIVIDER}\n\n✅ *СОТРУДНИК ДОБАВЛЕН!*\n\n"
        f"🆔 `{telegram_id}`\n👤 Роль: *{role_label}*\n📅 {now()}\n\n{DIVIDER}\n{FOOTER}",
        parse_mode="Markdown"
    )
    await mod_log(str(callback.from_user.id), "add_staff", str(telegram_id), role_key)
    await callback.answer()

@router.message(Command("delstaff"), IsStaffFilter())
async def cmd_delstaff(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n❌ *УДАЛЕНИЕ СОТРУДНИКА*\n\nВведите Telegram ID:",
        parse_mode="Markdown"
    )
    await state.set_state(StaffDeleteState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(StaffDeleteState.target)
async def delstaff_execute(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    target = (message.text or "").strip()
    await state.clear()
    if not target.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    tid = int(target)
    if tid == MAIN_ADMIN_ID:
        await message.answer("❌ Нельзя удалить главного администратора!")
        return
    try:
        async with mdb() as db:
            cur = await db.execute("DELETE FROM staff WHERE telegram_id=?", (tid,))
            await db.commit()
        invalidate_role(tid)
        if cur.rowcount:
            await message.answer(f"✅ Сотрудник `{tid}` удалён.", parse_mode="Markdown")
            await mod_log(str(message.from_user.id), "del_staff", str(tid))
        else:
            await message.answer(f"⚠️ Сотрудник `{tid}` не найден.", parse_mode="Markdown")
    except Exception as e:
        log.error(f"delstaff: {e}")
        await message.answer("❌ Ошибка.")

# ---------- УПРАВЛЕНИЕ БАЗОЙ ----------

@router.message(Command("addscam"), IsStaffFilter())
async def cmd_addscam(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n➕ *ДОБАВЛЕНИЕ В БАЗУ*\n\nВведите @username или ID:",
        parse_mode="Markdown"
    )
    await state.set_state(AdminAddState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AdminAddState.target)
async def addscam_target(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    identifier = validate_identifier(message.text or "")
    if not identifier:
        await message.answer("❌ Неверный формат:")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(target_id=identifier)
    await message.answer(
        f"🎯 Цель: `{identifier}`\n\nВыберите статус:", parse_mode="Markdown",
        reply_markup=statuses_keyboard()
    )
    await state.set_state(AdminAddState.status)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.callback_query(F.data.startswith("adm_s:"), IsStaffFilter())
async def addscam_status(callback: CallbackQuery, state: FSMContext):
    fsm_cancel(callback.from_user.id)
    status = callback.data.split(":")[1]
    if status == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено.")
        await callback.answer()
        return
    await state.update_data(status=status)
    await callback.message.edit_text(
        f"📝 Статус: *{status}*\n\nВведите причину добавления:", parse_mode="Markdown"
    )
    await state.set_state(AdminAddState.reason)
    fsm_schedule(callback.from_user.id, state, asyncio.get_event_loop())
    await callback.answer()

@router.message(AdminAddState.reason)
async def addscam_reason(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("❌ Введите причину:")
        fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())
        return
    await state.update_data(reason=reason)
    await message.answer("🔗 Ссылка на доказательство или «-»:")
    await state.set_state(AdminAddState.evidence)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AdminAddState.evidence)
async def addscam_evidence(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    evidence = (message.text or "").strip()
    data     = await state.get_data()
    await state.clear()
    target_id = data["target_id"]
    username  = target_id if not target_id.isdigit() else None
    success   = await db_add_user(
        target_id, username, data["status"], data["reason"],
        evidence if evidence != "-" else None,
        str(message.from_user.id)
    )
    if success:
        emoji = STATUS_EMOJI.get(data["status"], "✅")
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✅ *ДОБАВЛЕНО В БАЗУ!*\n\n"
            f"{emoji} `{target_id}` → *{data['status']}*\n"
            f"📋 Причина: {sanitize(data['reason'])}\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка сохранения.")

@router.message(Command("delscam"), IsStaffFilter())
async def cmd_delscam(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n🗑 *УДАЛЕНИЕ ИЗ БАЗЫ*\n\nВведите @username или ID:",
        parse_mode="Markdown"
    )
    await state.set_state(AdminDeleteState.target)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(AdminDeleteState.target)
async def delscam_execute(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    identifier = validate_identifier(message.text or "")
    await state.clear()
    if not identifier:
        await message.answer("❌ Неверный формат.")
        return
    if await db_delete_user(identifier, str(message.from_user.id)):
        await message.answer(f"✅ Запись `{identifier}` удалена.", parse_mode="Markdown")
    else:
        await message.answer(f"⚠️ Запись `{identifier}` не найдена.", parse_mode="Markdown")

# ---------- /pending ----------

@router.message(Command("pending"), IsStaffFilter())
async def cmd_pending(message: Message):
    reports = await db_pending_reports(1)
    if not reports:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✨ Жалоб нет!\n\n{DIVIDER}\n{FOOTER}", parse_mode="Markdown"
        )
        return
    await send_pending_report(message, reports[0])

async def send_pending_report(message: Message, report):
    text = (
        f"{HEADER}\n{DIVIDER}\n\n🆕 *ЖАЛОБА #{report['id']}*\n\n"
        f"🎯 Цель: `{sanitize(report['target_un'])}`\n"
        f"📋 Тип: *{sanitize(report['report_type'])}*\n"
        f"📝 Описание:\n{sanitize(report['description'])}\n"
    )
    if report["evidence"]:
        text += f"🔗 Доказательство: {sanitize(report['evidence'])}\n"
    text += f"\n📅 {report['created_at']}\n👤 `{report['reporter_id']}`\n\n{DIVIDER}"
    await message.answer(text, parse_mode="Markdown", reply_markup=pending_keyboard(report["id"]))

@router.callback_query(F.data.startswith("pnd:"), IsStaffFilter())
async def pending_action(callback: CallbackQuery):
    _, action, report_id_str = callback.data.split(":")
    report_id = int(report_id_str)

    if action == "approve":
        async with mdb() as db:
            cur = await db.execute("SELECT * FROM reports WHERE id=?", (report_id,))
            row = await cur.fetchone()
        if row:
            tid      = row["target_id"] if row["target_id"].isdigit() else row["target_un"].lstrip("@")
            username = None if row["target_id"].isdigit() else row["target_un"].lstrip("@")
            await db_add_user(tid, username, "scammer", row["description"],
                              row["evidence"], str(callback.from_user.id))
        await db_update_report_status(report_id, "approved")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        text = f"{HEADER}\n{DIVIDER}\n\n✅ *Жалоба #{report_id} принята!*"
        if new_rank:
            text += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.edit_text(text, parse_mode="Markdown")

    elif action == "reject":
        await db_update_report_status(report_id, "rejected")
        new_rank   = await update_mod_rank(callback.from_user.id, 1)
        rank_emoji = RANK_EMOJI.get((await get_mod_rank(callback.from_user.id))[0], "🏅")
        text = f"{HEADER}\n{DIVIDER}\n\n❌ *Жалоба #{report_id} отклонена.*"
        if new_rank:
            text += f"\n\n✨ *ПОВЫШЕНИЕ!* ✨\n{rank_emoji} Новый ранг: *{new_rank}*"
        await callback.message.edit_text(text, parse_mode="Markdown")

    elif action == "next":
        rows = await db_pending_reports(5)
        next_r = next((r for r in rows if r["id"] != report_id), None)
        if next_r:
            await callback.message.delete()
            await send_pending_report(callback.message, next_r)
        else:
            await callback.message.edit_text(
                f"{HEADER}\n{DIVIDER}\n\n✨ Жалоб больше нет!\n\n{FOOTER}", parse_mode="Markdown"
            )
    await callback.answer()

# ---------- КАНАЛЫ ----------

@router.message(Command("channels"), IsStaffFilter())
async def cmd_channels(message: Message, state: FSMContext):
    await state.clear()
    count = await db_count("required_channels", "active=1")
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n📢 *КАНАЛЫ*\n\nАктивных: *{count}*",
        parse_mode="Markdown", reply_markup=channels_keyboard()
    )

@router.callback_query(F.data == "chan:list", IsStaffFilter())
async def channels_list(callback: CallbackQuery):
    channels = await db_get_channels()
    if not channels:
        await callback.answer("Список пуст.", show_alert=True)
        return
    text = f"{HEADER}\n{DIVIDER}\n\n📋 *КАНАЛЫ:*\n\n"
    for ch in channels:
        text += f"• *{ch['title']}*\n  🆔 `{ch['channel_id']}`\n  🔗 {ch['channel_url']}\n\n"
    text += f"{DIVIDER}\n{FOOTER}"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "chan:add", IsStaffFilter())
async def channel_add_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        f"{HEADER}\n{DIVIDER}\n\nШаг 1/3: ID канала (пример: `-1001234567890`):",
        parse_mode="Markdown"
    )
    await state.set_state(ChannelAddState.channel_id)
    fsm_schedule(callback.from_user.id, state, asyncio.get_event_loop())
    await callback.answer()

@router.message(ChannelAddState.channel_id)
async def channel_add_id(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    await state.update_data(channel_id=(message.text or "").strip())
    await message.answer("Шаг 2/3: Ссылка (пример: `https://t.me/channelname`):", parse_mode="Markdown")
    await state.set_state(ChannelAddState.url)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(ChannelAddState.url)
async def channel_add_url(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    await state.update_data(url=(message.text or "").strip())
    await message.answer("Шаг 3/3: Название (пример: `Arion News`):", parse_mode="Markdown")
    await state.set_state(ChannelAddState.title)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(ChannelAddState.title)
async def channel_add_title(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    title = (message.text or "").strip()
    data  = await state.get_data()
    await state.clear()
    if await db_add_channel(data["channel_id"], data["url"], title):
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✅ *КАНАЛ ДОБАВЛЕН!*\n\n"
            f"📌 *{title}*\n🆔 `{data['channel_id']}`\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка.")

@router.callback_query(F.data == "chan:del", IsStaffFilter())
async def channel_delete_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    channels = await db_get_channels()
    if not channels:
        await callback.answer("Список пуст.", show_alert=True)
        return
    text = f"{HEADER}\n{DIVIDER}\n\nВведите ID для удаления:\n\n"
    for ch in channels:
        text += f"• *{ch['title']}* — `{ch['channel_id']}`\n"
    await callback.message.answer(text, parse_mode="Markdown")
    await state.set_state(ChannelDeleteState.channel_id)
    fsm_schedule(callback.from_user.id, state, asyncio.get_event_loop())
    await callback.answer()

@router.message(ChannelDeleteState.channel_id)
async def channel_delete_execute(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    cid = (message.text or "").strip()
    await state.clear()
    if await db_delete_channel(cid):
        await message.answer(f"✅ Канал `{cid}` удалён.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ Канал `{cid}` не найден.", parse_mode="Markdown")

@router.callback_query(F.data == "chan:close")
async def channel_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ---------- ИСТОРИЯ / СТАТИСТИКА / СБРОС ----------

@router.message(F.text == "📜 ИСТОРИЯ")
async def button_history(message: Message):
    if not await subscription_gate(message):
        return
    rows = await db_get_history(str(message.from_user.id))
    if not rows:
        text = await get_text("history_empty")
        await message.answer(text, parse_mode="Markdown")
        return
    text = f"{HEADER}\n{DIVIDER}\n\n📜 *АРХИВ ВАШИХ ПРОВЕРОК*\n\n"
    for target, result, checked_at in rows:
        emoji = "🔥" if result == "found" else "🫧"
        text += f"{emoji} `{target}` — {checked_at}\n"
    text += f"\n{DIVIDER}\n{FOOTER}"
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "📈 СТАТИСТИКА", IsStaffFilter())
async def button_stats(message: Message):
    total    = await db_count("users")
    scammers = await db_count("users", "status='scammer'")
    guar     = await db_count("users", "status='guarantor'")
    trusted  = await db_count("users", "status='trusted'")
    pending  = await db_count("reports", "status='pending'")
    bot_u    = await db_count("bot_users")
    ap_pend  = await db_count("appeals", "status='pending'")
    ap_app   = await db_count("appeals", "status='approved'")
    stats    = await get_all_stats()
    text = await get_text("stats")
    text += (
        f"👥 Пользователей бота: `{bot_u}`\n\n"
        f"📂 Всего в базе: `{total}`\n"
        f"🔥 Скамеров: `{scammers}`\n"
        f"💎 Гарантов: `{guar}`\n"
        f"🫧 Доверенных: `{trusted}`\n\n"
        f"{DIVIDER}\n\n"
        f"🔎 Проверок: `{stats['checks']}`\n"
        f"🎯 Найдено: `{stats['found']}`\n"
        f"✨ Чистых: `{stats['clean']}`\n"
        f"🚨 Жалоб: `{stats['reports']}`\n"
        f"🆕 Ожидают: `{pending}`\n\n"
        f"{DIVIDER}\n\n"
        f"⚖️ Апелляций (новых): `{ap_pend}`\n"
        f"✅ Апелляций одобрено: `{ap_app}`\n"
        f"📊 Одобрено за всё время: `{stats['appeals_approved']}`\n\n"
        f"{DIVIDER}\n💡 /admin — управление"
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "🗑 СБРОС", IsStaffFilter())
async def button_reset(message: Message):
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n🗑 *СБРОС ДАННЫХ*\n\n⚠️ Выберите что очистить:\n❗ Необратимо!",
        parse_mode="Markdown", reply_markup=reset_keyboard()
    )

@router.callback_query(F.data.startswith("reset:"), IsStaffFilter())
async def reset_confirm(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    if action == "cancel":
        await callback.message.edit_text("❌ Сброс отменён.")
        await callback.answer()
        return
    names      = {"reports": "ЖАЛОБЫ", "users": "БАЗУ", "history": "ИСТОРИЮ", "all": "ВСЁ"}
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА", callback_data=f"resetok:{action}"),
         InlineKeyboardButton(text="❌ НЕТ", callback_data="reset:cancel")]
    ])
    await callback.message.edit_text(
        f"⚠️ Сбросить *{names.get(action, action)}*?\n❗ Необратимо!",
        parse_mode="Markdown", reply_markup=confirm_kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("resetok:"), IsStaffFilter())
async def reset_execute(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    await db_clear(action)
    await callback.message.edit_text(
        f"{HEADER}\n{DIVIDER}\n\n✅ *СБРОС ВЫПОЛНЕН!*\n\n"
        f"Очищено: *{action.upper()}*\n\n{FOOTER}", parse_mode="Markdown"
    )
    await callback.answer()
    await mod_log(str(callback.from_user.id), "reset", action)

# ---------- ЭКСПОРТ ----------

@router.message(Command("export"), IsStaffFilter())
async def cmd_export(message: Message):
    total = await db_count("users")
    if not total:
        await message.answer("⚠️ База пуста.")
        return
    await message.answer("⏳ Формирую CSV...")
    data     = await db_export_csv()
    filename = f"scambase_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await message.answer_document(
        BufferedInputFile(data, filename),
        caption=f"{HEADER}\n{DIVIDER}\n\n📊 *ЭКСПОРТ БАЗЫ*\n\n👥 Записей: `{total}`\n📅 {now()}\n\n{FOOTER}",
        parse_mode="Markdown"
    )

# ---------- РАССЫЛКА (с батчингом) ----------

@router.message(Command("broadcast"), IsHeadAdminFilter())
async def cmd_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n📢 *РАССЫЛКА*\n\nВведите текст (поддерживается Markdown).\n«-» для отмены:",
        parse_mode="Markdown"
    )
    await state.set_state(BroadcastState.text)
    fsm_schedule(message.from_user.id, state, asyncio.get_event_loop())

@router.message(BroadcastState.text)
async def broadcast_execute(message: Message, state: FSMContext):
    fsm_cancel(message.from_user.id)
    text = (message.text or "").strip()
    await state.clear()
    if text == "-":
        await message.answer("❌ Рассылка отменена.")
        return
    users = await db_get_all_users()
    if not users:
        await message.answer("⚠️ Нет пользователей.")
        return

    sent   = 0
    failed = 0
    status_msg = await message.answer(f"📢 Рассылка: 0/{len(users)}...")

    for i, row in enumerate(users, 1):
        try:
            await message.bot.send_message(row["telegram_id"], text, parse_mode="Markdown")
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await message.bot.send_message(row["telegram_id"], text, parse_mode="Markdown")
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            failed += 1
        except TelegramBadRequest as e:
            if "can't parse entities" in str(e):
                try:
                    await message.bot.send_message(row["telegram_id"], text)
                    sent += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

        # Батчинг: пауза каждые BROADCAST_BATCH_SIZE сообщений
        if i % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(1)
            try:
                await status_msg.edit_text(f"📢 Рассылка: {i}/{len(users)}...")
            except Exception:
                pass
        else:
            await asyncio.sleep(BROADCAST_COOLDOWN)

    await status_msg.edit_text(
        f"{HEADER}\n{DIVIDER}\n\n✅ *РАССЫЛКА ЗАВЕРШЕНА!*\n\n"
        f"📨 Отправлено: `{sent}`\n❌ Ошибок: `{failed}`\n\n{FOOTER}",
        parse_mode="Markdown"
    )
    log.info(f"broadcast {sent}/{len(users)} by {message.from_user.id}")

# ---------- MINI APP ----------

@router.message(F.text == "📱 MINI APP")
async def button_miniapp(message: Message):
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n📱 *ARION MINI APP*\n\nБыстрый доступ к системе:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚀 ОТКРЫТЬ", web_app=WebAppInfo(url=MINI_APP_URL))
        ]])
    )

# ============================================
#         ЗАПУСК
# ============================================

async def main():
    log.info(HEADER)
    log.info("💎 Arion ScamBase v14.0 — с системой апелляций!")

    if "ТОКЕН" in BOT_TOKEN or MAIN_ADMIN_ID == 0:
        log.error("❌ Настройте BOT_TOKEN и MAIN_ADMIN_ID в .env!")
        log.error("Пример .env:")
        log.error("ARION_TOKEN=ваш_токен")
        log.error("MAIN_ADMIN_ID=123456789")
        log.error("CONSIDERATION_CHAT_ID=-1001234567890")
        log.error("REPORT_CHAT_ID=-1009876543210")
        log.error("APPEAL_CHAT_ID=-1009999999999  # чат для апелляций")
        log.error("API_SECRET=ваш_секретный_ключ")
        return

    await init_db()
    asyncio.create_task(start_api_server())

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: loop.stop())
        except NotImplementedError:
            pass

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    await bot.set_my_commands([
        BotCommand(command="start",            description="💎 Запуск"),
        BotCommand(command="check",            description="🔎 Проверить"),
        BotCommand(command="cons",             description="📝 Жалоба (форма)"),
        BotCommand(command="report",           description="🚨 Быстрая жалоба"),
        BotCommand(command="appeal",           description="⚖️ Подать апелляцию"),
        BotCommand(command="admin",            description="🛠 Админ-центр"),
        BotCommand(command="addscam",          description="➕ Добавить в базу"),
        BotCommand(command="delscam",          description="🗑 Удалить из базы"),
        BotCommand(command="addstaff",         description="👤 Добавить сотрудника"),
        BotCommand(command="delstaff",         description="❌ Удалить сотрудника"),
        BotCommand(command="channels",         description="📢 Каналы подписки"),
        BotCommand(command="pending",          description="📋 Жалобы"),
        BotCommand(command="pending_appeals",  description="⚖️ Апелляции"),
        BotCommand(command="export",           description="📊 CSV"),
        BotCommand(command="broadcast",        description="📢 Рассылка"),
        BotCommand(command="myrank",           description="🏅 Мой ранг"),
        BotCommand(command="modstop",          description="🏆 Топ модераторов"),
        BotCommand(command="setrank",          description="👑 Установить ранг"),
    ])

    log.info("🟢 БОТ ЗАПУЩЕН v14.0!")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        log.error(f"Polling error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
