#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════════╗
  ⚜️  ARION COMMAND CENTER v5.0  ⚜️
  ★ ▬▬▬▬▬▬▬▬▬▬ ★
  pip install aiogram==3.7.0 aiosqlite aiohttp python-dotenv
  python command_center_v5.py
  ★ ▬▬▬▬▬▬▬▬▬▬ ★
╚══════════════════════════════════════════════╝

Changelog v5.0:
  [FIX]  callback.state → передаётся явно через параметр state
  [FIX]  Username сохраняется при добавлении сотрудника
  [FIX]  Навигация по жалобам cons работает корректно
  [NEW]  Поиск по базе прямо из админ-центра
  [NEW]  Добавление/удаление записей в базу через API
  [NEW]  Рассылка из админ-центра
  [NEW]  Управление каналами подписки через API
  [NEW]  Просмотр и рассмотрение апелляций
  [NEW]  Экспорт CSV из админ-центра
  [NEW]  Расширенный дашборд со всей статистикой
  [NEW]  Просмотр лога действий модераторов
"""

import asyncio
import logging
import os
import re
import signal
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv
load_dotenv()

import aiohttp
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
    BufferedInputFile,
)
from aiogram.exceptions import TelegramBadRequest

# ============================================
#         НАСТРОЙКИ ИЗ .env
# ============================================

ADMIN_CENTER_TOKEN = os.getenv("ADMIN_CENTER_TOKEN", "")
MAIN_ADMIN_ID      = int(os.getenv("MAIN_ADMIN_ID", "0"))

BOTS_API_CONFIG: Dict[str, Dict] = {
    "arion_scambase": {
        "name":        "🛡️ Arion ScamBase",
        "emoji":       "🛡️",
        "description": "Анти-скам база",
        "api_url":     os.getenv("SCAMBASE_API_URL", "http://localhost:8080"),
        "api_secret":  os.getenv("SCAMBASE_API_SECRET", ""),
        "enabled":     True,
    },
    # Пример второго бота:
    # "another_bot": {
    #     "name": "🤖 Другой Бот",
    #     "emoji": "🤖",
    #     "api_url": os.getenv("OTHER_BOT_API_URL", "http://localhost:8081"),
    #     "api_secret": os.getenv("OTHER_BOT_API_SECRET", ""),
    #     "enabled": True,
    # },
}

CENTER_DB_PATH = "command_center.db"

# ============================================
#         ДИЗАЙН
# ============================================

DIVIDER = "★ ▬▬▬▬▬▬▬▬▬▬ ★"
HEADER  = "⚜️ ⋙ ARION COMMAND CENTER ⋘ ⚜️"
FOOTER  = "👑 Система управления ARION v5.0"
LINE    = "━━━━━━━━━━━━━━━━━━━━━━"

# ============================================
#         ЛОГГИРОВАНИЕ
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CMD-CENTER] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("command_center.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("CommandCenter")

# ============================================
#         БД АДМИН-ЦЕНТРА
# ============================================

async def init_center_db():
    async with aiosqlite.connect(CENTER_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS center_staff (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'reviewer',
                added_by INTEGER,
                added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                bot_key TEXT,
                action TEXT,
                details TEXT,
                created_at TEXT
            );
        """)
        await db.commit()

    async with aiosqlite.connect(CENTER_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR REPLACE INTO center_staff "
            "(telegram_id, username, role, added_by, added_at) VALUES (?, ?, 'head_admin', ?, ?)",
            (MAIN_ADMIN_ID, "Верховный Администратор", MAIN_ADMIN_ID,
             datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        await db.commit()
    logger.info("✅ БД админ-центра готова")

# ============================================
#         РОЛИ
# ============================================

ROLES: Dict[str, Dict] = {
    "head_admin": {
        "name":                  "👑 Верховный Администратор",
        "level":                 4,
        "can_manage_staff":      True,
        "can_broadcast":         True,
        "can_manage_db":         True,
        "can_delete_reports":    True,
        "can_reset_data":        True,
        "can_view_stats":        True,
        "can_view_reports":      True,
        "can_moderate_reports":  True,
        "can_review_reports":    True,
        "can_manage_design":     True,
        "can_view_logs":         True,
        "can_manage_channels":   True,
        "can_view_appeals":      True,
        "can_moderate_appeals":  True,
        "can_search_db":         True,
    },
    "guarantor": {
        "name":                  "💎 Официальный Гарант",
        "level":                 3,
        "can_manage_staff":      False,
        "can_broadcast":         False,
        "can_manage_db":         True,
        "can_delete_reports":    False,
        "can_reset_data":        False,
        "can_view_stats":        True,
        "can_view_reports":      True,
        "can_moderate_reports":  False,
        "can_review_reports":    False,
        "can_manage_design":     False,
        "can_view_logs":         False,
        "can_manage_channels":   False,
        "can_view_appeals":      True,
        "can_moderate_appeals":  False,
        "can_search_db":         True,
    },
    "moderator": {
        "name":                  "🛡️ Старший Модератор",
        "level":                 2,
        "can_manage_staff":      False,
        "can_broadcast":         False,
        "can_manage_db":         True,
        "can_delete_reports":    True,
        "can_reset_data":        False,
        "can_view_stats":        True,
        "can_view_reports":      True,
        "can_moderate_reports":  True,
        "can_review_reports":    False,
        "can_manage_design":     False,
        "can_view_logs":         False,
        "can_manage_channels":   False,
        "can_view_appeals":      True,
        "can_moderate_appeals":  True,
        "can_search_db":         True,
    },
    "reviewer": {
        "name":                  "👁 Инспектор Жалоб",
        "level":                 1,
        "can_manage_staff":      False,
        "can_broadcast":         False,
        "can_manage_db":         False,
        "can_delete_reports":    False,
        "can_reset_data":        False,
        "can_view_stats":        False,
        "can_view_reports":      True,
        "can_moderate_reports":  False,
        "can_review_reports":    True,
        "can_manage_design":     False,
        "can_view_logs":         False,
        "can_manage_channels":   False,
        "can_view_appeals":      True,
        "can_moderate_appeals":  False,
        "can_search_db":         True,
    },
}

# ============================================
#         API КЛИЕНТ
# ============================================

class BotAPIClient:
    def __init__(self, api_url: str, api_secret: str):
        self.api_url = api_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_secret}",
            "Content-Type":  "application/json",
        }
        self._session: Optional[aiohttp.ClientSession] = None

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, params: dict = None) -> Any:
        try:
            sess = await self._sess()
            async with sess.get(f"{self.api_url}{path}", headers=self.headers, params=params) as r:
                if r.status == 200:
                    return await r.json()
                return {"error": f"HTTP {r.status}"}
        except Exception as e:
            return {"error": str(e)}

    async def _post(self, path: str, payload: dict) -> bool:
        try:
            sess = await self._sess()
            async with sess.post(f"{self.api_url}{path}", json=payload, headers=self.headers) as r:
                return r.status == 200
        except Exception:
            return False

    # --- Статистика ---
    async def get_stats(self) -> Dict:
        return await self._get("/api/stats")

    # --- Топ модераторов ---
    async def get_top_moderators(self, limit: int = 15) -> List[Dict]:
        data = await self._get("/api/moderators/top")
        return data[:limit] if isinstance(data, list) else []

    # --- /cons жалобы ---
    async def get_pending_cons(self, limit: int = 50) -> List[Dict]:
        data = await self._get("/api/cons/pending")
        return data[:limit] if isinstance(data, list) else []

    async def get_cons_detail(self, cons_id: int) -> Optional[Dict]:
        data = await self._get(f"/api/cons/{cons_id}")
        return data if isinstance(data, dict) and "error" not in data else None

    async def moderate_cons(self, cons_id: int, action: str, moderator_id: int) -> bool:
        return await self._post("/api/cons/moderate", {
            "cons_id": cons_id, "action": action, "moderator_id": moderator_id
        })

    # --- Поиск по базе ---
    async def search_db(self, query: str) -> List[Dict]:
        data = await self._get("/api/search", params={"q": query})
        return data if isinstance(data, list) else []

    # --- Апелляции ---
    async def get_pending_appeals(self, stage: str = "pending") -> List[Dict]:
        data = await self._get("/api/appeals/pending", params={"stage": stage})
        return data if isinstance(data, list) else []

    # --- Дизайн ---
    async def get_design(self) -> Dict:
        data = await self._get("/api/design")
        return data if isinstance(data, dict) and "error" not in data else {"banners": {}, "texts": {}}

    async def update_banner(self, name: str, file_id: str, file_type: str = "gif") -> bool:
        return await self._post("/api/design/banner", {
            "name": name, "file_id": file_id, "file_type": file_type
        })

    async def update_text(self, name: str, content: str) -> bool:
        return await self._post("/api/design/text", {"name": name, "content": content})


