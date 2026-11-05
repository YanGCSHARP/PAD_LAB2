"use strict";

// ------------------------------------------------------------------ state & API helper
const state = {
  access: localStorage.getItem("access_token"),
  refresh: localStorage.getItem("refresh_token"),
  me: null,
  events: [],
  pollTimer: null,
};

const $ = (sel) => document.querySelector(sel);
const fmtDate = (iso) => new Date(iso).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" });
const money = (v, cur = "MDL") => `${Number(v).toLocaleString("ru-RU", { minimumFractionDigits: 2 })} ${cur}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast${isError ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 4000);
}

function saveTokens(tokens) {
  state.access = tokens?.access_token ?? null;
  state.refresh = tokens?.refresh_token ?? null;
  for (const [k, v] of [["access_token", state.access], ["refresh_token", state.refresh]]) {
    v ? localStorage.setItem(k, v) : localStorage.removeItem(k);
  }
}

async function api(path, { method = "GET", body, auth = true, retry = true, headers = {} } = {}) {
  const opts = { method, headers: { ...headers } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (auth && state.access) opts.headers.Authorization = `Bearer ${state.access}`;

  const res = await fetch(path, opts);
  if (res.status === 401 && auth && retry && state.refresh) {
    const ok = await refreshTokens();
    if (ok) return api(path, { method, body, auth, retry: false, headers });
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data.error || {};
    const details = (err.details || []).map((d) => `${d.field}: ${d.message}`).join("; ");
    throw new Error(`${err.message || res.statusText}${details ? ` (${details})` : ""}`);
  }
  return data;
}

async function refreshTokens() {
  try {
    saveTokens(await api("/api/auth/refresh", { method: "POST", body: { refresh_token: state.refresh }, auth: false }));
    return true;
  } catch {
    logout(false);
    return false;
  }
}

// ------------------------------------------------------------------ session
async function loadSession() {
  state.me = null;
  if (state.access) {
    try {
      state.me = await api("/api/auth/me");
    } catch {
      saveTokens(null);
    }
  }
  const authed = Boolean(state.me);
  document.querySelectorAll(".auth-only").forEach((el) => el.classList.toggle("hidden", !authed));
  document.querySelectorAll(".guest-only").forEach((el) => el.classList.toggle("hidden", authed));
  document.querySelectorAll(".admin-only").forEach((el) => el.classList.toggle("hidden", state.me?.role !== "admin"));
  $("#session").innerHTML = authed
    ? `<span>${esc(state.me.full_name)} · ${esc(state.me.role)}</span><button class="ghost" id="logout">Выйти</button>`
    : "";
  if (authed) {
    $("#logout").onclick = () => logout(true);
    refreshUnread();
  }
}

async function logout(callApi) {
  if (callApi && state.refresh) {
    await api("/api/auth/logout", { method: "POST", body: { refresh_token: state.refresh }, auth: false }).catch(() => {});
  }
  saveTokens(null);
  await loadSession();
  show("events");
}

// ------------------------------------------------------------------ views
function show(view) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  $(`#view-${view}`)?.classList.remove("hidden");
  document.querySelectorAll("nav a[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  clearInterval(state.pollTimer);
  ({ events: loadEvents, bookings: loadBookings, notifications: loadNotifications, admin: loadVenues, status: loadStatus }[view] || (() => {}))();
}

async function loadEvents() {
  const q = $("#search").value.trim();
  try {
    const page = await api(`/api/events?limit=50${q ? `&q=${encodeURIComponent(q)}` : ""}`, { auth: false });
    state.events = page.items;
    $("#events").innerHTML = page.items.length
      ? page.items.map(renderEvent).join("")
      : `<p class="muted">Мероприятий не найдено.</p>`;
  } catch (e) {
    toast(e.message, true);
  }
}

