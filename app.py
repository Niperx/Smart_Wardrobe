# -*- coding: utf-8 -*-
"""
app.py — минимальный сервер Flask для прототипа «Умный гардероб».

Запуск из корня проекта:
    python app.py

API префикс: /api/...
Статические страницы и ассеты раздаются из корня проекта (index.html, *.css, *.js).
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import database as db

# Корень проекта (рядом с app.py)
ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"

app = Flask(__name__, static_folder=None)


def _today() -> str:
    return date.today().isoformat()


@app.before_request
def _ensure_db() -> None:
    """Ленивая инициализация БД при первом запросе."""
    # Выполняется на каждый запрос — дёшево: только проверка файла/PRAGMA
    db.init_app_data()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# --- Раздача фронтенда ------------------------------------------------------


@app.route("/")
def index_page():
    return send_from_directory(ROOT, "index.html")


@app.route("/<path:name>")
def static_or_html(name: str):
    """Раздаём только безопасные файлы из корня (html, css, js, изображения в uploads)."""
    if ".." in name or name.startswith("\\"):
        return jsonify({"error": "bad path"}), 400
    allowed_root_files = {
        "index.html",
        "add_item.html",
        "schedule.html",
        "styles.css",
        "script.js",
    }
    if name in allowed_root_files:
        return send_from_directory(ROOT, name)
    if name.startswith("uploads/"):
        sub = name[len("uploads/") :]
        if ".." in sub:
            return jsonify({"error": "bad path"}), 400
        return send_from_directory(ROOT / "uploads", sub)
    return jsonify({"error": "not found"}), 404


# --- API: вещи --------------------------------------------------------------


@app.get("/api/items")
def api_list_items():
    status = request.args.get("status")
    items = db.list_items(status=status if status in ("clean", "dirty") else None)
    return jsonify({"items": items})


@app.post("/api/items")
def api_create_item():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    item_type = (data.get("type") or "").strip()
    color = (data.get("color") or "").strip()
    season = (data.get("season") or "all").strip()
    photo_data = data.get("photo")  # base64 data URL или путь

    if not name or item_type not in ("top", "bottom", "shoes", "outer"):
        return jsonify({"error": "Нужны name и корректный type (top|bottom|shoes|outer)"}), 400

    photo_path: str | None = None
    if isinstance(photo_data, str) and photo_data.startswith("data:image"):
        # data:image/png;base64,....
        try:
            header, b64 = photo_data.split(",", 1)
            ext = "png"
            if "jpeg" in header or "jpg" in header:
                ext = "jpg"
            raw = base64.b64decode(b64)
            fname = f"{uuid.uuid4().hex}.{ext}"
            fpath = UPLOAD_DIR / fname
            fpath.write_bytes(raw)
            photo_path = f"uploads/{fname}"
        except Exception:
            return jsonify({"error": "Некорректное фото (base64)"}), 400
    elif isinstance(photo_data, str) and photo_data:
        photo_path = photo_data

    new_id = db.create_item(
        name=name,
        item_type=item_type,
        color=color,
        season=season,
        photo=photo_path,
        status="clean",
    )
    return jsonify({"id": new_id}), 201


@app.patch("/api/items/<int:item_id>")
def api_patch_item(item_id: int):
    data = request.get_json(force=True, silent=True) or {}
    ok = db.update_item(item_id, **{k: data[k] for k in ("name", "type", "color", "season", "photo", "status", "last_used") if k in data})
    if not ok:
        return jsonify({"error": "не обновлено"}), 400
    return jsonify({"ok": True, "item": db.get_item(item_id)})


@app.delete("/api/items/<int:item_id>")
def api_delete_item(item_id: int):
    if not db.delete_item(item_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# --- API: расписание и погода -----------------------------------------------


@app.get("/api/schedule")
def api_get_schedule():
    day = request.args.get("date") or _today()
    return jsonify({"date": day, "lessons": db.get_schedule_for_day(day)})


@app.put("/api/schedule")
def api_put_schedule():
    data = request.get_json(force=True, silent=True) or {}
    day = (data.get("date") or _today()).strip()
    lessons = data.get("lessons") or []
    if not isinstance(lessons, list):
        return jsonify({"error": "lessons должен быть массивом"}), 400
    db.replace_schedule_for_day(day, lessons)
    return jsonify({"ok": True, "date": day, "lessons": db.get_schedule_for_day(day)})


@app.get("/api/weather")
def api_get_weather():
    day = request.args.get("date") or _today()
    w = db.get_weather(day)
    if not w:
        return jsonify({"error": "нет данных — вызовите POST /api/weather/refresh"}), 404
    return jsonify(w)


@app.post("/api/weather/refresh")
def api_refresh_weather():
    """
    Имитация внешнего API прогноза: генерирует правдоподобные значения на дату.
    (Без сетевых запросов — стабильно для учебного стенда.)
    """
    from random import Random

    day = (request.get_json(force=True, silent=True) or {}).get("date") or _today()
    rng = Random(sum(ord(c) for c in day) % 10000 + 13)
    temp = round(rng.uniform(-5, 22), 1)
    feels = round(temp + rng.uniform(-3, 2), 1)
    conditions = [
        "ясно",
        "переменная облачность",
        "облачно",
        "небольшой дождь",
        "снегопад",
        "туман",
    ]
    cond = rng.choice(conditions)
    precip = cond in ("небольшой дождь", "снегопад")
    db.upsert_weather(day, temp_c=temp, feels_like_c=feels, condition=cond, precip=precip)
    return jsonify(db.get_weather(day))


# --- API: рекомендации (временная логика; позже — recommendation.py) -------


def _pick_clean(items: list[dict], item_type: str) -> list[dict]:
    return [i for i in items if i["type"] == item_type and i.get("status") == "clean"]


def _day_has_sports(lessons: list[dict]) -> bool:
    return any((l.get("activity") == "sports") for l in lessons)


def simple_recommend_outfit(day_date: str | None = None) -> dict:
    """
    Упрощённый подбор до подключения recommendation.py:
    - только чистые вещи;
    - при спорте — приоритет спортивного низа, если есть в названии/типе;
    - температура: outer при feels_like < 12 или осадках;
    - сезон: грубое соответствие месяцу.
    """
    d = day_date or _today()
    weather = db.get_weather(d)
    if not weather:
        db.upsert_weather(d, 10.0, 8.0, "облачно (авто)", False)
        weather = db.get_weather(d)

    lessons = db.get_schedule_for_day(d)
    items = db.list_items()
    clean = [i for i in items if i.get("status") == "clean"]
    sports = _day_has_sports(lessons)

    bottoms = _pick_clean(clean, "bottom")
    if sports:
        bottoms.sort(
            key=lambda x: (0 if "спорт" in x["name"].lower() else 1, x["name"])
        )
    tops = _pick_clean(clean, "top")
    shoes_list = _pick_clean(clean, "shoes")
    outers = _pick_clean(clean, "outer")

    def first_or_none(seq: list[dict]) -> dict | None:
        return seq[0] if seq else None

    top = first_or_none(tops)
    bottom = first_or_none(bottoms)
    shoes = first_or_none(shoes_list)

    feels = float(weather.get("feels_like_c", weather.get("temp_c", 10)))
    precip = bool(weather.get("precip"))
    need_outer = feels < 12 or precip
    outer = first_or_none(outers) if need_outer else None

    outfit = {
        "top": top,
        "bottom": bottom,
        "shoes": shoes,
        "outer": outer,
        "meta": {
            "day_date": d,
            "sports_day": sports,
            "need_outer": need_outer,
            "feels_like_c": feels,
        },
    }
    return {"outfit": outfit, "weather": weather, "schedule": lessons}


@app.get("/api/recommend")
def api_recommend():
    day = request.args.get("date") or _today()
    payload = simple_recommend_outfit(day)
    return jsonify(payload)


@app.post("/api/outfits/wear")
def api_wear_outfit():
    """Помечает вещи комплекта как грязные + last_used."""
    data = request.get_json(force=True, silent=True) or {}
    ids = []
    for key in ("top_id", "bottom_id", "shoes_id", "outer_id"):
        if key in data and data[key] is not None:
            try:
                ids.append(int(data[key]))
            except (TypeError, ValueError):
                pass
    ids = [i for i in ids if i > 0]
    if not ids:
        return jsonify({"error": "передайте id вещей (top_id, ...)"}), 400
    db.set_last_used_now(ids)
    db.mark_items_dirty(ids)
    return jsonify({"ok": True, "marked_dirty": ids})


@app.post("/api/items/wash_all")
def api_wash_all():
    n = db.wash_all_dirty()
    return jsonify({"ok": True, "washed_count": n})


@app.post("/api/outfits/save")
def api_save_outfit():
    data = request.get_json(force=True, silent=True) or {}
    top_id = data.get("top_id")
    bottom_id = data.get("bottom_id")
    shoes_id = data.get("shoes_id")
    outer_id = data.get("outer_id")
    label = data.get("label")

    def opt_int(v):
        if v is None or v == "":
            return None
        return int(v)

    oid = db.save_outfit(
        top_id=opt_int(top_id),
        bottom_id=opt_int(bottom_id),
        shoes_id=opt_int(shoes_id),
        outer_id=opt_int(outer_id),
        label=str(label) if label else None,
    )
    return jsonify({"ok": True, "outfit_id": oid})


@app.get("/api/outfits/saved")
def api_list_saved():
    return jsonify({"outfits": db.list_saved_outfits()})


if __name__ == "__main__":
    db.init_app_data()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Локальная разработка: один процесс
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