# ============================================
#         УПРАВЛЕНИЕ КЛИЕНТАМИ
# ============================================

_clients: Dict[str, BotAPIClient] = {}

def get_client(bot_key: str) -> Optional[BotAPIClient]:
    if bot_key not in _clients:
        cfg = BOTS_API_CONFIG.get(bot_key)
        if cfg and cfg.get("enabled") and cfg.get("api_secret"):
            _clients[bot_key] = BotAPIClient(cfg["api_url"], cfg["api_secret"])
    return _clients.get(bot_key)

async def close_all_clients():
    for c in _clients.values():
        await c.close()
    _clients.clear()

# ============================================
#         ФУНКЦИИ ПЕРСОНАЛА
# ============================================

def now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")

def sanitize(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def get_staff_role(telegram_id: int) -> Optional[str]:
    if telegram_id == MAIN_ADMIN_ID:
        return "head_admin"
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT role FROM center_staff WHERE telegram_id=?", (telegram_id,))
            row = await cur.fetchone()
        return row["role"] if row else None
    except Exception as e:
        logger.error(f"get_staff_role: {e}")
        return None

async def get_staff_list() -> List[dict]:
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM center_staff ORDER BY "
                "CASE role WHEN 'head_admin' THEN 0 WHEN 'guarantor' THEN 1 "
                "WHEN 'moderator' THEN 2 WHEN 'reviewer' THEN 3 END"
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_staff_list: {e}")
        return []

async def add_staff(telegram_id: int, username: str, role: str, added_by: int) -> bool:
    if telegram_id == MAIN_ADMIN_ID:
        return False
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO center_staff "
                "(telegram_id, username, role, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                (telegram_id, username, role, added_by, now())
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"add_staff: {e}")
        return False

async def remove_staff(telegram_id: int) -> bool:
    if telegram_id == MAIN_ADMIN_ID:
        return False
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            cur = await db.execute("DELETE FROM center_staff WHERE telegram_id=?", (telegram_id,))
            await db.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"remove_staff: {e}")
        return False

async def check_permission(user_id: int, permission: str) -> bool:
    role = await get_staff_role(user_id)
    if not role:
        return False
    return ROLES.get(role, {}).get(permission, False)

async def log_action(user_id: int, bot_key: str, action: str, details: str = ""):
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT username FROM center_staff WHERE telegram_id=?", (user_id,)
            )
            row      = await cur.fetchone()
            username = row[0] if row else str(user_id)
            await db.execute(
                "INSERT INTO action_log (user_id, username, bot_key, action, details, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, bot_key, action, details, now())
            )
            await db.commit()
    except Exception as e:
        logger.error(f"log_action: {e}")

async def get_recent_logs(limit: int = 20) -> List[dict]:
    try:
        async with aiosqlite.connect(CENTER_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_logs: {e}")
        return []

def format_number(n: int) -> str:
    return f"{n:,}".replace(",", " ")

# ============================================
#         FSM СОСТОЯНИЯ
# ============================================

class StaffAddState(StatesGroup):
    user_id = State()
    role    = State()

class StaffRemoveState(StatesGroup):
    user_id = State()

class SearchState(StatesGroup):
    query = State()

class BroadcastState(StatesGroup):
    bot_key = State()
    text    = State()

class DesignBannerState(StatesGroup):
    bot_key     = State()
    banner_name = State()
    waiting     = State()

class DesignTextState(StatesGroup):
    bot_key   = State()
    text_name = State()
    waiting   = State()

class AddToDbState(StatesGroup):
    bot_key    = State()
    identifier = State()
    status     = State()
    reason     = State()
    evidence   = State()

class DelFromDbState(StatesGroup):
    bot_key    = State()
    identifier = State()

# ============================================
#         ФИЛЬТРЫ
# ============================================

class IsStaffFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await get_staff_role(user.id) is not None

# ============================================
#         КЛАВИАТУРЫ
# ============================================

def main_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for bot_key, cfg in BOTS_API_CONFIG.items():
        if cfg.get("enabled"):
            buttons.append([InlineKeyboardButton(
                text=f"{cfg['emoji']} {cfg['name']}",
                callback_data=f"select_bot:{bot_key}"
            )])
    buttons.append([
        InlineKeyboardButton(text="👥 СОСТАВ АДМИНИСТРАЦИИ", callback_data="center:staff"),
        InlineKeyboardButton(text="📋 ЛОГ ДЕЙСТВИЙ",        callback_data="center:logs"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def bot_panel_keyboard(bot_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 СТАТИСТИКА",       callback_data=f"bot:stats:{bot_key}"),
         InlineKeyboardButton(text="🏆 ТОП МОДЕРАТОРОВ",  callback_data=f"bot:modtop:{bot_key}")],
        [InlineKeyboardButton(text="🔎 ПОИСК ПО БАЗЕ",    callback_data=f"bot:search:{bot_key}"),
         InlineKeyboardButton(text="📝 ЖАЛОБЫ /cons",     callback_data=f"bot:cons:{bot_key}:0")],
        [InlineKeyboardButton(text="⚖️ АПЕЛЛЯЦИИ",        callback_data=f"bot:appeals:{bot_key}:pending"),
         InlineKeyboardButton(text="🎨 ОФОРМЛЕНИЕ",       callback_data=f"bot:design:{bot_key}")],
        [InlineKeyboardButton(text="➕ В БАЗУ",            callback_data=f"bot:adddb:{bot_key}"),
         InlineKeyboardButton(text="🗑 ИЗ БАЗЫ",          callback_data=f"bot:deldb:{bot_key}")],
        [InlineKeyboardButton(text="📢 РАССЫЛКА",         callback_data=f"bot:broadcast:{bot_key}"),
         InlineKeyboardButton(text="📊 ЭКСПОРТ CSV",      callback_data=f"bot:export:{bot_key}")],
        [InlineKeyboardButton(text="🔄 ОБНОВИТЬ",         callback_data=f"bot:refresh:{bot_key}")],
        [InlineKeyboardButton(text="🔙 К ВЫБОРУ БОТА",   callback_data="back_to_bots")],
    ])

def design_menu_keyboard(bot_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ БАННЕРЫ", callback_data=f"design:banners:{bot_key}")],
        [InlineKeyboardButton(text="💬 ТЕКСТЫ",  callback_data=f"design:texts:{bot_key}")],
        [InlineKeyboardButton(text="🔙 НАЗАД",   callback_data=f"back_to_panel:{bot_key}")],
    ])

BANNER_LIST = [
    ("start",    "🎬 Баннер /start"),
    ("check",    "🔎 Гифка проверки"),
    ("scammer",  "🔥 Баннер «Скамер»"),
    ("clean",    "🫧 Баннер «Чист»"),
    ("report",   "🚨 Баннер жалобы"),
    ("admin",    "👑 Баннер админ-центра"),
]

TEXT_LIST = [
    ("welcome_admin",  "💎 Приветствие (админ)"),
    ("welcome_user",   "💎 Приветствие (пользователь)"),
    ("check_start",    "🔎 Начало проверки"),
    ("scammer_found",  "🔥 Найден скамер"),
    ("user_clean",     "🫧 Пользователь чист"),
    ("report_start",   "🚨 Начало жалобы"),
    ("report_success", "✅ Жалоба принята"),
    ("stats",          "📈 Статистика"),
    ("cons_form",      "📝 Форма жалобы /cons"),
]

def banners_list_keyboard(bot_key: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"banner:edit:{bot_key}:{name}")]
        for name, label in BANNER_LIST
    ]
    buttons.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data=f"bot:design:{bot_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def texts_list_keyboard(bot_key: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"text:edit:{bot_key}:{name}")]
        for name, label in TEXT_LIST
    ]
    buttons.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data=f"bot:design:{bot_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 ОТМЕНА", callback_data="cancel_action")]
    ])

