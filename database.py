# -*- coding: utf-8 -*-
"""
database.py — слой доступа к SQLite для прототипа «Умный гардероб».

Таблицы:
  - items        — вещи в гардеробе
  - outfits      — опционально: сохранённые комплекты (связи id вещей)
  - schedule     — уроки на день (упорядоченный список)
  - weather      — запись о погоде «на сегодня»
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

# База лежит рядом с этим файлом (корень проекта)
DB_PATH = Path(__file__).resolve().parent / "wardrobe.db"


def _today_iso() -> str:
    return date.today().isoformat()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Контекстный менеджер соединения: row_factory + foreign keys."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('top', 'bottom', 'shoes', 'outer')),
                color TEXT NOT NULL,
                season TEXT NOT NULL,
                photo TEXT,
                status TEXT NOT NULL DEFAULT 'clean'
                    CHECK (status IN ('clean', 'dirty')),
                last_used TEXT
            );

            -- Опционально: сохранённый подобранный комплект
            CREATE TABLE IF NOT EXISTS outfits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                label TEXT,
                top_id INTEGER,
                bottom_id INTEGER,
                shoes_id INTEGER,
                outer_id INTEGER,
                FOREIGN KEY (top_id) REFERENCES items(id),
                FOREIGN KEY (bottom_id) REFERENCES items(id),
                FOREIGN KEY (shoes_id) REFERENCES items(id),
                FOREIGN KEY (outer_id) REFERENCES items(id)
            );

            -- Расписание на конкретную дату (один день — несколько строк)
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_date TEXT NOT NULL,
                slot_index INTEGER NOT NULL,
                subject TEXT NOT NULL,
                activity TEXT NOT NULL
                    CHECK (activity IN ('sitting', 'sports', 'walking', 'mixed')),
                UNIQUE(day_date, slot_index)
            );

            -- Одна строка на дату: актуальная погода для логики рекомендаций
            CREATE TABLE IF NOT EXISTS weather (
                day_date TEXT PRIMARY KEY,
                temp_c REAL NOT NULL,
                feels_like_c REAL NOT NULL,
                condition TEXT NOT NULL,
                precip INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
            CREATE INDEX IF NOT EXISTS idx_items_type ON items(type);
            CREATE INDEX IF NOT EXISTS idx_schedule_day ON schedule(day_date);
            """
        )


