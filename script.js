/**
 * Главная страница: погода, рекомендация, расписание, действия.
 */
(function () {
  const $ = (id) => document.getElementById(id);

  const labels = {
    top: "Верх",
    bottom: "Низ",
    shoes: "Обувь",
    outer: "Верхняя одежда",
  };

  const activityRu = {
    sitting: "сидячая",
    sports: "спорт",
    walking: "прогулка",
    mixed: "смешанная",
  };

  let lastOutfit = null;

  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText || String(r.status));
    return data;
  }

  function renderWeather(w) {
    const el = $("weather-text");
    if (!w) {
      el.textContent = "Нет данных.";
      return;
    }
    const precip = w.precip ? ", осадки" : "";
    el.textContent =
      `${Math.round(w.temp_c)}°C, ощущается ${Math.round(w.feels_like_c)}°C — ${w.condition}${precip}`;
  }

  function renderSchedule(lessons) {
    const ul = $("schedule-list");
    ul.innerHTML = "";
    if (!lessons || !lessons.length) {
      ul.innerHTML = "<li>Нет уроков на этот день</li>";
      return;
    }
    lessons.forEach((L) => {
      const li = document.createElement("li");
      const act = activityRu[L.activity] || L.activity;
      li.innerHTML = `<span>${escapeHtml(L.subject)}</span><span class="badge">${escapeHtml(act)}</span>`;
      ul.appendChild(li);
    });
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function renderOutfit(data) {
    const box = $("outfit-content");
    const outfit = data.outfit || {};
    lastOutfit = outfit;
    const parts = ["top", "bottom", "shoes", "outer"];
    const rows = [];
    parts.forEach((key) => {
      const item = outfit[key];
      if (item && item.id) {
        rows.push(
          `<div class="outfit-item"><strong>${labels[key] || key}</strong>${escapeHtml(item.name)} <span style="color:var(--muted);font-size:0.85rem">· ${escapeHtml(item.color)}</span></div>`
        );
      }
    });
    if (!rows.length) {
      box.innerHTML =
        "<p>Недостаточно чистых вещей. Добавьте вещи или постирайте грязные.</p>";
      return;
    }
    box.innerHTML = rows.join("");
  }

  async function loadAll() {
    $("action-msg").textContent = "";
    try {
      const rec = await fetchJSON("/api/recommend");
      renderWeather(rec.weather);
      renderOutfit(rec);
      renderSchedule(rec.schedule || []);
    } catch (e) {
      $("weather-text").textContent = "Ошибка загрузки.";
      $("outfit-content").textContent = String(e.message || e);
    }
  }

  async function refreshWeather() {
    const btn = $("btn-refresh-weather");
    btn.disabled = true;
    try {
      await fetchJSON("/api/weather/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      await loadAll();
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
    btn.disabled = false;
  }

  async function wearOutfit() {
    const o = lastOutfit;
    if (!o) return;
    const body = {};
    if (o.top && o.top.id) body.top_id = o.top.id;
    if (o.bottom && o.bottom.id) body.bottom_id = o.bottom.id;
    if (o.shoes && o.shoes.id) body.shoes_id = o.shoes.id;
    if (o.outer && o.outer.id) body.outer_id = o.outer.id;
    if (Object.keys(body).length === 0) {
      $("action-msg").textContent = "Нет вещей для отметки.";
      return;
    }
    $("btn-wear").disabled = true;
    try {
      await fetchJSON("/api/outfits/wear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("action-msg").textContent = "Комплект отмечен как надетый (вещи в стирке).";
      await loadAll();
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
    $("btn-wear").disabled = false;
  }

  async function washAll() {
    $("btn-wash").disabled = true;
    try {
      const r = await fetchJSON("/api/items/wash_all", { method: "POST" });
      $("action-msg").textContent =
        r.washed_count > 0
          ? `Постирано вещей: ${r.washed_count}.`
          : "Грязных вещей не было.";
      await loadAll();
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
    $("btn-wash").disabled = false;
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadAll();
    $("btn-refresh-weather").addEventListener("click", refreshWeather);
    $("btn-wear").addEventListener("click", wearOutfit);
    $("btn-wash").addEventListener("click", washAll);
  });
})();