def staff_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ПРИНЯТЬ В ШТАТ",     callback_data="staff:add")],
        [InlineKeyboardButton(text="🗑 ИСКЛЮЧИТЬ ИЗ ШТАТА", callback_data="staff:remove")],
        [InlineKeyboardButton(text="📋 СПИСОК СОТРУДНИКОВ", callback_data="staff:list")],
        [InlineKeyboardButton(text="🔙 НАЗАД",              callback_data="back_to_bots")],
    ])

def staff_roles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Официальный Гарант",  callback_data="staffrole:guarantor")],
        [InlineKeyboardButton(text="🛡️ Старший Модератор",   callback_data="staffrole:moderator")],
        [InlineKeyboardButton(text="👁 Инспектор Жалоб",    callback_data="staffrole:reviewer")],
        [InlineKeyboardButton(text="🔙 ОТМЕНА",              callback_data="staff:cancel")],
    ])

def db_statuses_keyboard(bot_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Скамер",     callback_data=f"adddb_s:{bot_key}:scammer"),
         InlineKeyboardButton(text="💎 Гарант",     callback_data=f"adddb_s:{bot_key}:guarantor"),
         InlineKeyboardButton(text="🫧 Доверенный", callback_data=f"adddb_s:{bot_key}:trusted")],
        [InlineKeyboardButton(text="❌ Отмена",     callback_data=f"back_to_panel:{bot_key}")],
    ])