function renderEvent(ev) {
  const cats = ev.ticket_categories
    .map((c) => `<div><span>${esc(c.name)} — ${money(c.price)}</span><span class="muted">${c.available} / ${c.total}</span></div>`)
    .join("");
  return `<article class="card event">
    <h3>${esc(ev.title)}</h3>
    <div class="meta">${fmtDate(ev.starts_at)} · ${esc(ev.venue.name)}, ${esc(ev.venue.city)}</div>
    <p class="desc">${esc(ev.description)}</p>
    <div class="cats">${cats}</div>
    <button data-book="${ev.id}" ${ev.status !== "on_sale" ? "disabled" : ""}>${ev.status === "on_sale" ? "Забронировать" : "Продажи закрыты"}</button>
  </article>`;
}

function openBooking(eventId) {
  if (!state.me) return toast("Войдите, чтобы бронировать билеты", true);
  const ev = state.events.find((e) => e.id === eventId);
  $("#book-title").textContent = ev.title;
  $("#book-category").innerHTML = ev.ticket_categories
    .map((c) => `<option value="${c.id}" data-price="${c.price}" ${c.available ? "" : "disabled"}>${esc(c.name)} — ${money(c.price)} (осталось ${c.available})</option>`)
    .join("");
  $("#book-form").quantity.value = 1;
  updateTotal();
  $("#book-dialog").showModal();
}

function updateTotal() {
  const opt = $("#book-category").selectedOptions[0];
  const qty = Number($("#book-form").quantity.value || 0);
  $("#book-total").textContent = opt ? `Итого: ${money(Number(opt.dataset.price) * qty)}` : "";
}

async function submitBooking(e) {
  e.preventDefault();
  const form = e.target;
  $("#book-submit").disabled = true;
  try {
    const booking = await api("/api/bookings", {
      method: "POST",
      body: { category_id: form.category_id.value, quantity: Number(form.quantity.value) },
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    $("#book-dialog").close();
    toast(`Бронь создана, ожидает оплаты: ${money(booking.total_amount, booking.currency)}`);
    location.hash = "bookings";
  } catch (err) {
    toast(err.message, true);
  } finally {
    $("#book-submit").disabled = false;
  }
}

const STATUS_RU = { PENDING_PAYMENT: "Ожидает оплаты", CONFIRMED: "Подтверждена", CANCELLED: "Отменена" };

async function loadBookings() {
  try {
    const page = await api("/api/bookings?limit=50");
    $("#bookings").innerHTML = page.items.length
      ? page.items.map((b) => `<div class="card item">
          <div>
            <div class="title">${esc(b.event_title)} · ${esc(b.category_name)} × ${b.quantity}</div>
            <div class="sub">${fmtDate(b.event_starts_at)} · ${money(b.total_amount, b.currency)}${b.cancel_reason ? ` · ${esc(b.cancel_reason)}` : ""}</div>
          </div>
          <div class="row">
            <span class="pill ${b.status}">${STATUS_RU[b.status] || b.status}</span>
            ${b.status !== "CANCELLED" ? `<button class="ghost" data-cancel="${b.id}">Отменить</button>` : ""}
          </div>
        </div>`).join("")
      : `<p class="muted">Пока нет бронирований.</p>`;
    // The saga is asynchronous: poll while something is still pending.
    if (page.items.some((b) => b.status === "PENDING_PAYMENT")) {
      clearInterval(state.pollTimer);
      state.pollTimer = setInterval(() => { loadBookings(); refreshUnread(); }, 1500);
    } else {
      clearInterval(state.pollTimer);
    }
  } catch (e) {
    toast(e.message, true);
  }
}

async function cancelBooking(id) {
  if (!confirm("Отменить бронь?")) return;
  try {
    await api(`/api/bookings/${id}/cancel`, { method: "POST" });
    toast("Бронь отменена");
    loadBookings();
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadNotifications() {
  try {
    const page = await api("/api/notifications?limit=50");
    $("#notifications").innerHTML = page.items.length
      ? page.items.map((n) => `<div class="card item ${n.read ? "" : "unread"}">
          <div><div class="title">${esc(n.title)}</div><div class="sub">${esc(n.message)}</div>
          <div class="sub">${fmtDate(n.created_at)} · ${esc(n.channel)}</div></div>
          ${n.read ? "" : `<button class="ghost" data-read="${n.id}">Прочитано</button>`}
        </div>`).join("")
      : `<p class="muted">Уведомлений нет.</p>`;
  } catch (e) {
    toast(e.message, true);
  }
}

async function refreshUnread() {
  try {
    const { count } = await api("/api/notifications/unread-count");
    $("#unread").textContent = count;
    $("#unread").classList.toggle("hidden", count === 0);
  } catch { /* the badge is not critical */ }
}

async function loadVenues() {
  const venues = await api("/api/venues", { auth: false }).catch(() => []);
  $("#venue-select").innerHTML = venues.map((v) => `<option value="${v.id}">${esc(v.name)} (${esc(v.city)}, ${v.capacity})</option>`).join("");
}

async function loadStatus() {
  try {
    const data = await api("/api/status", { auth: false });
    $("#status").innerHTML = Object.entries(data.services)
      .map(([name, s]) => `<div class="card"><h3>${name}</h3><span class="pill ${s.status}">${s.status}</span>
        <p class="muted">${s.latency_ms} ms · circuit: ${s.circuit}</p></div>`)
      .join("");
  } catch (e) {
    toast(e.message, true);
  }
}

// ------------------------------------------------------------------ wiring
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $("#login-form").classList.toggle("hidden", tab.dataset.tab !== "login");
    $("#register-form").classList.toggle("hidden", tab.dataset.tab !== "register");
  }),
);

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    saveTokens(await api("/api/auth/login", { method: "POST", body: { email: f.email.value, password: f.password.value }, auth: false }));
    f.reset();
    await loadSession();
    toast("Добро пожаловать!");
  } catch (err) {
    toast(err.message, true);
  }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { full_name: f.full_name.value, email: f.email.value, password: f.password.value };
  try {
    await api("/api/auth/register", { method: "POST", body, auth: false });
    saveTokens(await api("/api/auth/login", { method: "POST", body: { email: body.email, password: body.password }, auth: false }));
    f.reset();
    await loadSession();
    toast("Аккаунт создан");
  } catch (err) {
    toast(err.message, true);
  }
});