def _table_empty(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
    return row is None


def seed_if_empty() -> None:
    """
    Заполняет мок-данными при первом запуске (если таблицы пустые).
    Идемпотентно: не дублирует, если уже есть записи.
    """
    today = _today_iso()
    with get_connection() as conn:
        if not _table_empty(conn, "items"):
            return

        cur = conn.cursor()
        # Несколько чистых вещей + одна «грязная» для демонстрации фильтра
        demo_items: list[tuple[str, str, str, str, str | None, str]] = [
            ("Белая футболка", "top", "белый", "summer", None, "clean"),
            ("Серый свитшот", "top", "серый", "all", None, "clean"),
            ("Тёплая кофта", "top", "синий", "winter", None, "clean"),
            ("Джинсы классические", "bottom", "синий", "all", None, "clean"),
            ("Спортивные штаны", "bottom", "чёрный", "all", None, "dirty"),
            ("Кроссовки", "shoes", "белый", "all", None, "clean"),
            ("Ботинки", "shoes", "коричневый", "winter", None, "clean"),
            ("Лёгкая куртка", "outer", "оливковый", "spring", None, "clean"),
            ("Пуховик", "outer", "чёрный", "winter", None, "clean"),
        ]
        cur.executemany(
            """
            INSERT INTO items (name, type, color, season, photo, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            demo_items,
        )

        # Расписание на сегодня (типичный учебный день)
        lessons = [
            (0, "Алгебра", "sitting"),
            (1, "Литература", "sitting"),
            (2, "Физкультура", "sports"),
            (3, "История", "sitting"),
            (4, "Информатика", "sitting"),
            (5, "Английский", "sitting"),
        ]
        cur.executemany(
            """
            INSERT INTO schedule (day_date, slot_index, subject, activity)
            VALUES (?, ?, ?, ?)
            """,
            [(today, i, sub, act) for i, sub, act in lessons],
        )

        # Погода на сегодня (мок)
        cur.execute(
            """
            INSERT INTO weather (day_date, temp_c, feels_like_c, condition, precip)
            VALUES (?, ?, ?, ?, ?)
            """,
            (today, 8.0, 5.0, "облачно, небольшой ветер", 0),
        )


# --- Items -----------------------------------------------------------------


def list_items(status: Optional[str] = None) -> list[dict[str, Any]]:
    """Список вещей; status: 'clean' | 'dirty' | None — все."""
    sql = "SELECT * FROM items ORDER BY type, name"
    args: tuple[Any, ...] = ()
    if status in ("clean", "dirty"):
        sql = "SELECT * FROM items WHERE status = ? ORDER BY type, name"
        args = (status,)
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_item(item_id: int) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_dict(row) if row else None


def create_item(
    name: str,
    item_type: str,
    color: str,
    season: str,
    photo: Optional[str] = None,
    status: str = "clean",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO items (name, type, color, season, photo, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, item_type, color, season, photo, status),
        )
        return int(cur.lastrowid)


def update_item(item_id: int, **fields: Any) -> bool:
    """Частичное обновление разрешённых полей."""
    allowed = {"name", "type", "color", "season", "photo", "status", "last_used"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    cols = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [item_id]
    with get_connection() as conn:
        cur = conn.execute(f"UPDATE items SET {cols} WHERE id = ?", values)
        return cur.rowcount > 0


def delete_item(item_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


def mark_items_status(item_ids: Iterable[int], status: str) -> int:
    """Массово меняет статус (clean/dirty). Возвращает число обновлённых строк."""
    ids = list(item_ids)
    if not ids or status not in ("clean", "dirty"):
        return 0
    placeholders = ",".join("?" * len(ids))
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE items SET status = ? WHERE id IN ({placeholders})",
            [status, *ids],
        )
        return cur.rowcount


def mark_items_dirty(item_ids: Iterable[int]) -> int:
    return mark_items_status(item_ids, "dirty")


def wash_all_dirty() -> int:
    """«Постирать всё»: все грязные -> чистые."""
    with get_connection() as conn:
        cur = conn.execute("UPDATE items SET status = 'clean' WHERE status = 'dirty'")
        return cur.rowcount


def set_last_used_now(item_ids: Iterable[int]) -> int:
    """Отмечает время последнего использования (ISO)."""
    now = datetime.now().isoformat(timespec="seconds")
    ids = list(item_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE items SET last_used = ? WHERE id IN ({placeholders})",
            [now, *ids],
        )
        return cur.rowcount


# --- Schedule --------------------------------------------------------------


def get_schedule_for_day(day_date: Optional[str] = None) -> list[dict[str, Any]]:
    d = day_date or _today_iso()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, day_date, slot_index, subject, activity
            FROM schedule
            WHERE day_date = ?
            ORDER BY slot_index
            """,
            (d,),
        ).fetchall()
        return [dict(r) for r in rows]


def replace_schedule_for_day(
    day_date: str, lessons: list[dict[str, Any]]
) -> None:
    """
    lessons: [{"subject": "...", "activity": "sitting|sports|..."}, ...]
    slot_index выставляется по порядку списка.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM schedule WHERE day_date = ?", (day_date,))
        for idx, lesson in enumerate(lessons):
            conn.execute(
                """
                INSERT INTO schedule (day_date, slot_index, subject, activity)
                VALUES (?, ?, ?, ?)
                """,
                (
                    day_date,
                    idx,
                    str(lesson.get("subject", "Урок")),
                    str(lesson.get("activity", "sitting")),
                ),
            )


# --- Weather ---------------------------------------------------------------


def get_weather(day_date: Optional[str] = None) -> Optional[dict[str, Any]]:
    d = day_date or _today_iso()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM weather WHERE day_date = ?", (d,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["precip"] = bool(data.get("precip", 0))
        return data


def upsert_weather(
    day_date: str,
    temp_c: float,
    feels_like_c: float,
    condition: str,
    precip: bool = False,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO weather (day_date, temp_c, feels_like_c, condition, precip)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day_date) DO UPDATE SET
                temp_c = excluded.temp_c,
                feels_like_c = excluded.feels_like_c,
                condition = excluded.condition,
                precip = excluded.precip
            """,
            (day_date, temp_c, feels_like_c, condition, 1 if precip else 0),
        )


# --- Outfits (сохранённые комплекты) ---------------------------------------


def save_outfit(
    top_id: Optional[int],
    bottom_id: Optional[int],
    shoes_id: Optional[int],
    outer_id: Optional[int],
    label: Optional[str] = None,
) -> int:
    created = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO outfits (created_at, label, top_id, bottom_id, shoes_id, outer_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (created, label, top_id, bottom_id, shoes_id, outer_id),
        )
        return int(cur.lastrowid)


def list_saved_outfits(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT o.*,
                   t.name AS top_name, b.name AS bottom_name,
                   s.name AS shoes_name, x.name AS outer_name
            FROM outfits o
            LEFT JOIN items t ON o.top_id = t.id
            LEFT JOIN items b ON o.bottom_id = b.id
            LEFT JOIN items s ON o.shoes_id = s.id
            LEFT JOIN items x ON o.outer_id = x.id
            ORDER BY o.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def _row_to_dict(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    if "precip" in d:
        d["precip"] = bool(d.get("precip", 0))
    return d


def init_app_data() -> None:
    """Точка входа для приложения: схема + сиды."""
    init_db()
    seed_if_empty()