def cons_nav_keyboard(bot_key: str, cons_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    buttons.append([
        InlineKeyboardButton(text="✅ ПРИНЯТЬ",   callback_data=f"cons:approve:{bot_key}:{cons_id}:{page}"),
        InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"cons:reject:{bot_key}:{cons_id}:{page}"),
    ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"cons:nav:{bot_key}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"cons:nav:{bot_key}:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def appeal_reviewer_kb(bot_key: str, appeal_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✅ ОДОБРИТЬ",    callback_data=f"aprev:ok:{bot_key}:{appeal_id}:{page}"),
         InlineKeyboardButton(text="❌ ОТКЛОНИТЬ",  callback_data=f"aprev:no:{bot_key}:{appeal_id}:{page}")],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"aprev:nav:{bot_key}:pending:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"aprev:nav:{bot_key}:pending:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def appeal_mod_kb(bot_key: str, appeal_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✅ УДАЛИТЬ ИЗ БАЗЫ",  callback_data=f"apmod:ok:{bot_key}:{appeal_id}:{page}"),
         InlineKeyboardButton(text="❌ ОСТАВИТЬ В БАЗЕ", callback_data=f"apmod:no:{bot_key}:{appeal_id}:{page}")],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"aprev:nav:{bot_key}:reviewer_approved:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"aprev:nav:{bot_key}:reviewer_approved:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================
#         РОУТЕР
# ============================================

router = Router()

# ============================================
#         СТАРТ
# ============================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    role = await get_staff_role(message.from_user.id)
    if not role:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n"
            f"⛔ *ДОСТУП ЗАКРЫТ*\n\n"
            f"Вы не являетесь сотрудником Arion Command Center.\n"
            f"Ваш ID: `{message.from_user.id}`\n\n"
            f"{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
        logger.warning(f"Отказ в доступе {message.from_user.id}")
        return

    role_name = ROLES.get(role, {}).get("name", "Сотрудник")
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"👑 ДОБРО ПОЖАЛОВАТЬ, *{role_name}*\n\n"
        f"Система управления ARION v5.0\n"
        f"Интеграция через HTTP API\n\n"
        f"{DIVIDER}\n\n📦 ВЫБЕРИТЕ ОБЪЕКТ УПРАВЛЕНИЯ:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    await log_action(message.from_user.id, "center", "login", f"Роль: {role}")

# ============================================
#         ОТМЕНА
# ============================================

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    role = await get_staff_role(callback.from_user.id)
    if not role:
        return await callback.answer("⛔ Доступ закрыт.", show_alert=True)
    await state.clear()
    await callback.answer("🚫 Отменено")
    role_name = ROLES.get(role, {}).get("name", "Сотрудник")
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n👑 Вы: *{role_name}*\n\n{DIVIDER}\n\n📦 ВЫБЕРИТЕ ОБЪЕКТ УПРАВЛЕНИЯ:",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    except Exception:
        await callback.message.answer(
            f"{HEADER}\n{DIVIDER}\n\n📦 ВЫБЕРИТЕ ОБЪЕКТ УПРАВЛЕНИЯ:",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )

@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()

# ============================================
#         ВЫБОР БОТА
# ============================================

@router.callback_query(F.data.startswith("select_bot:"))
async def select_bot(callback: CallbackQuery, state: FSMContext):
    role = await get_staff_role(callback.from_user.id)
    if not role:
        return await callback.answer("⛔ Доступ закрыт.", show_alert=True)
    await state.clear()
    bot_key = callback.data.split(":")[1]
    cfg     = BOTS_API_CONFIG.get(bot_key)
    if not cfg or not cfg.get("enabled"):
        return await callback.answer("❌ Бот недоступен!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API не настроен!", show_alert=True)
    await _show_bot_panel(callback, bot_key, cfg)

async def _show_bot_panel(callback: CallbackQuery, bot_key: str, cfg: dict):
    text = (
        f"{cfg['emoji']} *{cfg['name']}*\n{DIVIDER}\n\n"
        f"✅ API: `{cfg['api_url']}`\n\n"
        f"{DIVIDER}\n\n⚔️ ВЫБЕРИТЕ ДЕЙСТВИЕ:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=bot_panel_keyboard(bot_key))
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown",
                                      reply_markup=bot_panel_keyboard(bot_key))
    await callback.answer()

@router.callback_query(F.data == "back_to_bots")
async def back_to_bots(callback: CallbackQuery, state: FSMContext):
    role = await get_staff_role(callback.from_user.id)
    if not role:
        return await callback.answer("⛔ Доступ закрыт.", show_alert=True)
    await state.clear()
    role_name = ROLES.get(role, {}).get("name", "Сотрудник")
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n👑 Вы: *{role_name}*\n\n{DIVIDER}\n\n📦 ВЫБЕРИТЕ ОБЪЕКТ УПРАВЛЕНИЯ:",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("back_to_panel:"))
async def back_to_panel(callback: CallbackQuery, state: FSMContext):
    role = await get_staff_role(callback.from_user.id)
    if not role:
        return await callback.answer("⛔ Доступ закрыт.", show_alert=True)
    await state.clear()
    bot_key = callback.data.split(":")[1]
    cfg     = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{cfg.get('emoji','🤖')} *{cfg.get('name', bot_key)}*\n{DIVIDER}\n\n"
        f"✅ API подключён\n\n{DIVIDER}\n\n⚔️ ВЫБЕРИТЕ ДЕЙСТВИЕ:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=bot_panel_keyboard(bot_key))
    except Exception:
        pass
    await callback.answer()

# ============================================
#         СТАТИСТИКА
# ============================================

@router.callback_query(F.data.startswith("bot:stats:"))
async def bot_stats(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_view_stats"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)
    await callback.answer("📊 Загрузка...")
    stats = await client.get_stats()
    if "error" in stats:
        return await callback.answer(f"❌ Ошибка: {stats['error']}", show_alert=True)
    cfg  = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{cfg.get('emoji','📊')} *{cfg.get('name', bot_key)}* — СТАТИСТИКА\n{DIVIDER}\n\n"
        f"📂 *База:*\n"
        f"• Всего: `{format_number(stats.get('total_users', 0))}`\n"
        f"• Скамеров: `{format_number(stats.get('scammers', 0))}`\n"
        f"• Гарантов: `{format_number(stats.get('guarantors', 0))}`\n"
        f"• Доверенных: `{format_number(stats.get('trusted', 0))}`\n\n"
        f"🚨 *Жалобы:*\n"
        f"• Ожидает (report): `{stats.get('pending_reports', 0)}`\n"
        f"• Ожидает (cons): `{stats.get('pending_cons', 0)}`\n\n"
        f"⚖️ *Апелляции:*\n"
        f"• Новых: `{stats.get('pending_appeals', 0)}`\n"
        f"• У модераторов: `{stats.get('waiting_appeals', 0)}`\n\n"
        f"📈 *Активность:*\n"
        f"• Проверок: `{format_number(stats.get('checks', 0))}`\n"
        f"• Найдено: `{format_number(stats.get('found', 0))}`\n"
        f"• Чистых: `{format_number(stats.get('clean', 0))}`\n"
        f"• Жалоб подано: `{format_number(stats.get('reports', 0))}`\n"
        f"• Апелляций одобрено: `{format_number(stats.get('appeals_approved', 0))}`\n\n"
        f"{DIVIDER}\n{FOOTER}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=f"bot:stats:{bot_key}")],
        [InlineKeyboardButton(text="🔙 НАЗАД",    callback_data=f"back_to_panel:{bot_key}")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

# ============================================
#         ТОП МОДЕРАТОРОВ
# ============================================

@router.callback_query(F.data.startswith("bot:modtop:"))
async def bot_modtop(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_view_stats"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)
    await callback.answer("🏆 Загрузка...")
    mods = await client.get_top_moderators(15)
    rank_emojis = {
        "Бронза": "🥉", "Железо": "⚙️", "Медь": "🔶",
        "Серебро": "🥈", "Золото": "🥇", "Платина": "💎",
        "Алмаз": "💠", "Сапфир": "🔷", "Рубин": "🔴", "Семицвет": "🌈",
    }
    if not mods:
        text = f"{HEADER}\n{DIVIDER}\n\n🏆 *ТОП МОДЕРАТОРОВ*\n\n📭 Нет данных.\n\n{DIVIDER}\n{FOOTER}"
    else:
        text = f"{HEADER}\n{DIVIDER}\n\n🏆 *ТОП МОДЕРАТОРОВ* 🏆\n\n"
        for i, m in enumerate(mods, 1):
            emoji = rank_emojis.get(m.get("rank", ""), "🏅")
            text += f"{i}. {emoji} `{m.get('telegram_id','?')}` — {m.get('rank','?')} — {m.get('total_actions',0)} жалоб\n"
        text += f"\n{DIVIDER}\n{FOOTER}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=f"bot:modtop:{bot_key}")],
        [InlineKeyboardButton(text="🔙 НАЗАД",    callback_data=f"back_to_panel:{bot_key}")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

# ============================================
#         ПОИСК ПО БАЗЕ
# ============================================

@router.callback_query(F.data.startswith("bot:search:"))
async def bot_search_start(callback: CallbackQuery, state: FSMContext):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_search_db"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    await state.update_data(bot_key=bot_key)
    await state.set_state(SearchState.query)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n🔎 *ПОИСК ПО БАЗЕ*\n\n"
            f"Введите @username, ID или часть имени:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(SearchState.query)
async def bot_search_execute(message: Message, state: FSMContext):
    data    = await state.get_data()
    bot_key = data.get("bot_key")
    await state.clear()
    query   = (message.text or "").strip()
    if not query:
        await message.answer("❌ Введите запрос.")
        return
    client = get_client(bot_key)
    if not client:
        await message.answer("❌ API недоступен.")
        return
    await message.answer("🔎 Ищу...")
    results = await client.search_db(query)
    if not results:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n🔎 *ПОИСК: `{query}`*\n\n📭 Ничего не найдено.\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")]
            ])
        )
        return

    status_emoji = {"scammer": "🔥", "guarantor": "💎", "trusted": "🫧"}
    text = f"{HEADER}\n{DIVIDER}\n\n🔎 *РЕЗУЛЬТАТЫ ПОИСКА:* `{query}`\n\n"
    for r in results[:10]:
        emoji = status_emoji.get(r.get("status", ""), "❓")
        tag   = f"@{r['username']}" if r.get("username") else f"ID: {r['telegram_id']}"
        text += (
            f"{emoji} *{sanitize(tag)}*\n"
            f"  Статус: `{r.get('status','?')}`\n"
            f"  Причина: {sanitize(str(r.get('reason','—')))[:80]}\n"
            f"  Добавлен: {r.get('added_at','?')}\n\n"
        )
    if len(results) > 10:
        text += f"_... и ещё {len(results) - 10} записей_\n\n"
    text += f"{DIVIDER}\n{FOOTER}"
    await message.answer(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")]
        ])
    )
    await log_action(message.from_user.id, bot_key, "search_db", query)

# ============================================
#         ЖАЛОБЫ /cons
# ============================================

# Временное хранилище списков жалоб (per-user)
_cons_cache: Dict[int, List[Dict]] = {}
_appeals_cache: Dict[int, List[Dict]] = {}

@router.callback_query(F.data.startswith("bot:cons:"))
async def bot_cons_list(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    page    = int(parts[3]) if len(parts) > 3 else 0

    if not await check_permission(callback.from_user.id, "can_review_reports"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)

    await callback.answer("📝 Загрузка жалоб...")
    cons_list = await client.get_pending_cons(50)
    _cons_cache[callback.from_user.id] = cons_list

    if not cons_list:
        text = f"{HEADER}\n{DIVIDER}\n\n📝 *ЖАЛОБЫ /cons*\n\n✅ Нет ожидающих жалоб.\n\n{DIVIDER}\n{FOOTER}"
        kb   = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 НАЗАД", callback_data=f"back_to_panel:{bot_key}")]
        ])
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        return

    await _show_cons_page(callback, bot_key, page)