$("#venue-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api("/api/venues", { method: "POST", body: { name: f.name.value, city: f.city.value, address: f.address.value, capacity: Number(f.capacity.value) } });
    f.reset();
    toast("Площадка создана");
    loadVenues();
  } catch (err) {
    toast(err.message, true);
  }
});

$("#event-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const ticket_categories = f.categories.value.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
    const [name, price, total] = line.split(";").map((s) => s.trim());
    return { name, price, total: Number(total) };
  });
  try {
    await api("/api/events", {
      method: "POST",
      body: {
        venue_id: f.venue_id.value, title: f.title.value, description: f.description.value, category: f.category.value,
        starts_at: new Date(f.starts_at.value).toISOString(), ticket_categories,
      },
    });
    toast("Мероприятие создано");
    location.hash = "events";
  } catch (err) {
    toast(err.message, true);
  }
});

document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset.book) openBooking(t.dataset.book);
  if (t.dataset.cancel) cancelBooking(t.dataset.cancel);
  if (t.dataset.read) api(`/api/notifications/${t.dataset.read}/read`, { method: "POST" }).then(() => { loadNotifications(); refreshUnread(); });
});

$("#book-form").addEventListener("submit", submitBooking);
$("#book-form").addEventListener("input", updateTotal);
$("#book-cancel").addEventListener("click", () => $("#book-dialog").close());
$("#search").addEventListener("input", () => { clearTimeout(loadEvents.t); loadEvents.t = setTimeout(loadEvents, 300); });
$("#refresh-bookings").addEventListener("click", loadBookings);
$("#refresh-status").addEventListener("click", loadStatus);
window.addEventListener("hashchange", () => show(location.hash.slice(1) || "events"));

loadSession().then(() => show(location.hash.slice(1) || "events"));