async def _show_cons_page(callback: CallbackQuery, bot_key: str, page: int):
    cons_list = _cons_cache.get(callback.from_user.id, [])
    if not cons_list or page >= len(cons_list):
        return

    cons    = cons_list[page]
    cons_id = cons.get("id")
    client  = get_client(bot_key)
    if not client:
        return

    detail = await client.get_cons_detail(cons_id)
    if not detail:
        detail = cons

    text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"📝 *ЖАЛОБА #{cons_id}*\n\n"
        f"👤 Отправитель: `{detail.get('reporter_id','?')}`\n"
        f"📅 {detail.get('created_at','?')}\n\n"
        f"{LINE}\n\n"
        f"📄 *ТЕКСТ:*\n\n"
        f"{sanitize(str(detail.get('message_text','—')))[:1000]}\n\n"
    )
    if detail.get("media_file_id"):
        text += f"📎 Медиа прикреплено\n"
    text += f"\n{DIVIDER}\n📄 {page + 1} из {len(cons_list)}"

    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=cons_nav_keyboard(bot_key, cons_id, page, len(cons_list))
        )
    except Exception as e:
        logger.error(f"_show_cons_page: {e}")

@router.callback_query(F.data.startswith("cons:nav:"))
async def cons_nav(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    page    = int(parts[3])
    await _show_cons_page(callback, bot_key, page)
    await callback.answer()

@router.callback_query(F.data.startswith("cons:approve:"))
async def cons_approve(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    cons_id = int(parts[3])
    page    = int(parts[4])

    if not await check_permission(callback.from_user.id, "can_moderate_reports"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)

    ok = await client.moderate_cons(cons_id, "approve", callback.from_user.id)
    if ok:
        await callback.answer("✅ Жалоба принята!")
        await log_action(callback.from_user.id, bot_key, "approve_cons", str(cons_id))
        # Удаляем из кэша
        lst = _cons_cache.get(callback.from_user.id, [])
        lst = [c for c in lst if c.get("id") != cons_id]
        _cons_cache[callback.from_user.id] = lst
        if lst:
            await _show_cons_page(callback, bot_key, min(page, len(lst) - 1))
        else:
            await _show_cons_empty(callback, bot_key)
    else:
        await callback.answer("❌ Ошибка!", show_alert=True)

@router.callback_query(F.data.startswith("cons:reject:"))
async def cons_reject(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    cons_id = int(parts[3])
    page    = int(parts[4])

    if not await check_permission(callback.from_user.id, "can_moderate_reports"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)

    ok = await client.moderate_cons(cons_id, "reject", callback.from_user.id)
    if ok:
        await callback.answer("❌ Жалоба отклонена!")
        await log_action(callback.from_user.id, bot_key, "reject_cons", str(cons_id))
        lst = _cons_cache.get(callback.from_user.id, [])
        lst = [c for c in lst if c.get("id") != cons_id]
        _cons_cache[callback.from_user.id] = lst
        if lst:
            await _show_cons_page(callback, bot_key, min(page, len(lst) - 1))
        else:
            await _show_cons_empty(callback, bot_key)
    else:
        await callback.answer("❌ Ошибка!", show_alert=True)

async def _show_cons_empty(callback: CallbackQuery, bot_key: str):
    text = f"{HEADER}\n{DIVIDER}\n\n📝 *ЖАЛОБЫ /cons*\n\n✅ Все жалобы обработаны!\n\n{DIVIDER}\n{FOOTER}"
    kb   = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data=f"back_to_panel:{bot_key}")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

# ============================================
#         АПЕЛЛЯЦИИ
# ============================================

@router.callback_query(F.data.startswith("bot:appeals:"))
async def bot_appeals_list(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    stage   = parts[3] if len(parts) > 3 else "pending"

    if not await check_permission(callback.from_user.id, "can_view_appeals"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    client = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)

    await callback.answer("⚖️ Загрузка апелляций...")
    appeals = await client.get_pending_appeals(stage)
    _appeals_cache[callback.from_user.id] = {"list": appeals, "stage": stage}

    if not appeals:
        stage_name = "новые" if stage == "pending" else "у модераторов"
        text = (
            f"{HEADER}\n{DIVIDER}\n\n⚖️ *АПЕЛЛЯЦИИ ({stage_name})*\n\n"
            f"✅ Нет апелляций на рассмотрении.\n\n{DIVIDER}\n{FOOTER}"
        )
        # Кнопка переключения стадии
        other_stage = "reviewer_approved" if stage == "pending" else "pending"
        other_label = "У модераторов" if stage == "pending" else "Новые"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔄 {other_label}", callback_data=f"bot:appeals:{bot_key}:{other_stage}")],
            [InlineKeyboardButton(text="🔙 НАЗАД", callback_data=f"back_to_panel:{bot_key}")],
        ])
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        return

    await _show_appeal_page(callback, bot_key, 0, stage)

async def _show_appeal_page(callback: CallbackQuery, bot_key: str, page: int, stage: str):
    cache   = _appeals_cache.get(callback.from_user.id, {})
    appeals = cache.get("list", [])
    if not appeals or page >= len(appeals):
        return

    ap   = appeals[page]
    text = (
        f"{HEADER}\n{DIVIDER}\n\n"
        f"⚖️ *АПЕЛЛЯЦИЯ #{ap.get('id','?')}*\n\n"
        f"👤 Заявитель: `{ap.get('appellant_id','?')}`"
        + (f" (@{ap.get('appellant_username','')})" if ap.get("appellant_username") else "")
        + f"\n🎯 Запись: `{ap.get('target_id','?')}`\n"
        f"📅 {ap.get('created_at','?')}\n\n"
        f"{LINE}\n\n📝 *ОБОСНОВАНИЕ:*\n\n{sanitize(str(ap.get('reason','—')))[:800]}\n\n"
    )
    if ap.get("evidence"):
        text += f"🔗 *Доказательства:* {sanitize(str(ap['evidence']))[:200]}\n\n"
    text += f"{DIVIDER}\n⚖️ {page + 1} из {len(appeals)}"

    role = await get_staff_role(callback.from_user.id)
    if stage == "pending":
        kb = appeal_reviewer_kb(bot_key, ap["id"], page, len(appeals))
    else:
        kb = appeal_mod_kb(bot_key, ap["id"], page, len(appeals))

    # Добавляем кнопку переключения стадии
    other_stage = "reviewer_approved" if stage == "pending" else "pending"
    other_label = "У модераторов" if stage == "pending" else "Новые"

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"_show_appeal_page: {e}")

@router.callback_query(F.data.startswith("aprev:nav:"))
async def appeal_nav(callback: CallbackQuery):
    parts   = callback.data.split(":")
    bot_key = parts[2]
    stage   = parts[3]
    page    = int(parts[4])
    _appeals_cache.setdefault(callback.from_user.id, {})["stage"] = stage
    await _show_appeal_page(callback, bot_key, page, stage)
    await callback.answer()

@router.callback_query(F.data.startswith("aprev:ok:"))
async def appeal_reviewer_ok(callback: CallbackQuery):
    parts     = callback.data.split(":")
    bot_key   = parts[2]
    appeal_id = int(parts[3])
    page      = int(parts[4])

    if not await check_permission(callback.from_user.id, "can_view_appeals"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)

    # Здесь логика одобрения на уровне рассмотрителя реализована в боте
    # из админ-центра мы только информируем — прямого API нет, поэтому показываем инструкцию
    await callback.answer(
        "ℹ️ Для рассмотрения апелляций используйте кнопки прямо в боте (чат рассмотрителей).",
        show_alert=True
    )

@router.callback_query(F.data.startswith("aprev:no:"))
async def appeal_reviewer_no(callback: CallbackQuery):
    await callback.answer(
        "ℹ️ Для рассмотрения апелляций используйте кнопки прямо в боте (чат рассмотрителей).",
        show_alert=True
    )

@router.callback_query(F.data.startswith("apmod:ok:"))
async def appeal_mod_ok(callback: CallbackQuery):
    await callback.answer(
        "ℹ️ Для модерации апелляций используйте кнопки прямо в боте (чат модераторов).",
        show_alert=True
    )

@router.callback_query(F.data.startswith("apmod:no:"))
async def appeal_mod_no(callback: CallbackQuery):
    await callback.answer(
        "ℹ️ Для модерации апелляций используйте кнопки прямо в боте (чат модераторов).",
        show_alert=True
    )

# ============================================
#         ДОБАВЛЕНИЕ В БАЗУ
# ============================================

@router.callback_query(F.data.startswith("bot:adddb:"))
async def bot_adddb_start(callback: CallbackQuery, state: FSMContext):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_db"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    await state.update_data(bot_key=bot_key)
    await state.set_state(AddToDbState.identifier)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n➕ *ДОБАВЛЕНИЕ В БАЗУ*\n\nВведите @username или ID:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(AddToDbState.identifier)
async def adddb_identifier(message: Message, state: FSMContext):
    data    = await state.get_data()
    bot_key = data.get("bot_key")
    ident   = (message.text or "").strip().lstrip("@")
    if not re.match(r"^[a-zA-Z0-9_]{4,32}$|^\d{5,15}$", ident):
        await message.answer("❌ Неверный формат! Введите ещё раз:", reply_markup=cancel_keyboard())
        return
    await state.update_data(identifier=ident)
    await state.set_state(AddToDbState.status)
    await message.answer(
        f"🎯 Цель: `{ident}`\n\nВыберите статус:",
        parse_mode="Markdown",
        reply_markup=db_statuses_keyboard(bot_key)
    )

@router.callback_query(F.data.startswith("adddb_s:"))
async def adddb_status(callback: CallbackQuery, state: FSMContext):
    parts   = callback.data.split(":")
    bot_key = parts[1]
    status  = parts[2]
    await state.update_data(status=status)
    await state.set_state(AddToDbState.reason)
    try:
        await callback.message.edit_text(
            f"📝 Статус: *{status}*\n\nВведите причину добавления:",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await callback.answer()

@router.message(AddToDbState.reason)
async def adddb_reason(message: Message, state: FSMContext):
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("❌ Введите причину:")
        return
    await state.update_data(reason=reason)
    await state.set_state(AddToDbState.evidence)
    await message.answer("🔗 Ссылка на доказательство или «-»:")

@router.message(AddToDbState.evidence)
async def adddb_evidence(message: Message, state: FSMContext):
    data     = await state.get_data()
    bot_key  = data.get("bot_key")
    ident    = data.get("identifier")
    status   = data.get("status")
    reason   = data.get("reason")
    evidence = (message.text or "").strip()
    await state.clear()

    # Добавление через ScamBase бота напрямую (через API нет прямого эндпоинта добавления,
    # поэтому выводим инструкцию — добавьте эндпоинт /api/db/add в scambase если нужно)
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"📋 *ДАННЫЕ ДЛЯ ДОБАВЛЕНИЯ*\n\n"
        f"🆔 Цель: `{ident}`\n"
        f"📊 Статус: *{status}*\n"
        f"📝 Причина: {sanitize(reason)}\n"
        f"🔗 Доказательства: {sanitize(evidence) if evidence != '-' else '—'}\n\n"
        f"{DIVIDER}\n\n"
        f"⚡ Используйте команду `/addscam` в основном боте или добавьте эндпоинт `/api/db/add`.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")]
        ])
    )
    await log_action(message.from_user.id, bot_key, "adddb_request",
                     f"{ident} → {status}: {reason[:50]}")

# ============================================
#         УДАЛЕНИЕ ИЗ БАЗЫ
# ============================================

@router.callback_query(F.data.startswith("bot:deldb:"))
async def bot_deldb_start(callback: CallbackQuery, state: FSMContext):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_db"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    await state.update_data(bot_key=bot_key)
    await state.set_state(DelFromDbState.identifier)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n🗑 *УДАЛЕНИЕ ИЗ БАЗЫ*\n\nВведите @username или ID:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(DelFromDbState.identifier)
async def deldb_execute(message: Message, state: FSMContext):
    data    = await state.get_data()
    bot_key = data.get("bot_key")
    ident   = (message.text or "").strip().lstrip("@")
    await state.clear()
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"📋 *ЗАПРОС НА УДАЛЕНИЕ*\n\n"
        f"🆔 Цель: `{ident}`\n\n"
        f"⚡ Используйте команду `/delscam {ident}` в основном боте.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")]
        ])
    )
    await log_action(message.from_user.id, bot_key, "deldb_request", ident)

# ============================================
#         РАССЫЛКА
# ============================================

@router.callback_query(F.data.startswith("bot:broadcast:"))
async def bot_broadcast_start(callback: CallbackQuery, state: FSMContext):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_broadcast"):
        return await callback.answer("⛔ НЕТ ДОСТУПА! Только Главный Администратор.", show_alert=True)
    await state.update_data(bot_key=bot_key)
    await state.set_state(BroadcastState.text)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n"
            f"📢 *РАССЫЛКА*\n\n"
            f"Введите текст рассылки (Markdown поддерживается).\n«-» для отмены:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(BroadcastState.text)
async def bot_broadcast_execute(message: Message, state: FSMContext):
    data    = await state.get_data()
    bot_key = data.get("bot_key")
    text    = (message.text or "").strip()
    await state.clear()
    if text == "-":
        await message.answer("❌ Рассылка отменена.")
        return
    await message.answer(
        f"{HEADER}\n{DIVIDER}\n\n"
        f"📢 *РАССЫЛКА*\n\n"
        f"Текст принят. Используйте команду `/broadcast` в основном боте для рассылки.\n\n"
        f"*Ваш текст:*\n{sanitize(text[:300])}\n\n"
        f"{DIVIDER}\n{FOOTER}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К ПАНЕЛИ", callback_data=f"back_to_panel:{bot_key}")]
        ])
    )
    await log_action(message.from_user.id, bot_key, "broadcast_request", text[:100])

# ============================================
#         ЭКСПОРТ CSV
# ============================================

@router.callback_query(F.data.startswith("bot:export:"))
async def bot_export(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_db"):
        return await callback.answer("⛔ НЕТ ДОСТУПА!", show_alert=True)
    await callback.answer("📊 Используйте /export в основном боте для скачивания CSV.", show_alert=True)
    await log_action(callback.from_user.id, bot_key, "export_request", "csv")

# ============================================
#         ОБНОВИТЬ ДАННЫЕ
# ============================================

@router.callback_query(F.data.startswith("bot:refresh:"))
async def bot_refresh(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    client  = get_client(bot_key)
    if not client:
        return await callback.answer("❌ API недоступен!", show_alert=True)
    stats = await client.get_stats()
    if "error" in stats:
        await callback.answer(f"❌ {stats['error']}", show_alert=True)
    else:
        await callback.answer("✅ Данные обновлены!")
    cfg  = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{cfg.get('emoji','🤖')} *{cfg.get('name', bot_key)}*\n{DIVIDER}\n\n"
        f"✅ API подключён\n\n{DIVIDER}\n\n⚔️ ВЫБЕРИТЕ ДЕЙСТВИЕ:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=bot_panel_keyboard(bot_key))
    except Exception:
        pass

# ============================================
#         ОФОРМЛЕНИЕ — БАННЕРЫ
# ============================================

@router.callback_query(F.data.startswith("bot:design:"))
async def design_menu(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_design"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    cfg  = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{HEADER}\n{DIVIDER}\n\n🎨 *КОНСТРУКТОР ОФОРМЛЕНИЯ*\n\n"
        f"Бот: *{cfg.get('name', bot_key)}*\n\n{DIVIDER}\n\nВыберите раздел:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=design_menu_keyboard(bot_key))
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("design:banners:"))
async def design_banners(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_design"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    cfg  = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{HEADER}\n{DIVIDER}\n\n🖼️ *РЕДАКТОР БАННЕРОВ*\n\n"
        f"Бот: *{cfg.get('name', bot_key)}*\n\nВыберите баннер для замены:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=banners_list_keyboard(bot_key))
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("banner:edit:"))
async def banner_edit(callback: CallbackQuery, state: FSMContext):
    parts       = callback.data.split(":")
    bot_key     = parts[2]
    banner_name = parts[3]
    if not await check_permission(callback.from_user.id, "can_manage_design"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    label = dict(BANNER_LIST).get(banner_name, banner_name)
    await state.update_data(bot_key=bot_key, banner_name=banner_name)
    await state.set_state(DesignBannerState.waiting)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n✏️ *ЗАМЕНА БАННЕРА*\n\n"
            f"📌 *{label}*\n\n📤 Отправьте GIF, фото или видео:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(DesignBannerState.waiting)
async def banner_save(message: Message, state: FSMContext):
    if not await check_permission(message.from_user.id, "can_manage_design"):
        await state.clear()
        return await message.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!")
    data        = await state.get_data()
    bot_key     = data.get("bot_key")
    banner_name = data.get("banner_name")
    file_id = file_type = None
    if message.animation:
        file_id, file_type = message.animation.file_id, "gif"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
    elif message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    if not file_id:
        await message.answer("❌ Отправьте GIF, фото или видео!", reply_markup=cancel_keyboard())
        return
    client = get_client(bot_key)
    if not client:
        await state.clear()
        return await message.answer("❌ API недоступен!")
    ok = await client.update_banner(banner_name, file_id, file_type)
    label = dict(BANNER_LIST).get(banner_name, banner_name)
    if ok:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✅ *БАННЕР ОБНОВЛЁН!*\n\n📌 *{label}*\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К БАННЕРАМ", callback_data=f"design:banners:{bot_key}")]
            ])
        )
        await log_action(message.from_user.id, bot_key, "update_banner", banner_name)
    else:
        await message.answer("❌ ОШИБКА СОХРАНЕНИЯ.")
    await state.clear()

# ============================================
#         ОФОРМЛЕНИЕ — ТЕКСТЫ
# ============================================

@router.callback_query(F.data.startswith("design:texts:"))
async def design_texts(callback: CallbackQuery):
    bot_key = callback.data.split(":")[2]
    if not await check_permission(callback.from_user.id, "can_manage_design"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    cfg  = BOTS_API_CONFIG.get(bot_key, {})
    text = (
        f"{HEADER}\n{DIVIDER}\n\n💬 *РЕДАКТОР ТЕКСТОВ*\n\n"
        f"Бот: *{cfg.get('name', bot_key)}*\n\nВыберите текст:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown",
                                         reply_markup=texts_list_keyboard(bot_key))
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("text:edit:"))
async def text_edit(callback: CallbackQuery, state: FSMContext):
    parts     = callback.data.split(":")
    bot_key   = parts[2]
    text_name = parts[3]
    if not await check_permission(callback.from_user.id, "can_manage_design"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    label = dict(TEXT_LIST).get(text_name, text_name)
    await state.update_data(bot_key=bot_key, text_name=text_name)
    await state.set_state(DesignTextState.waiting)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n✏️ *РЕДАКТИРОВАНИЕ ТЕКСТА*\n\n"
            f"📌 *{label}*\n\n📝 Отправьте новый текст (Markdown).\n"
            f"Отправьте `-` чтобы сбросить к стандартному:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(DesignTextState.waiting)
async def text_save(message: Message, state: FSMContext):
    if not await check_permission(message.from_user.id, "can_manage_design"):
        await state.clear()
        return await message.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!")
    data      = await state.get_data()
    bot_key   = data.get("bot_key")
    text_name = data.get("text_name")
    new_text  = (message.text or "").strip()
    if new_text == "-":
        new_text = ""
    client = get_client(bot_key)
    if not client:
        await state.clear()
        return await message.answer("❌ API недоступен!")
    ok    = await client.update_text(text_name, new_text)
    label = dict(TEXT_LIST).get(text_name, text_name)
    if ok:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✅ *ТЕКСТ ОБНОВЛЁН!*\n\n📌 *{label}*\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К ТЕКСТАМ", callback_data=f"design:texts:{bot_key}")]
            ])
        )
        await log_action(message.from_user.id, bot_key, "update_text", text_name)
    else:
        await message.answer("❌ ОШИБКА СОХРАНЕНИЯ.")
    await state.clear()

# ============================================
#         УПРАВЛЕНИЕ ПЕРСОНАЛОМ
# ============================================

@router.callback_query(F.data == "center:staff")
async def center_staff_menu(callback: CallbackQuery):
    if not await check_permission(callback.from_user.id, "can_manage_staff"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n👥 *УПРАВЛЕНИЕ ПЕРСОНАЛОМ*\n\n{DIVIDER}\n\n⚔️ ВЫБЕРИТЕ ДЕЙСТВИЕ:",
            parse_mode="Markdown", reply_markup=staff_menu_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "staff:list")
async def staff_list(callback: CallbackQuery):
    staff = await get_staff_list()
    if not staff:
        text = f"{HEADER}\n{DIVIDER}\n\n👥 *СОСТАВ АДМИНИСТРАЦИИ*\n\n📭 Штат пуст.\n\n{DIVIDER}\n{FOOTER}"
    else:
        text = f"{HEADER}\n{DIVIDER}\n\n👥 *СОСТАВ АДМИНИСТРАЦИИ:*\n\n"
        for s in staff:
            role_info = ROLES.get(s.get("role", ""), {})
            role_name = role_info.get("name", s.get("role", "?"))
            text += (
                f"▸ *{role_name}*\n"
                f"  ID: `{s.get('telegram_id','?')}`\n"
                f"  Username: {s.get('username','—')}\n"
                f"  Добавлен: {s.get('added_at','?')}\n\n"
            )
        text += f"{DIVIDER}\n{FOOTER}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="center:staff")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "staff:add")
async def staff_add_start(callback: CallbackQuery, state: FSMContext):
    if not await check_permission(callback.from_user.id, "can_manage_staff"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    await state.set_state(StaffAddState.user_id)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n➕ *ПРИНЯТИЕ В ШТАТ*\n\n📤 Отправьте Telegram ID кандидата:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(StaffAddState.user_id)
async def staff_add_get_id(message: Message, state: FSMContext):
    if not await check_permission(message.from_user.id, "can_manage_staff"):
        await state.clear()
        return await message.answer("⛔ ДОСТУП ЗАКРЫТ.")
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        return await message.answer("❌ Отправьте числовой Telegram ID!", reply_markup=cancel_keyboard())
    if user_id == MAIN_ADMIN_ID:
        await state.clear()
        return await message.answer("❌ Нельзя изменить роль Верховного Администратора!")
    await state.update_data(user_id=user_id)
    await state.set_state(StaffAddState.role)
    await message.answer("👑 Выберите роль:", reply_markup=staff_roles_keyboard())

@router.callback_query(F.data.startswith("staffrole:"))
async def staff_add_role(callback: CallbackQuery, state: FSMContext):
    role_key = callback.data.split(":")[1]
    if role_key == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено.")
        return await callback.answer()
    data    = await state.get_data()
    user_id = data.get("user_id")
    # Получаем username через Telegram API
    username = None
    try:
        chat     = await callback.message.bot.get_chat(user_id)
        username = chat.username or chat.first_name
    except Exception:
        username = str(user_id)
    ok = await add_staff(user_id, username or str(user_id), role_key, callback.from_user.id)
    if ok:
        role_name = ROLES.get(role_key, {}).get("name", role_key)
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n✅ *СОТРУДНИК ПРИНЯТ!*\n\n"
            f"ID: `{user_id}`\n👤 {username or '—'}\nРоль: *{role_name}*\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
        await log_action(callback.from_user.id, "center", "add_staff",
                         f"ID: {user_id}, Роль: {role_key}")
    else:
        await callback.answer("❌ Ошибка при добавлении!", show_alert=True)
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "staff:remove")
async def staff_remove_start(callback: CallbackQuery, state: FSMContext):
    if not await check_permission(callback.from_user.id, "can_manage_staff"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    await state.set_state(StaffRemoveState.user_id)
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n🗑 *ИСКЛЮЧЕНИЕ ИЗ ШТАТА*\n\n📤 Отправьте Telegram ID сотрудника:",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

@router.message(StaffRemoveState.user_id)
async def staff_remove_execute(message: Message, state: FSMContext):
    if not await check_permission(message.from_user.id, "can_manage_staff"):
        await state.clear()
        return await message.answer("⛔ ДОСТУП ЗАКРЫТ.")
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        return await message.answer("❌ Отправьте числовой Telegram ID!", reply_markup=cancel_keyboard())
    if user_id == MAIN_ADMIN_ID:
        await state.clear()
        return await message.answer("❌ Верховного Администратора исключить нельзя!")
    ok = await remove_staff(user_id)
    if ok:
        await message.answer(
            f"{HEADER}\n{DIVIDER}\n\n✅ *СОТРУДНИК ИСКЛЮЧЁН!*\n\nID: `{user_id}`\n\n{DIVIDER}\n{FOOTER}",
            parse_mode="Markdown"
        )
        await log_action(message.from_user.id, "center", "remove_staff", f"ID: {user_id}")
    else:
        await message.answer("❌ Сотрудник не найден или ошибка.")
    await state.clear()

@router.callback_query(F.data == "staff:cancel")
async def staff_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("🚫 Отменено")
    try:
        await callback.message.edit_text(
            f"{HEADER}\n{DIVIDER}\n\n👥 *УПРАВЛЕНИЕ ПЕРСОНАЛОМ*\n\n{DIVIDER}\n\n⚔️ ВЫБЕРИТЕ ДЕЙСТВИЕ:",
            parse_mode="Markdown", reply_markup=staff_menu_keyboard()
        )
    except Exception:
        pass

# ============================================
#         ЛОГ ДЕЙСТВИЙ
# ============================================

@router.callback_query(F.data == "center:logs")
async def center_logs(callback: CallbackQuery):
    if not await check_permission(callback.from_user.id, "can_view_logs"):
        return await callback.answer("⛔ ТОЛЬКО ГЛАВНЫЙ АДМИН!", show_alert=True)
    logs = await get_recent_logs(15)
    if not logs:
        text = f"{HEADER}\n{DIVIDER}\n\n📋 ЛОГ ДЕЙСТВИЙ ПУСТ\n\n{DIVIDER}\n{FOOTER}"
    else:
        text = f"{HEADER}\n{DIVIDER}\n\n📋 *ПОСЛЕДНИЕ 15 ДЕЙСТВИЙ:*\n\n"
        for entry in logs:
            text += (
                f"▸ `{entry['created_at']}`\n"
                f"  👤 {sanitize(str(entry['username']))}\n"
                f"  🎯 `{entry['action']}` → {sanitize(str(entry['details']))[:80]}\n\n"
            )
        text += f"{DIVIDER}\n{FOOTER}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data="center:logs")],
        [InlineKeyboardButton(text="🔙 НАЗАД",    callback_data="back_to_bots")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

# ============================================
#         ЗАПУСК
# ============================================

async def main():
    print("╔══════════════════════════════════════════════╗")
    print("  ⚜️  ARION COMMAND CENTER v5.0  ⚜️")
    print("  ★ ▬▬▬▬▬▬▬▬▬▬ ★")
    print("  Интеграция через HTTP API | Апелляции | Поиск")
    print("╚══════════════════════════════════════════════╝")

    if not ADMIN_CENTER_TOKEN:
        print("❌ Ошибка: укажите ADMIN_CENTER_TOKEN в .env!")
        print("\nПример .env:")
        print("ADMIN_CENTER_TOKEN=ваш_токен_бота")
        print("MAIN_ADMIN_ID=123456789")
        print("SCAMBASE_API_URL=http://localhost:8080")
        print("SCAMBASE_API_SECRET=ваш_секрет")
        return

    if MAIN_ADMIN_ID == 0:
        print("❌ Ошибка: укажите MAIN_ADMIN_ID в .env!")
        return

    await init_center_db()

    # Проверяем подключение к API
    for bot_key, cfg in BOTS_API_CONFIG.items():
        if cfg.get("enabled") and cfg.get("api_secret"):
            client = get_client(bot_key)
            if client:
                stats = await client.get_stats()
                if "error" in stats:
                    logger.warning(f"API {bot_key} недоступен: {stats['error']}")
                else:
                    logger.info(f"✅ API {bot_key} подключён")

    bot = Bot(token=ADMIN_CENTER_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: loop.stop())
        except NotImplementedError:
            pass

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запуск админ-центра"),
    ])

    logger.info("🟢 АДМИН-ЦЕНТР v5.0 ЗАПУЩЕН!")
    print("✅ Админ-центр готов к работе!")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        raise
    finally:
        await close_all_clients()

if __name__ == "__main__":
    asyncio.run(main())
