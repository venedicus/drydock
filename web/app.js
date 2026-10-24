"use strict";

// Выбор держим двумя множествами: отдельные файлы и целые папки. Папка в
// выборе означает "всё поддерево", и раскрывать её в тысячи путей на
// клиенте не нужно -- сервер сделает это сам, когда дойдёт до дела.
const sel = { files: new Set(), folders: new Set() };
const expanded = new Set();
let current = null;

const $ = (id) => document.getElementById(id);
const human = (n) => humanSize(n);
// Экранируем все пять символов, а не два: esc() подставляется и в
// текст, и в атрибуты (title="..."), а имя файла приходит из облака и
// кавычку в нём никто не запрещал.
const esc = (s) => String(s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// Срок годности пробы приходит с сервера: "доступно" -- это наблюдение с
// датой, и после TTL оно показывается как устаревшее, а не как факт.
let PROBE_TTL_H = 12;
const hoursAgo = (ts) => ts ? (Date.now() / 1000 - ts) / 3600 : null;
function isStale(node) {
  const h = hoursAgo(node.checked_at);
  return h !== null && h > PROBE_TTL_H;
}

// ── уведомления ─────────────────────────────────────────────────────
// toast() блокирует окно: пока не нажмёшь «ОК», ничего не происходит, а
// после -- строки уже нет, и что именно случилось, не вспомнить. Тосты
// гаснут сами, копятся стопкой и закрываются кликом.
const TOAST_MAX = 4;
function toast(msg, kind = "info", ms) {
  const box = $("toasts");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = `<span class="txt">${esc(msg)}</span>`;
  el.onclick = () => el.remove();
  box.appendChild(el);
  while (box.children.length > TOAST_MAX) box.firstElementChild.remove();
  const ttl = ms || (kind === "err" ? 9000 : 4500);
  setTimeout(() => el.remove(), ttl);
}

// ── тема ────────────────────────────────────────────────────────────
// Три состояния: «как в системе», светлая, тёмная. По умолчанию --
// системная: у кого Windows светлый, тому незачем щуриться в тёмном.
// Само значение ставится ещё в <head> (там же, до отрисовки), иначе окно
// успевает мигнуть чужим цветом.
const THEMES = ["auto", "light", "dark"];
let THEME = localStorage.getItem("cr-theme");
if (!THEMES.includes(THEME)) THEME = "auto";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

// Масштаб: 0 -- «под экран». Пресеты остались кнопкой «авто», а точное
// значение берётся ползунком: кому-то мало 110, а 125 уже много.
const SCALE_MIN = 80;
const SCALE_MAX = 150;
let SCALE = Number(localStorage.getItem("cr-scale"));
if (!Number.isFinite(SCALE) || SCALE < SCALE_MIN || SCALE > SCALE_MAX) SCALE = 0;
let DENSITY = localStorage.getItem("cr-density") === "compact"
  ? "compact" : "normal";

function resolvedTheme() {
  return THEME === "auto" ? (darkQuery.matches ? "dark" : "light") : THEME;
}

// Авто-подгонка: по ширине окна и плотности пикселей. Узкое окно на
// ноутбуке -- мельче, широкий монитор -- крупнее; на глаз это заметно,
// а руками никто не полезет.
function autoScale() {
  const w = window.innerWidth;
  const dpr = window.devicePixelRatio || 1;
  if (w < 1100) return 90;
  if (w < 1400) return 100;
  if (w < 1700) return dpr > 1.5 ? 100 : 105;
  return 110;
}

function currentScale() {
  return SCALE || autoScale();
}

function applyTheme() {
  document.documentElement.dataset.theme = resolvedTheme();
  paintView();
}

function applyView() {
  // zoom, а не font-size: он масштабирует и отступы, и таблицы, и
  // фиксированные панели -- иначе пришлось бы править каждое правило.
  document.documentElement.style.zoom = String(currentScale() / 100);
  document.body.classList.toggle("dense", DENSITY === "compact");
  paintView();
}

function cycleTheme() {
  THEME = THEMES[(THEMES.indexOf(THEME) + 1) % THEMES.length];
  localStorage.setItem("cr-theme", THEME);
  applyTheme();
}

// Кнопки вида: масштаб, плотность, тема. Строятся один раз, потом только
// подсвечиваются -- иначе перерисовка сбивала бы фокус.
function initView() {
  const group = (id, items, attr) => {
    const box = $(id);
    if (!box) return;
    box.innerHTML = items.map(([value, label]) =>
      `<button data-${attr}="${value}">${esc(label)}</button>`).join("");
  };

  group("density-btns", [["normal", t("view.density.normal")],
                         ["compact", t("view.density.compact")]], "density");
  group("theme-btns", THEMES.map((v) => [v, t("theme." + v)]), "theme");

  const range = $("scale-range");
  range.oninput = () => {
    SCALE = Number(range.value);
    localStorage.setItem("cr-scale", String(SCALE));
    applyView();
  };
  $("scale-auto").onclick = () => {
    SCALE = 0;
    localStorage.removeItem("cr-scale");
    applyView();
  };
  $("density-btns").onclick = (e) => {
    const b = e.target.closest("[data-density]");
    if (!b) return;
    DENSITY = b.dataset.density;
    localStorage.setItem("cr-density", DENSITY);
    applyView();
  };
  $("theme-btns").onclick = (e) => {
    const b = e.target.closest("[data-theme]");
    if (!b) return;
    THEME = b.dataset.theme;
    localStorage.setItem("cr-theme", THEME);
    applyTheme();
  };
}

function paintView() {
  const scale = currentScale();
  const range = $("scale-range");
  if (range && document.activeElement !== range) range.value = String(scale);
  const val = $("scale-val");
  if (val) val.textContent = `${scale}%`;
  $("scale-auto")?.classList.toggle("on", !SCALE);
  for (const b of $("density-btns")?.children || []) {
    b.classList.toggle("on", b.dataset.density === DENSITY);
  }
  for (const b of $("theme-btns")?.children || []) {
    b.classList.toggle("on", b.dataset.theme === THEME);
  }
  const note = $("view-note");
  if (note) {
    note.textContent = SCALE
      ? t("view.manual", { pct: scale })
      : t("view.auto", { pct: scale });
  }
  const btn = $("btn-view");
  if (btn) btn.title = `${t("view.title")}: ${scale}%`;
}

function toggleView() {
  const pop = $("view-pop");
  pop.classList.toggle("hidden");
  if (!pop.classList.contains("hidden")) paintView();
}

// Система переключила тему, пока окно открыто, -- следуем за ней.
darkQuery.addEventListener("change", () => { if (THEME === "auto") applyTheme(); });

// Сервер не знает, на каком языке открыто окно: ошибки приходят кодом
// {"code": "err.noToken"} или {"code": "err.folderMissing", "source": "…"}.
// Переводим здесь; если кода нет -- показываем текст как есть.
function apiError(detail, status) {
  if (detail && typeof detail === "object" && detail.code) {
    const params = { ...detail };
    delete params.code;
    // «нечего пробовать» бывает про узел и про кластер -- разные подписи.
    if (params.kind) params.kind = t("job." + params.kind);
    const key = detail.host ? "err.nothingToProbeNode"
      : detail.cluster ? "err.nothingToProbeCluster" : detail.code;
    const err = new Error(t(key, params));
    err.code = detail.code;
    return err;
  }
  return new Error(detail || `HTTP ${status}`);
}

// Сообщение задачи: код плюс числа, старые записи -- обычный текст.
function jobText(raw) {
  const text = String(raw || "");
  if (text.startsWith("{")) {
    try {
      const m = JSON.parse(text);
      if (m && m.c) {
        const params = { ...m };
        delete params.c;
        if (params.kind) params.kind = t("job." + params.kind);
        // «диск полон» -- отдельная фраза, а не флаг в подстановке.
        if ("full" in params) params.full = params.full ? t("jobmsg.full") : "";
        return t("jobmsg." + m.c, params);
      }
    } catch (e) { /* не наш формат -- покажем как есть */ }
  }
  return text;
}

const api = async (url, body) => {
  const opt = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) };
  const resp = await fetch(url, opt);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw apiError(data.detail, resp.status);
  return data;
};

// ── шапка ───────────────────────────────────────────────────────────

let lastStateAt = 0;
let wasRunning = false;

// Отпечаток файлов интерфейса, с которым загрузилась эта страница. Если
// сервер начал отдавать другой -- значит программу обновили под открытым
// окном, и страница перезагружает себя сама. Иначе человек продолжает
// смотреть на старый интерфейс и видеть давно починенные баги.
let loadedAssets = null;
// Последнее состояние и числа по текущему выбору: карточки действий
// должны отвечать на вопрос «а сколько будет с этим выбором», а не только
// «сколько всего в коллекции».
let lastState = null;
let lastTotals = null;
let selPlan = null;

// ── линза: одни и те же данные, три разных вопроса ────────────────────
// «Сейчас» -- что облако ещё держит; «Было» -- вся опись с судьбой
// каждого файла; «На диске» -- что спасено. Раньше строка папки
// показывала исторический размер, и папка, от которой в облаке ничего не
// осталось, выглядела полной.
const LENSES = ["now", "was", "disk"];
let LENS = localStorage.getItem("cr-lens") || "now";
// Ссылку можно дать прямо адресом: ?lens=was -- открыть в линзе «Было».
const lensParam = new URLSearchParams(location.search).get("lens");
if (LENSES.includes(lensParam)) LENS = lensParam;
if (!LENSES.includes(LENS)) LENS = "now";
// Пустые в линзе «Сейчас» папки скрыты: в облаке от них ничего не
// осталось, и держать их в списке -- шум. Но иногда нужно увидеть всё.
let showEmpty = localStorage.getItem("cr-show-empty") === "1";

function paintLens() {
  for (const b of $("lens").querySelectorAll("button")) {
    b.classList.toggle("on", b.dataset.lens === LENS);
  }
  const btn = $("btn-show-empty");
  if (btn) {
    btn.classList.toggle("on", showEmpty);
    btn.textContent = t("tree.showEmpty");
  }
}

function setLens(name) {
  if (!LENSES.includes(name)) return;
  LENS = name;
  localStorage.setItem("cr-lens", name);
  paintLens();
  loadTree();
  refreshState();
}

// Что показывать в строке узла при текущей линзе.
function lensOf(node) {
  const live = (node.ok || 0) + (node.unavailable || 0) + (node.unchecked || 0);
  if (LENS === "now") return { files: live, bytes: node.live_bytes || 0 };
  if (LENS === "disk") return { files: node.present || 0,
                                bytes: node.present_bytes || 0 };
  return { files: node.files || 0, bytes: node.bytes || 0 };
}

// Кнопка аккаунта в шапке: под кем работаем и жив ли токен. Раньше вход
// жил в меню «Ещё», и ответить на это без захода туда было нельзя.
function renderAuthButton(s) {
  const btn = $("btn-auth");
  if (!btn) return;
  const label = $("auth-label");
  const dot = $("auth-dot");
  const acc = s.account || {};
  const check = s.token_check || {};
  const accName = (acc.name || "").trim();
  const showName = accName && accName !== acc.login && accName !== ".";
  const dead = !!s.token && check.ok === false;
  const ok = !!s.token && !dead;

  btn.classList.toggle("bad", !ok);
  dot.className = "dot2 " + (ok ? "ok" : (dead ? "bad" : "warn"));

  if (!s.token) {
    label.textContent = t("auth.signIn");
    btn.title = t("btn.auth.title");
    return;
  }
  if (dead) {
    label.textContent = t("auth.dead");
    btn.title = [t("auth.dead.why"), check.detail || ""].filter(Boolean).join("\n");
    return;
  }
  label.textContent = acc.login || t("auth.tokenOnly");
  const when = check.ts ? new Date(check.ts * 1000).toLocaleString(I18N.lang) : "";
  btn.title = [
    showName ? `${accName} (${acc.login || ""})`.trim() : (acc.login || ""),
    when ? t("auth.checkedAt", { when }) : "",
    acc.total ? t("auth.space", { used: human(acc.used), total: human(acc.total) }) : "",
    t("auth.clickToManage"),
  ].filter(Boolean).join("\n");
}

// Блок аккаунта в модалке входа: кто, когда проверено, сколько места.
function accountBlock(acc) {
  const used = acc.used || 0;
  const total = acc.total || 0;
  const pct = total ? Math.min(100, Math.round(100 * used / total)) : 0;
  const when = acc.ts ? new Date(acc.ts * 1000).toLocaleString(I18N.lang) : "";
  const nm = (acc.name || "").trim();
  const who = acc.login
    ? `<div class="lg">${esc(acc.login)}</div>${
        nm && nm !== acc.login && nm !== "."
          ? `<div class="nm">${esc(nm)}</div>` : ""}`
    : `<div class="lg">${t("auth.noAccount")}</div>`;
  return `<div class="acc">
      <span class="dot2 ${acc.login ? "ok" : "warn"}"></span>
      <div class="who">${who}
        <div class="when">${when ? t("auth.checkedAt", { when }) : ""}</div></div>
      ${total ? `<div class="space">${t("auth.space", {
          used: human(used), total: human(total) })} · ${pct}%
        <div class="bar3"><i class="${pct >= 95 ? "full" : ""}"
          style="width:${pct}%"></i></div></div>` : ""}
      <button id="auth-acc-refresh" class="ghost">${t("auth.refreshInfo")}</button>
    </div>`;
}

// Строка в шапке: одна, но по выбранной линзе.
function summaryLine(s, t_) {
  const files = (n) => t("n.files", { n });
  if (LENS === "disk") {
    return `${t("summary.disk", { n: t_.present || 0, files: files(t_.present || 0),
                                 size: human(t_.present_bytes) })}`;
  }
  if (LENS === "was") {
    return `${t("summary.was", { n: t_.files || 0, files: files(t_.files || 0),
                                size: human(t_.bytes) })} · `
      + `${t("summary.savedShort", { n: t_.present || 0, files: files(t_.present || 0) })}`;
  }
  const live = (t_.ok || 0) + (t_.unavailable || 0) + (t_.unchecked || 0);
  return `<span class="ok"><b>${live.toLocaleString(I18N.lang)}</b> `
    + `${t("summary.now", { n: live, files: files(live) })}</span> · `
    + `${t("summary.savedShort", { n: t_.present || 0, files: files(t_.present || 0) })}`;
}

// Плитки итогов под выбранную линзу.
function tilesFor(s, t_) {
  const saved = ["ok", t("tile.onDisk"), t_.present || 0,
                 t_.unverified
                   ? t("tile.verifiedOf", { n: t_.saved || 0,
                                            files: t("n.files", { n: t_.saved || 0 }) })
                   : human(t_.present_bytes)];
  const holes = ["warn", t("tile.salvaged"), t_.salvaged || 0,
                 t_.salvaged ? human(t_.salvaged_bytes) : ""];
  const fixed = ["ok", t("tile.fixed"), t_.fixed || 0, ""];
  if (LENS === "was") {
    return [
      ["", t("tile.wasFiles"), t_.files || 0, human(t_.bytes)],
      saved,
      ["", t("tile.deletedByUs"), t_.cloud_deleted || 0, ""],
      ["", t("tile.vanished"), t_.vanished || 0, ""],
      ["warn", t("tile.neverTaken"), t_.never_taken || 0, ""],
      holes,
    ];
  }
  if (LENS === "disk") {
    return [
      ["ok", t("tile.onDisk"), t_.present || 0, human(t_.present_bytes)],
      holes,
      fixed,
      ["bad", t("tile.missingLocal"), t_.missing_local || 0, ""],
    ];
  }
  return [
    ["ok", t("tile.available"), t_.ok || 0, human(t_.ok_bytes)],
    ["bad", t("tile.unavailable"), t_.unavailable || 0, ""],
    ["warn", t("tile.unchecked"), t_.unchecked || 0, ""],
    saved,
    holes,
    fixed,
    ["", t("tile.gone"), t_.gone || 0, ""],
  ];
}

// Числа на четырёх главных кнопках. Это и есть сводка: раньше её несли
// одиннадцать чипов, и все их приходилось читать.
function paintActions(s, t_) {
  const hasSel = !!(sel.files.size || sel.folders.size);
  const files = (n) => t("n.files", { n });
  // Числа под выбор: если что-то отмечено, кнопки отвечают «сколько будет
  // с ним», а не «сколько всего в коллекции».
  const p = hasSel ? selPlan : null;

  const scan = s.scan_pending || 0;
  $("n-scan").textContent = scan ? scan.toLocaleString(I18N.lang) : "✓";
  $("s-scan").textContent = scan ? t("act.scan.left") : t("act.scan.done");

  const left = s.remaining || {};
  const by = left.by_state || {};
  // Очередь круга сервер считает сам (отлёжка, свежий gone) -- берём её,
  // иначе кнопка обещает одно, а задача берёт другое.
  const loopN = p ? (p.loop.files || 0)
    : (left.loop_queue != null ? left.loop_queue
                               : ((by.unavailable || {}).files || 0));
  const loopB = p ? (p.loop.bytes || 0) : ((by.unavailable || {}).bytes || 0);
  $("n-loop").textContent = loopN.toLocaleString(I18N.lang);
  $("s-loop").textContent = loopN
    ? t(p ? "act.loop.takeSel" : "act.loop.take", { size: human(loopB) })
    : t("act.loop.empty");
  $("btn-loop").disabled = !loopN;

  const archN = p ? (p.arch.files || 0) : (t_.arch_ready || 0);
  $("n-archive").textContent = archN.toLocaleString(I18N.lang);
  $("s-archive").textContent = archN
    ? (p ? t("act.archive.sel", { n: p.arch.volumes || 0,
                                  volumes: t("n.volumes", { n: p.arch.volumes || 0 }) })
         : t("act.archive.wait", { size: human(t_.saved_bytes) }))
    : t("act.archive.empty");
  $("btn-archive").disabled = !archN;

  const delN = p ? (p.del.allowed || 0) : (t_.del_ready || 0);
  $("n-delete").textContent = delN.toLocaleString(I18N.lang);
  $("s-delete").textContent = delN
    ? t(p ? "act.delete.sel" : "act.delete.ready")
    : t(p ? "act.delete.emptySel" : "act.delete.empty");
  $("btn-cloud-delete").disabled = !delN;

  // Видно, что числа относятся к выбору, а не ко всей коллекции.
  for (const id of ["btn-loop", "btn-archive", "btn-cloud-delete"]) {
    const el = $(id);
    el.classList.toggle("scoped", hasSel);
  }
}

async function refreshState(fresh) {
  lastStateAt = Date.now();
  const s = await api("/api/state" + (fresh ? "?fresh=true" : ""));
  if (s.assets_version) {
    if (loadedAssets === null) loadedAssets = s.assets_version;
    else if (loadedAssets !== s.assets_version) {
      console.info("интерфейс обновился, перезагружаюсь");
      location.reload();
      return s;
    }
  }
  if (s.probe_ttl_hours) PROBE_TTL_H = s.probe_ttl_hours;
  const t_ = s.totals || {};
  // ── Строка состояния в шапке ────────────────────────────────────────
  // Одна строка вместо одиннадцати чипов: сколько всего, сколько спасено,
  // сколько можно взять прямо сейчас. Остальное -- в карточке «Итоги».
  lastState = s; lastTotals = t_;
  $("summary").innerHTML = summaryLine(s, t_);
  paintActions(s, t_);
  renderSetup(s);
  renderAuthButton(s);

// ── Итоги: те же цифры, что были чипами, но плитками ────────────────
  // Плитки тоже по линзе: в «Сейчас» нет смысла показывать «пропало из
  // облака» (это про прошлое), а в «Было» -- «недоступно» (это про сейчас).
  const tiles = tilesFor(s, t_);
  $("totals-card").innerHTML =
    `<h4>${t("totals.title")}</h4>
     <div class="tiles">${tiles.map(([cls, label, n, note]) =>
       `<div class="tile ${cls}"><div class="n">${n.toLocaleString(I18N.lang)}</div>
        <div class="l">${label}${note ? ` · ${note}` : ""}</div></div>`).join("")}</div>
     <div class="tiles-foot">
       ${s.free && s.free.save_root
         ? `<span>${t("tile.free", { drive: s.free.save_root.drive,
                                    size: human(s.free.save_root.free) })}</span>` : ""}
       <span class="hosts-link" title="${t("hosts.open")}">${t("chip.hosts", {
                                 alive: s.hosts && s.hosts.alive || 0,
                                 dead: s.hosts && s.hosts.dead || 0,
                                 best: Math.round((s.hosts && s.hosts.best_share || 0) * 100) })}</span>
       ${LENS === "now" && t_.stale
         ? `<span class="dim" title="${t("tile.stale.title", { hours: PROBE_TTL_H })}">${
             t("tile.staleLine", {
               n: t_.stale, files: t("n.files", { n: t_.stale }),
               when: s.remaining && s.remaining.checked_at
                 ? new Date(s.remaining.checked_at * 1000)
                     .toLocaleDateString(I18N.lang) : "" })}</span>`
         : ""}
       ${t_.revived ? `<span>${t("chip.revived", { n: t_.revived })}</span>` : ""}
       ${t_.archives
         ? `<span>${t("chip.archives", { n: t_.archives, size: human(t_.archive_bytes) })}</span>`
         : ""}
       ${s.token ? "" : `<span style="color:var(--bad)">${t("chip.noToken")}</span>`}
       ${s.token && s.token_check && s.token_check.ok === false
         ? `<span style="color:var(--bad)">${t("chip.tokenDead")}</span>` : ""}
       ${s.seven_zip ? "" : `<span style="color:var(--bad)">${t("chip.no7zip")}</span>`}
       <span>${t("chip.saveTo", { path: esc(s.root || "") })}</span>
     </div>
     ${LENS === "now" ? remainingBlock(s.remaining) : ""}`;
  const hostsLink = $("totals-card").querySelector(".hosts-link");
  if (hostsLink) hostsLink.onclick = () => wrap(hostsLink, hostsModal);
  const where = $("totals-card").querySelector(".tiles-foot .path");
  if (where) {
    where.title = t("chip.saveTo.title");
    where.onclick = () => api("/api/reveal", {}).catch((e) => toast(e.message, "err"));
  }

  // ── Карточка «Что дальше»: программа считает шаг сама ───────────────
  renderNext(s, t_);
  // Чекпоинт описи: прерванный обход продолжается сам, но интерфейс об
  // этом молчал -- человек не понимал, всё ли потеряно при обрыве. Здесь
  // он видит остаток очереди и может потребовать начало заново.
  const hint = $("scan-hint");
  // Автопилот: переключатель программы, а не окна, поэтому его честно
  // ставит сервер. Подсказка собирает оба дела -- прерванную опись и
  // следующий круг автопилота, чтобы одно не прятало другое.
  if ($("autopilot")) $("autopilot").checked = !!s.autopilot;
  const hintBits = [];
  if (s.scan_pending) {
    hintBits.push(t("scan.pending", { n: s.scan_pending,
                                      folders: t("n.folders", { n: s.scan_pending }) }));
  }
  if (s.autopilot) {
    const cfg = s.autopilot_config || {};
    hintBits.push(s.autopilot_last_at
      ? t("autopilot.next", { n: new Date(s.autopilot_last_at * 1000
          + (cfg.hours || 2) * 3600 * 1000).toLocaleString(I18N.lang) })
      : t("autopilot.nextSoon"));
  }
  hint.textContent = hintBits.join(" · ");
  if (s.scan_pending) {
    hint.title = t("scan.pending.title");
    $("scan-restart-wrap").classList.remove("hidden");
  } else {
    $("scan-restart-wrap").classList.add("hidden");
    $("scan-restart").checked = false;
  }
  return s;
}

// ── дерево ──────────────────────────────────────────────────────────

function stateOf(node) {
  if (!node.is_dir) return node.state || "unchecked";
  if (node.ok > 0) return "ok";
  if (node.unavailable > 0) return "unavailable";
  if (node.gone > 0) return "gone";
  return "unchecked";
}

function nodeRow(node, depth, q) {
  const row = document.createElement("div");
  row.className = "node";
  row.style.paddingLeft = (depth * 16 + 8) + "px";
  row.dataset.path = node.path;
  // tabindex=-1, а не 0: иначе Tab шёл бы через тысячи строк. Фокус
  // ставится стрелками, кликом и из поиска.
  row.tabIndex = -1;

  const tw = document.createElement("span");
  tw.className = "twisty" + (node.is_dir ? "" : " leaf");
  tw.textContent = expanded.has(node.path) ? "▾" : "▸";
  row.appendChild(tw);

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = node.is_dir ? sel.folders.has(node.path) : sel.files.has(node.path);
  cb.setAttribute("aria-label", node.name);
  row.appendChild(cb);
  row.title = node.path;

  const dot = document.createElement("span");
  // Устаревшее наблюдение -- не знание: точка гаснет, чтобы «доступно»
  // месячной давности не читалось как текущее состояние.
  const stale = node.is_dir ? (node.stale || 0) > 0 : isStale(node);
  dot.className = "dot " + stateOf(node) + (stale ? " stale" : "");
  const nl = String.fromCharCode(10);
  dot.title = node.is_dir
    ? t("tree.dirTip", { ok: node.ok, bad: node.unavailable,
                         unchecked: node.unchecked })
      + (node.stale
         ? nl + t("tree.staleTip", { n: node.stale, files: node.files }) : "")
    : t("tree.fileTip", { state: node.state || t("chip.unchecked") })
      + (stale ? nl + t("detail.staleNote") : "");
  row.appendChild(dot);

  const name = document.createElement("span");
  name.className = "name";
  if (q) name.innerHTML = (node.is_dir ? "📁 " : "") + highlight(node.name, q);
  else name.textContent = (node.is_dir ? "📁 " : "") + node.name;
  row.appendChild(name);

  const meta = document.createElement("span");
  meta.className = "meta";
  const bits = [];
  if (node.is_dir) {
    // Число и размер -- по линзе: «в облаке», «было» или «на диске».
    const v = lensOf(node);
    bits.push(`${v.files} ${t("unit.pcs")}`);
    bits.push(human(v.bytes));
    if (LENS === "was") {
      if (node.cloud_deleted) bits.push(`<span class="badge del">${
        t("badge.removedN", { n: node.cloud_deleted })}</span>`);
      if (node.vanished) bits.push(`<span class="badge">${
        t("badge.vanishedN", { n: node.vanished })}</span>`);
    }
    if (node.present) bits.push(`<span class="badge saved">${
      t("badge.saved", { n: node.present })}</span>`);
    if (node.archived) bits.push(`<span class="badge arch">${
      t("badge.archivedN", { n: node.archived })}</span>`);
  } else {
    bits.push(human(node.bytes));
    if (node.verify === "ok" && !node.released)
      bits.push(`<span class="badge saved">${t("badge.savedOne")}</span>`);
    if (node.verify === "salvaged")
      bits.push(`<span class="badge hole">${t("badge.gaps")}</span>`);
    if (node.released) bits.push(`<span class="badge">${t("badge.released")}</span>`);
    if (node.archived) bits.push(`<span class="badge arch">${t("badge.archived")}</span>`);
    if (node.cloud_deleted)
      bits.push(`<span class="badge del">${t("badge.notInCloud")}</span>`);
    if (node.preview_state === "ok")
      bits.push(`<span class="badge">${t("badge.preview")}</span>`);
  }
  meta.innerHTML = bits.join(" ");
  row.appendChild(meta);

  tw.onclick = (e) => { e.stopPropagation(); if (node.is_dir) toggle(node, row, depth); };
  cb.onclick = (e) => {
    e.stopPropagation();
    const set = node.is_dir ? sel.folders : sel.files;
    if (cb.checked) set.add(node.path); else set.delete(node.path);
    refreshSelection();
  };
  row.onclick = () => {
    row.focus({ preventScroll: true });
    if (!node.is_dir) showDetail(node.path);
  };
  return row;
}

// Режим «только нескачанное»: в дереве остаются папки, под которыми есть
// файлы без локальной копии (любые -- доступные, недоступные, непроверенные),
// и прячутся файлы, уже лежащие на диске. Когда папка выкачана целиком, она
// из вида уходит -- по ней всё решено, её можно забирать в архивы.
// Выбор запоминаем: окно перезагружает себя само при обновлении
// интерфейса, и режим не должен от этого сбрасываться.
let onlyUnsaved = localStorage.getItem("onlyUnsaved") === "1";
// Ссылку на режим можно дать прямо адресом: ?unsaved=1 включает его.
if (new URLSearchParams(location.search).get("unsaved") === "1") {
  onlyUnsaved = true;
  localStorage.setItem("onlyUnsaved", "1");
}

function visibleInTree(node) {
  if (node.is_dir && LENS === "now" && !showEmpty) {
    const live = (node.ok || 0) + (node.unavailable || 0) + (node.unchecked || 0);
    if (live === 0) return false;
  }
  if (!onlyUnsaved) return true;
  if (node.is_dir) return (node.files || 0) - (node.present || 0) > 0;
  // Файл прячем, если на диске есть годная копия -- проверенная или
  // перенесённая вручную (её перекачивать неоткуда). Запись, чей файл
  // исчез с диска, копией не считается: сверка ставит local_missing.
  return !(node.verify && node.verify !== "mismatch" && !node.released
           && !node.local_missing);
}

const treeChildren = (data) => (data.children || []).filter(visibleInTree);

// Подсветка найденного: в выдаче из сотен строк иначе не видно, почему
// строка вообще попала в список.
function highlight(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  const needle = esc(q);
  const i = safe.toLowerCase().indexOf(needle.toLowerCase());
  if (i < 0) return safe;
  return safe.slice(0, i) + "<mark>" + safe.slice(i, i + needle.length)
    + "</mark>" + safe.slice(i + needle.length);
}

async function toggle(node, row, depth) {
  if (expanded.has(node.path)) {
    expanded.delete(node.path);
    let n = row.nextSibling;
    while (n && Number(n.dataset.depth) > depth) {
      const next = n.nextSibling; n.remove(); n = next;
    }
    row.querySelector(".twisty").textContent = "▸";
    return;
  }
  expanded.add(node.path);
  row.querySelector(".twisty").textContent = "▾";
  const data = await api("/api/tree?path=" + encodeURIComponent(node.path));
  let anchor = row;
  for (const child of treeChildren(data)) {
    const r = nodeRow(child, depth + 1);
    r.dataset.depth = depth + 1;
    anchor.after(r);
    anchor = r;
    if (expanded.has(child.path) && child.is_dir) await toggle(child, r, depth + 1);
  }
}

// Номер поколения отрисовки. Между очисткой списка и вставкой строк есть
// await, и две отрисовки, начатые внахлёст (смена языка, поиск, обновление
// состояния), дописывали строки друг другу -- папки двоились. Поздняя
// отрисовка отменяет раннюю: та, увидев чужое поколение, молча уходит.
let treeGeneration = 0;

async function loadTree() {
  const mine = ++treeGeneration;
  const box = $("tree");
  const data = await api("/api/tree?path=disk:%2F");
  if (mine !== treeGeneration) return;
  box.innerHTML = "";
  if (!data.children.length) {
    box.innerHTML = `<div class="detail empty" style="padding:14px">${
      t("tree.empty")}</div>`;
    return;
  }
  for (const child of treeChildren(data)) {
    // Раскрытие папки тоже ходит на сервер, и за это время могла начаться
    // новая отрисовка -- дописывать строки в чужой список незачем.
    if (mine !== treeGeneration) return;
    const r = nodeRow(child, 0);
    r.dataset.depth = 0;
    box.appendChild(r);
    if (expanded.has(child.path) && child.is_dir) await toggle(child, r, 0);
  }
}

// Переключатель «только нескачанное»: перерисовывает дерево с прежним
// раскрытием -- иначе режим выглядел бы пустым до ручного раскрытия.
window.toggleOnlyUnsaved = async () => {
  onlyUnsaved = !onlyUnsaved;
  localStorage.setItem("onlyUnsaved", onlyUnsaved ? "1" : "0");
  paintOnlyUnsaved();
  if (onlyUnsaved) {
    // Свежий взгляд на диск: файл могли переложить минуту назад, и
    // показывать его как «не скачан» -- значит врать.
    try { await api("/api/local/sync", {}); } catch (e) { console.warn(e); }
    await refreshState(true);
  }
  loadTree();
};

function paintOnlyUnsaved() {
  const btn = $("btn-only-unsaved");
  if (!btn) return;
  btn.classList.toggle("on", onlyUnsaved);
  btn.title = onlyUnsaved ? t("btn.onlyUnsaved.on") : t("btn.onlyUnsaved.title");
  btn.textContent = onlyUnsaved ? t("btn.onlyUnsaved.off") : t("btn.onlyUnsaved");
}

wrap($("btn-only-unsaved"), () => toggleOnlyUnsaved());

// Автопилот: переключатель живёт в настройках программы, не в браузере,
// поэтому его ставит сервер -- при обновлении состояния.
wrap($("autopilot"), async () => {
  await api("/api/autopilot", { on: $("autopilot").checked });
});
paintOnlyUnsaved();
// Текст кнопки зависит от режима, поэтому статическая разметка его не
// задаёт -- перекрашиваем при смене языка.
document.addEventListener("langchange", () => paintOnlyUnsaved());

// ── выбор ───────────────────────────────────────────────────────────

let planTimer = null;
function refreshSelection() {
  clearTimeout(planTimer);
  // Кнопки выбора живут по его же состоянию: «Скачать выбранное» без
  // выбора выключена с пояснением, а не молча падает в alert.
  const empty = !sel.files.size && !sel.folders.size;
  $("btn-download").disabled = empty;
  $("btn-download").title = empty ? t("btn.download.empty") : t("btn.download.title");
  if (empty) $("selinfo").textContent = t("sel.hint");
  else $("selinfo").textContent = t("sel.counting");
  if (empty) return;
  planTimer = setTimeout(async () => {
    if (!sel.files.size && !sel.folders.size) {
      $("selinfo").textContent = t("sel.hint");
      selPlan = null;
      if (lastState) paintActions(lastState, lastTotals || {});
      return;
    }
    try {
      // Один запрос вместо четырёх: план выгрузки, круг, архив и удаление
      // считаются по одному и тому же разрешённому списку путей.
      const data = await api("/api/selection/plan", selectionBody({
        volume: archOpts.volume,
        compression: archOpts.compression,
        level: $("delete-level").value,
      }));
      const p = data.plan;
      // Части с нулём не показываем: «не проверено 0» -- это шум, а не
      // информация. Строка собирается из того, что действительно есть.
      const n = (v) => (v || 0).toLocaleString(I18N.lang);
      const parts = [];
      if (p.available) parts.push(t("sel.p.avail", {
        n: n(p.available), size: human(p.available_bytes) }));
      if (p.already) parts.push(t("sel.p.saved", { n: n(p.already) }));
      if (p.unavailable) parts.push(t("sel.p.unavail", { n: n(p.unavailable) }));
      if (p.unchecked) parts.push(t("sel.p.unchecked", { n: n(p.unchecked) }));
      $("selinfo").innerHTML = t("sel.total", {
        count: n(p.count), files: t("n.files", { n: p.count }), size: human(p.bytes),
      }) + (parts.length ? " — " + parts.join(" · ") : "");
      selPlan = { loop: data.loop, arch: data.arch, del: data.del };
      if (lastState) paintActions(lastState, lastTotals || {});
    } catch (e) {
      $("selinfo").textContent = t("sel.failed", { error: e.message });
    }
  }, 250);
}

function selectionBody(extra) {
  const states = [];
  if ($("f-ok").checked) states.push("ok");
  return Object.assign({
    paths: [...sel.files],
    folders: [...sel.folders],
    states: states.length ? states : null,
    exclude_saved: $("f-unsaved").checked,
  }, extra || {});
}

// ── «Осталось взять» по последнему известному состоянию облака ────────
// Одного числа мало: «осталось 791 ГБ» читается как «столько ещё можно
// взять», хотя большую часть облако уже не отдаёт. Поэтому рядом --
// разбивка и когда это проверяли.
function remainingBlock(left) {
  if (!left || !left.files) return "";
  const by = left.by_state || {};
  const st = (k) => by[k] || { files: 0, bytes: 0 };
  const row = (label, v, cls) =>
    v.files
      ? `<div class="left-row ${cls || ""}"><span>${label}</span>
           <span>${v.files.toLocaleString(I18N.lang)} · ${human(v.bytes)}</span></div>`
      : "";
  const when = left.checked_at
    ? new Date(left.checked_at * 1000).toLocaleString(I18N.lang) : "";
  return `<div class="left">
    <div class="left-head">${t("left.title")}: <b>${left.files.toLocaleString(I18N.lang)}</b>
      ${t("n.files", { n: left.files })} · ${human(left.bytes)}</div>
    <div class="left-row now"><span>${t("left.now")}</span>
      <span>${left.available_files.toLocaleString(I18N.lang)} · ${human(left.available_bytes)}</span></div>
    ${row(t("left.unavailable"), st("unavailable"), "warn")}
    ${row(t("left.gone"), st("gone"), "bad")}
    ${row(t("left.unchecked"), st("unchecked"))}
    ${when ? `<div class="tiny">${t("left.checked", { when })}</div>` : ""}
  </div>`;
}

// ── начало работы ───────────────────────────────────────────────────
// Три шага, без которых программа бесполезна: токен, опись, первое
// спасение. Новый человек видит пустой экран и четыре кнопки -- этот
// чеклист объясняет порядок. Когда всё сделано, карточка уходит сама.
let setupHidden = localStorage.getItem("cr-setup-hidden") === "1";
const forceSetup = new URLSearchParams(location.search).get("onboard") === "1";

function setupSteps(s) {
  const t_ = s.totals || {};
  const tokenOk = !!s.token && !(s.token_check && s.token_check.ok === false);
  return [
    { done: tokenOk, title: t("setup.token"), why: t("setup.token.why"),
      btn: t("btn.auth"), run: () => $("btn-auth").click() },
    { done: (t_.files || 0) > 0, title: t("setup.scan"), why: t("setup.scan.why"),
      btn: t("act.scan"), run: () => $("btn-scan").click() },
    { done: (t_.present || 0) > 0, title: t("setup.rescue"), why: t("setup.rescue.why"),
      btn: t("act.loop"), run: () => $("btn-loop").click() },
  ];
}

function renderSetup(s) {
  const card = $("setup-card");
  if (!card) return;
  const steps = setupSteps(s);
  const done = steps.filter((x) => x.done).length;
  if ((done === steps.length && !forceSetup) || setupHidden) {
    card.classList.add("hidden");
    return;
  }
  const firstOpen = steps.findIndex((x) => !x.done);
  card.classList.remove("hidden");
  card.innerHTML = `<h4>${t("setup.title")}
      <span class="n">${done} / ${steps.length}</span>
      <button class="ghost setup-close" onclick="hideSetup()"
        title="${t("setup.hide")}" aria-label="${t("setup.hide")}">×</button></h4>`
    + steps.map((x, i) => `<div class="step ${
        x.done ? "done" : (i === firstOpen ? "now" : "")}">
        <span class="mark2">${x.done ? "✓" : i + 1}</span>
        <span class="txt"><div class="t">${esc(x.title)}</div>
          <div class="w">${esc(x.why)}</div></span>
        ${x.done ? "" : `<button data-i="${i}">${esc(x.btn)}</button>`}
      </div>`).join("");
  for (const b of card.querySelectorAll("button[data-i]")) {
    b.onclick = () => steps[Number(b.dataset.i)].run();
  }
}

window.hideSetup = () => {
  setupHidden = true;
  localStorage.setItem("cr-setup-hidden", "1");
  $("setup-card").classList.add("hidden");
};

// ── карточка «Сейчас»: активная задача крупно, а не строкой в подвале ──
// ── карточка «Что дальше»: программа считает шаг сама ────────────────
async function runNextStep(step) {
  try {
    if (step.kind === "scan") {
      await api("/api/scan", { restart: $("scan-restart").checked });
    } else if (step.kind === "download") {
      // Вся коллекция: папка-корень + только доступное + пропустить
      // спасённое -- ровно то, что советует карточка.
      downloadFlow({ folders: ["disk:/"], exclude_saved: true,
                     states: ["ok"], salvage: $("salvage").checked });
      return;
    } else if (step.kind === "probe") {
      await api("/api/probe", { paths: [], folders: [], states: ["unchecked"] });
    } else if (step.kind === "loop") {
      // Только то, что осталось: очередь круга и есть «не спасённое,
      // не удалённое, не исчезнувшее», минус свежий gone.
      const plan = await api("/api/download/loop/plan", {});
      if (!plan.files) { toast(t("loop.nothing")); return; }
      await api("/api/download/loop", {});
    } else if (step.kind === "stale") {
      await api("/api/probe", { paths: [], folders: [], states: ["stale"] });
    } else if (step.kind === "archive") {
      const p = await api("/api/archive", { paths: null });
      toast(t("arch.started", { n: p.files, size: human(p.bytes) }));
    } else if (step.kind === "autopilot") {
      await api("/api/autopilot", { on: true });
      toast(t("next.autopilot.done"));
    }
    await pollJobs();
    await refreshState(true);
  } catch (e) { toast(e.message, "err"); }
}

function renderNext(s) {
  const step = s.next_step || { kind: "done" };
  const card = $("next-card");
  const hasBtn = step.kind !== "busy" && step.kind !== "done";
  card.innerHTML =
    `<h4>${t("next.title")}</h4>
     <div class="lead">${t(`next.${step.kind}.lead`, { n: step.n || 0,
         files: t("n.files", { n: step.n || 0 }) })}</div>
     <div class="why">${t(`next.${step.kind}.why`, { n: step.n || 0,
         files: t("n.files", { n: step.n || 0 }),
         hours: step.hours || 0 })}</div>
     ${hasBtn ? `<button class="primary" id="next-go"
        style="width:100%">${t(`next.${step.kind}.btn`)}</button>` : ""}`;
  const go = $("next-go");
  if (go) go.onclick = () => wrap(go, () => runNextStep(step));
}

// ── подробности файла ───────────────────────────────────────────────

async function showDetail(path) {
  current = path;
  document.querySelectorAll(".node.sel").forEach((n) => n.classList.remove("sel"));
  const row = document.querySelector(`.node[data-path="${CSS.escape(path)}"]`);
  if (row) row.classList.add("sel");
  const d = await api("/api/file?path=" + encodeURIComponent(path));
  const age = hoursAgo(d.checked_at);
  const checked = d.checked_at
    ? t("detail.attempts", {
        s: new Date(d.checked_at * 1000).toLocaleString(I18N.lang)
           + " · " + t("detail.ago", { n: Math.round(age) }),
        n: d.attempts })
    : null;
  const staleMark = age !== null && age > PROBE_TTL_H
    ? ` <span class="badge hole">${t("detail.staleNote")}</span>` : "";
  const rows = [
    [t("detail.path"), `<span class="mono">${esc(d.path)}</span>`],
    [t("detail.size"), human(d.size)],
    [t("detail.type"), d.mime || "—"],
    [t("detail.modified"), d.modified || "—"],
    [t("detail.availability"), `<b>${d.probe_state}</b>`
      + (d.http_status ? ` (HTTP ${d.http_status})` : "") + staleMark],
    d.detail ? [t("detail.serverResponse"), `<span class="mono">${esc(d.detail)}</span>`] : null,
    d.storage_host ? [t("detail.storageHost"), `<span class="mono">${esc(d.storage_host)}</span>`] : null,
    checked ? [t("detail.checked"), checked] : null,
    [t("detail.md5"), `<span class="mono">${d.md5 || "—"}</span>`],
    [t("detail.sha256"), `<span class="mono">${d.sha256 || "—"}</span>`],
    d.local_path && d.verify
      ? [t("detail.localPath"),
         d.local_missing
           // Запись в базе есть, а файла на диске нет: обещать «лежит
           // здесь» и кнопку «открыть папку» в этом случае нельзя.
           ? `<span class="mono" style="opacity:.6">${esc(d.local_path)}</span><br>
              <span class="badge del">${t("detail.localMissing")}</span>`
           : `<span class="mono">${esc(d.local_path)}</span><br>`
             + `<button class="ghost" data-reveal="${esc(path)}">`
             + `${t("detail.openFolder")}</button>`]
      : null,
    d.verify ? [t("detail.rescued"),
      `${d.verify}${d.released ? t("detail.spaceFreed") : ""}`
      + (d.local_missing ? ` ${t("detail.localMissingShort")}` : "")] : null,
    d.holes ? [t("detail.holes"), `<span class="mono">${esc(d.holes)}</span>`] : null,
    [t("detail.previewState"), d.preview_state || "—"],
  ].filter(Boolean);
  $("detail").className = "detail";
  $("detail").innerHTML =
    `<h3>${esc(d.name)}</h3>`
    + (d.preview_state === "ok"
      ? `<img src="/api/preview?path=${encodeURIComponent(path)}" alt="">` : "")
    + `<dl class="kv">`
    + rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")
    + `</dl>`;
}

// ── работы и прогресс ───────────────────────────────────────────────

// Кнопки, которые запускают работу: пока работа этого вида идёт, кнопка
// неактивна (сервер и сам откажет 409).
const JOB_BUTTONS = {
  scan: "btn-scan", previews: "btn-previews", probe: "btn-probe",
  download: "btn-download", archive: "btn-archive",
  "cloud-delete": "btn-cloud-delete", adopt: "btn-adopt", mirror: "btn-mirror",
};

// Завершённые задачи можно скрыть: они остаются в базе и в логе, но
// перестают занимать место. Номер задачи нужен только логу, поэтому в
// строке его нет -- он в подсказке.
let hiddenUpTo = Number(localStorage.getItem("cr-jobs-hidden") || 0);

async function pollJobs() {
  try {
    const data = await api("/api/jobs?limit=12");
    const running = data.items.filter((j) => j.state === "running");
    setWindowTitle(running);
    const maxId = data.items.reduce((m, j) => Math.max(m, j.id), 0);
    localStorage.setItem("cr-jobs-last", String(maxId));
    renderActive(running);
    renderFinished(data.items.filter((j) => j.state !== "running"));
    for (const j of data.items) {
      if (j.state !== "running") stopping.delete(j.id);
    }
    // Пока работа идёт, её кнопка неактивна: сервер всё равно откажет
    // (409), но лучше не доводить до отказа. Стоп -- в карточке «Сейчас».
    const busy = new Set(running.map((j) => j.kind));
    for (const [kind, id] of Object.entries(JOB_BUTTONS)) {
      const el = $(id);
      if (el) el.disabled = busy.has(kind);
    }
    // В простое состояние тоже опрашивается, просто редко: по нему окно
    // узнаёт, что программу обновили, и перезагружает себя. Без этого
    // открытое без задач окно жило бы со старым интерфейсом сколько угодно.
    const every = running.length ? 5000 : 30000;
    if (Date.now() - lastStateAt > every) await refreshState();
    // Работа закончилась -- показываем итог сразу и без кэша.
    if (!running.length && wasRunning) await refreshState(true);
    wasRunning = running.length > 0;
  } catch (e) { /* сервер мог перезапуститься -- просто пробуем снова */ }
  // В простое незачем спрашивать каждые полторы секунды: задача идёт --
  // 1.5 с, ничего не происходит -- 5 с.
  setTimeout(pollJobs, wasRunning ? 1500 : 5000);
}

// Прогресс в заголовке окна: круг идёт часами, окно свёрнуто, и узнать
// «сколько ещё» иначе неоткуда -- разве что развернуть и посмотреть.
function setWindowTitle(running) {
  if (!running.length) {
    if (document.title !== "Drydock") document.title = "Drydock";
    return;
  }
  const j = running[0];
  const parts = [t("job." + j.kind)];
  if (j.total) {
    parts.push(`${j.done.toLocaleString(I18N.lang)}/${j.total.toLocaleString(I18N.lang)}`
      + ` · ${Math.round(100 * j.done / j.total)}%`);
  } else {
    parts.push(j.done.toLocaleString(I18N.lang));
  }
  if (running.length > 1) parts.push(`+${running.length - 1}`);
  document.title = `${parts.join(" · ")} — Drydock`;
}

// Что работает прямо сейчас. Задач может быть несколько, но обычно
// одна-две, поэтому карточка перечисляет их строками.
function renderActive(list) {
  const card = $("now-card");
  if (!list.length) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  card.className = "card now";
  card.innerHTML = `<h4>${t("now.title")}</h4>` + list.map((j) => {
    const indet = !j.total;
    const pct = indet ? 0 : Math.min(100, Math.round(100 * j.done / j.total));
    return `<div class="now-row" title="${t("jobs.id", { id: j.id })}">
      <div class="row2">
        <span class="nm">${t("job." + j.kind)}</span>
        <div class="bar${indet ? " indet" : ""}"><i style="width:${
          indet ? 35 : pct}%"></i></div>
        <span class="dim">${j.done}${j.total ? " / " + j.total : ""}</span>
        ${stopping.has(j.id)
          ? `<button class="ghost" disabled>${t("btn.stopping")}</button>`
          : `<button class="ghost" onclick="cancelJob(${j.id}, this)">${
              t("btn.stop")}</button>`}
      </div>
      <div class="dim msg">${esc(jobText(j.message))}</div>
    </div>`;
  }).join("");
}

// Завершённые -- внизу, без номеров и с возможностью скрыть.
// Высота подвала меняется (свёрнут / раскрыт), и уведомления должны
// подниматься вместе с ним, иначе закрывают строки задач.
function syncToastOffset() {
  const f = document.querySelector("footer");
  const h = f ? f.getBoundingClientRect().height : 0;
  document.documentElement.style.setProperty("--footer-h", (h + 8) + "px");
}

// Подвал свёрнут по умолчанию: шесть завершённых задач с полосками
// занимали четверть экрана и ничего не решали. Свёрнутый вид отвечает на
// один вопрос -- «всё ли прошло», подробности раскрываются по клику.
let jobsOpen = localStorage.getItem("cr-jobs-open") === "1";

window.toggleJobs = () => {
  jobsOpen = !jobsOpen;
  localStorage.setItem("cr-jobs-open", jobsOpen ? "1" : "0");
  pollJobs();
};

function renderFinished(list) {
  const shown = list.filter((j) => j.id > hiddenUpTo).slice(0, 12);
  const box = $("jobs");
  if (!shown.length) { box.innerHTML = ""; syncToastOffset(); return; }
  const done = shown.filter((j) => j.state === "done").length;
  const bad = shown.length - done;
  const head = `<div class="jobs-head">
      <button class="ghost" onclick="toggleJobs()" aria-expanded="${jobsOpen}"
        ><span class="tw">${jobsOpen ? "▾" : "▸"}</span>${
          jobsOpen ? t("jobs.collapse") : t("jobs.expand")}</button>
      <span class="dim">${t("jobs.recentN", { n: shown.length,
        jobs: t("n.jobs", { n: shown.length }) })}</span>
      <span class="ok" title="${t("jobs.okTitle")}">✓ ${done}</span>
      ${bad ? `<span class="bad" title="${t("jobs.badTitle")}">✕ ${bad}</span>` : ""}
      <span class="grow"></span>
      <button class="ghost" onclick="hideFinished()">${t("jobs.hide")}</button>
    </div>`;
  syncToastOffset();
  box.innerHTML = head + (jobsOpen ? shown.map((j) => {
    const pct = j.total ? Math.min(100, Math.round(100 * j.done / j.total)) : 100;
    const cls = j.state + (stopping.has(j.id) ? " stopping" : "");
    return `<div class="job ${cls}" title="${t("jobs.id", { id: j.id })}">
      <span class="nm">${t("job." + j.kind)}</span>
      <span class="bar"><i style="width:${pct}%"></i></span>
      <span class="st">${j.done}${j.total ? " / " + j.total : ""} · ${
        t("job.state." + j.state)}</span>
      <span class="msg">${esc(jobText(j.message))}</span>
    </div>`;
  }).join("") : "");
}

window.hideFinished = () => {
  // Скрываем всё, что уже завершилось на этот момент. Записи остаются в
  // базе и в логе -- пропадает только строка на экране.
  hiddenUpTo = Number(localStorage.getItem("cr-jobs-last") || hiddenUpTo);
  localStorage.setItem("cr-jobs-hidden", String(hiddenUpTo));
  pollJobs();
};

// Нажатие «стоп» должно быть заметно сразу: уже начатые файлы
// доигрываются, и без отметки это выглядит как проигнорированный клик.
const stopping = new Set();
window.cancelJob = async (id, btn) => {
  stopping.add(id);
  if (btn) { btn.disabled = true; btn.textContent = t("btn.stopping"); }
  try { await api(`/api/jobs/${id}/cancel`, {}); } catch (e) { stopping.delete(id); }
  await pollJobs();
};

// ── модальные окна ──────────────────────────────────────────────────

// ── узлы и кластеры ─────────────────────────────────────────────────
// Узел при выгрузке выбрать нельзя: ссылку выдаёт API Яндекса. Но
// повторный запрос иногда отдаёт другую машину -- это и есть «попробовать
// с другого узла». Показываем, где висит остаток и что узел отвечал.
function hostsTable(list, kind) {
  return `<table><thead><tr>
      <th>${t("hosts.name")}</th><th>${t("hosts.files")}</th>
      <th>${t("hosts.seen")}</th>
      <th>${t("hosts.size")}</th><th>${t("hosts.unavail")}</th>
      <th>${t("hosts.share")}</th><th></th></tr></thead><tbody>
    ${list.map((x) => `<tr>
      <td>${esc(x.name)}</td>
      <td>${x.files.toLocaleString(I18N.lang)}</td>
      <td class="dim">${(x.seen || 0).toLocaleString(I18N.lang)}</td>
      <td>${human(x.bytes)}</td>
      <td>${x.unavailable || ""}</td>
      <td>${Math.round((x.share || 0) * 100)}%</td>
      <td><button class="ghost" data-try-kind="${kind}"
          data-try-host="${esc(x.name)}"
          ${x.files ? "" : "disabled"}>${t("hosts.try")}</button></td>
    </tr>`).join("")}</tbody></table>`;
}

async function hostsModal() {
  const data = await api("/api/hosts");
  modal(t("hosts.title"),
    `<p class="dim">${t("hosts.how")}</p>
     <h4>${t("hosts.clusters")}</h4>${hostsTable(data.clusters || [], "cluster")}
     <h4>${t("hosts.nodes")}</h4>${hostsTable(data.hosts || [], "host")}`,
    [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }]);
}

// Правая кнопка: это окно программы, а не страница. Браузерное меню
// («сохранить страницу», «просмотр кода») здесь только мешает. Оставляем
// его там, где оно нужно -- в полях ввода и когда выделен текст.
document.addEventListener("contextmenu", (e) => {
  const el = e.target;
  const field = el.closest && el.closest("input, textarea, [contenteditable]");
  const picked = window.getSelection ? String(window.getSelection()) : "";
  if (field || picked) return;
  e.preventDefault();
});

// Кнопки с путём и узлом вешаем делегированием, а не строкой в onclick:
// апостроф в имени файла (O'Brien.docx) ломал такой обработчик -- строка
// обрывалась, и кнопка молча не работала.
document.addEventListener("click", (e) => {
  const reveal = e.target.closest ? e.target.closest("[data-reveal]") : null;
  if (reveal) { e.preventDefault(); revealFile(reveal.dataset.reveal); return; }
  const host = e.target.closest ? e.target.closest("[data-try-host]") : null;
  if (host && !host.disabled) {
    e.preventDefault();
    window.tryHost(host.dataset.tryKind, host.dataset.tryHost);
  }
});

window.tryHost = async (kind, name) => {
  try {
    const body = kind === "cluster" ? { cluster: name } : { host: name };
    const r = await api("/api/hosts/try", body);
    closeModal();
    await pollJobs();
    const what = r.cluster
      ? t("hosts.cluster", { name: r.cluster })
      : t("hosts.node", { name: r.host });
    toast(t("hosts.started", { n: r.files, what }));
  } catch (e) { toast(e.message, "err"); }
};

// Куда вернуть фокус после закрытия: без этого Tab начинается с начала
// страницы, и место, где работал, приходится искать заново.
let modalReturnFocus = null;

// ── командная палитра ───────────────────────────────────────────────
// Пятнадцать действий живут в «Ещё», и чтобы найти нужное, надо помнить
// его группу. Ctrl+K -- один вход: набрал «круг» и запустил. Палитра не
// заменяет кнопки, а снимает вопрос «куда положить новую».
let palIndex = 0;
let palShown = [];

function paletteCommands() {
  const hasSel = !!(sel.files.size || sel.folders.size);
  const loopN = (selPlan && selPlan.loop && selPlan.loop.files) || 0;
  const toggle = (on) => (on ? t("cmd.on") : t("cmd.off"));
  const cmds = [
    { label: t("act.scan"), kw: "scan inventory опись обход",
      run: () => $("btn-scan").click() },
    { label: t("act.loop"), kw: "loop круг качать скачать",
      hint: hasSel && loopN ? t("palette.ofSel", { n: loopN }) : "",
      run: () => $("btn-loop").click() },
    { label: t("act.archive"), kw: "archive архив паковать тома",
      run: () => $("btn-archive").click() },
    { label: t("act.delete"), kw: "delete удалить облако",
      run: () => $("btn-cloud-delete").click() },
    { label: t("tools.title"), kw: "tools инструменты ещё доп настройки",
      run: () => openTools() },
    { label: t("view.title"), kw: "view вид масштаб шрифт плотность тема",
      run: () => { $("view-pop").classList.remove("hidden"); paintView(); } },
    { label: t("health.title"), kw: "health здоровье отчёт лог ошибки",
      run: () => healthModal() },
    { label: t("hosts.title"), kw: "hosts узлы кластеры цод",
      run: () => hostsModal() },
    { label: t("btn.archives"), kw: "archives архивы тома",
      run: () => $("btn-archives").click() },
    { label: t("btn.adopt"), kw: "adopt учесть перенесённое папка",
      run: () => $("btn-adopt").click() },
    { label: t("btn.mirror"), kw: "mirror зеркало сверка",
      run: () => $("btn-mirror").click() },
    { label: t("btn.probe"), kw: "probe проверка доступность проба",
      run: () => $("btn-probe").click() },
    { label: t("btn.previews"), kw: "previews превью картинки",
      run: () => $("btn-previews").click() },
    { label: t("btn.log"), kw: "log журнал лог",
      run: () => $("btn-log").click() },
    { label: t("btn.settings"), kw: "settings настройки путь",
      run: () => $("btn-settings").click() },
    { label: t("btn.auth"), kw: "auth токен доступ",
      run: () => $("btn-auth").click() },
    { label: t("help.title"), kw: "help клавиши справка",
      run: () => helpModal() },
    { label: t("setup.title"), kw: "setup начало работы чеклист старт",
      run: () => {
        setupHidden = false;
        localStorage.removeItem("cr-setup-hidden");
        renderSetup(lastState || {});
      } },
    { label: t("theme.title"), kw: "theme тема светлая тёмная",
      hint: t("theme." + THEME),
      run: () => cycleTheme() },
    { label: `${t("cmd.lens")}: ${t("lens.now")}`, kw: "lens линза сейчас now",
      run: () => setLens("now") },
    { label: `${t("cmd.lens")}: ${t("lens.was")}`, kw: "lens линза было was",
      run: () => setLens("was") },
    { label: `${t("cmd.lens")}: ${t("lens.disk")}`, kw: "lens линза диск disk",
      run: () => setLens("disk") },
    { label: t("autopilot.label"), kw: "autopilot автопилот",
      hint: toggle($("autopilot").checked),
      run: () => $("autopilot").click() },
    { label: t("tree.showEmpty"), kw: "empty пустые показать",
      hint: toggle(showEmpty),
      run: () => $("btn-show-empty").click() },
    { label: t("btn.onlyUnsaved"), kw: "unsaved нескачанное фильтр",
      hint: toggle(onlyUnsaved),
      run: () => $("btn-only-unsaved").click() },
  ];
  if (hasSel) {
    cmds.push({ label: t("btn.clear"), kw: "clear снять выбор",
                run: () => $("btn-clear").click() });
  }
  return cmds;
}

function paintPalette() {
  const box = $("palette-list");
  if (!palShown.length) {
    box.innerHTML = `<div class="palette-empty">${t("palette.empty")}</div>`;
    return;
  }
  box.innerHTML = palShown.map((c, i) => `
    <div class="p-item${i === palIndex ? " on" : ""}" role="option"
         aria-selected="${i === palIndex}" data-i="${i}">
      <span>${esc(c.label)}</span>
      ${c.hint ? `<span class="hint">${esc(c.hint)}</span>` : ""}
    </div>`).join("");
  for (const el of box.querySelectorAll(".p-item")) {
    el.onclick = () => runPalette(Number(el.dataset.i));
  }
  const active = box.querySelector(".p-item.on");
  if (active) active.scrollIntoView({ block: "nearest" });
}

function filterPalette() {
  const q = $("palette-input").value.trim().toLowerCase();
  const all = paletteCommands();
  palShown = !q ? all : all.filter((c) =>
    // Ищем и по подписи, и по ключевым словам. Подпись переведена, поэтому
    // человек на любом языке найдёт команду своим словом; латинские
    // ключевые слова -- добавка для тех, кто привык к английским терминам.
    (c.label + " " + c.kw).toLowerCase().includes(q));
  palIndex = 0;
  paintPalette();
}

function openPalette() {
  $("palette").classList.remove("hidden");
  $("palette-input").value = "";
  filterPalette();
  $("palette-input").focus();
}

function closePalette() {
  $("palette").classList.add("hidden");
}

function runPalette(i) {
  const cmd = palShown[i];
  if (!cmd) return;
  closePalette();
  // Действие запускаем после закрытия: иначе модалка откроется под
  // палитрой и фокус останется в поле поиска.
  setTimeout(() => { try { cmd.run(); } catch (e) { toast(e.message, "err"); } }, 0);
}

function togglePalette() {
  if ($("palette").classList.contains("hidden")) openPalette();
  else closePalette();
}

$("palette").onclick = (e) => { if (e.target === $("palette")) closePalette(); };
$("palette-input").addEventListener("input", filterPalette);
$("palette-input").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!palShown.length) return;
    const d = e.key === "ArrowDown" ? 1 : -1;
    palIndex = (palIndex + d + palShown.length) % palShown.length;
    paintPalette();
    return;
  }
  if (e.key === "Enter") { e.preventDefault(); runPalette(palIndex); }
});

// ── здоровье: почему не выходит и что было по дням ──────────────────
// Считается на сервере по базе (probe, probe_history, local,
// cloud_deleted, jobs), а не по логу: лог в 50 МБ в интерфейсе не
// прочитать, а всё нужное уже записано.
function healthBars(days) {
  const max = Math.max(1, ...days.map((d) => Math.max(d.saved, d.deleted)));
  return days.map((d) => {
    const cap = d.day.slice(5).replace("-", ".");
    const sh = Math.round(100 * d.saved / max);
    const dh = Math.round(100 * d.deleted / max);
    return `<div class="h-col" title="${d.day}: ${t("health.saved")} ${d.saved}
      · ${t("health.deleted")} ${d.deleted}
      · ${t("health.probes")} ${d.probes_ok + d.probes_bad}">
      <div class="val">${d.saved || ""}</div>
      <div class="bars">
        <div class="b" style="height:${sh}%"></div>
        <div class="b del" style="height:${dh}%"></div>
      </div>
      <div class="cap">${cap}</div>
    </div>`;
  }).join("");
}

function healthRows(items, emptyText) {
  if (!items.length) return `<div class="dim">${emptyText}</div>`;
  return items.map((r) => `<div class="h-row">
      <span class="lbl">${esc(t("reason." + r.code))}</span>
      <span class="bar2"><i style="width:${Math.max(2, Math.round(r.share * 100))}%"></i></span>
      <span class="n">${r.n.toLocaleString(I18N.lang)} · ${Math.round(r.share * 100)}%</span>
    </div>`).join("");
}

function healthHtml(h) {
  const k = h.kpi;
  const kpi = `<div class="h-kpi">
      <div class="k good"><div class="n">${k.saved.toLocaleString(I18N.lang)}</div>
        <div class="l">${t("health.saved24")} · ${human(k.saved_bytes)}</div></div>
      <div class="k"><div class="n">${k.deleted.toLocaleString(I18N.lang)}</div>
        <div class="l">${t("health.deleted24")}</div></div>
      <div class="k"><div class="n">${k.probes.toLocaleString(I18N.lang)}</div>
        <div class="l">${t("health.probes24")}</div></div>
      <div class="k ${k.probes_bad ? "bad" : ""}">
        <div class="n">${k.probes_bad.toLocaleString(I18N.lang)}</div>
        <div class="l">${t("health.failed24")}</div></div>
    </div>`;

  const hosts = h.hosts.slice(0, 7).map((x) => `<div class="h-row">
      <span class="lbl" title="${esc(x.host)}">${
        x.cluster === "api" ? "API"
          : esc(x.cluster) + " · " + esc(x.host.split(".")[0])}</span>
      <span class="n">${x.bad.toLocaleString(I18N.lang)}</span>
      <span class="n">${Math.round(x.share * 100)}%</span>
      <button class="ghost" data-try-kind="host"
        data-try-host="${esc(x.host)}">${t("hosts.try")}</button>
    </div>`).join("");

  const failed = h.jobs.failed.length
    ? `<div class="h-jobs">${h.jobs.failed.map((j) =>
        `<div class="dim">${
          new Date(j.started_at * 1000).toLocaleString(I18N.lang)} · ${
          t("job." + j.kind)} · <span class="bad">${
          t("job.state." + j.state)}</span> · ${esc(jobText(j.message).slice(0, 90))}</div>`
      ).join("")}</div>`
    : "";

  return `${kpi}
    <h4>${t("health.days")}</h4>
    <div class="h-chart">${healthBars(h.days)}</div>
    <div class="h-legend">
      <span><i style="background:var(--ok)"></i>${t("health.saved")}</span>
      <span><i style="background:#4a5568"></i>${t("health.deleted")}</span>
    </div>
    <div class="h-cols">
      <div><h4>${t("health.reasons")}</h4>${healthRows(h.reasons, t("health.noFailures"))}</div>
      <div><h4>${t("health.hosts")}</h4>${hosts || `<div class="dim">${t("health.noFailures")}</div>`}</div>
    </div>
    <h4>${t("health.gone")}</h4>
    ${healthRows(h.gone, t("health.noFailures"))}
    <h4>${t("health.jobs")}</h4>
    <div>${t("health.jobsLine", { total: h.jobs.total, failed: h.jobs.failed_total })}</div>
    ${failed}
    <div class="h-note">${t("health.source")}</div>`;
}

window.healthModal = async () => {
  try {
    const h = await api("/api/health?days=7");
    modal(t("health.title"), healthHtml(h),
      [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }], "wide");
  } catch (e) { toast(e.message, "err"); }
};

function modal(title, bodyHtml, buttons, cls) {
  modalReturnFocus = document.activeElement;
  $("modal-box").className = "modal-box" + (cls ? " " + cls : "");
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = bodyHtml;
  $("modal-foot").innerHTML = "";
  for (const b of buttons) {
    const el = document.createElement("button");
    el.textContent = b.label;
    if (b.cls) el.className = b.cls;
    el.onclick = b.onClick;
    $("modal-foot").appendChild(el);
  }
  $("modal").classList.remove("hidden");
  // Фокус уходит внутрь диалога: иначе Tab уводит в дерево под ним.
  const first = $("modal-body").querySelector("input, select, textarea")
             || $("modal-foot").querySelector("button")
             || $("modal-close");
  if (first) first.focus();
}

function closeModal() {
  $("modal").classList.add("hidden");
  if (modalReturnFocus && modalReturnFocus.focus) modalReturnFocus.focus();
  modalReturnFocus = null;
}

$("modal-close").onclick = closeModal;
// Клик мимо окна закрывает: это ожидаемо везде, кроме формы с введённым
// текстом, но таких у нас нет -- модалки только спрашивают решение.
$("modal").onclick = (e) => { if (e.target === $("modal")) closeModal(); };
// Tab не должен выходить за пределы диалога.
$("modal").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const items = [...$("modal").querySelectorAll(
    "button, input, select, textarea, [href]")]
    .filter((el) => !el.disabled && el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault(); last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault(); first.focus();
  }
});

// ── настройки: куда спасаем ─────────────────────────────────────────

const attrEsc = (s) => esc(s).replace(/"/g, "&quot;");

window.settingsModal = async () => {
  const s = await api("/api/settings");
  modal(t("set.title"),
    `<p>${t("set.body")}</p>
     <input id="set-root" type="text" value="${attrEsc(s.save_root)}"
            style="width:100%;margin:6px 0">
     <p class="dim">${t("set.db", { db: esc(s.db) })}</p>
     <label class="set-port">${t("set.port")}
       <input id="set-port" type="number" min="1024" max="65535"
              value="${s.port}" ${s.port_from_env ? "disabled" : ""}>
     </label>
     <p class="dim">${s.port_from_env ? t("set.port.env") : t("set.port.hint")}</p>
     ${s.locked_by_env
        ? `<div class="warnbox">${t("set.envLock")}</div>`
        : `<div class="warnbox">${t("set.restart")}</div>`}`,
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("btn.save"), cls: "primary", onClick: async () => {
        const r = await api("/api/settings", {
          save_root: $("set-root").value,
          port: Number($("set-port").value) || undefined,
        });
        toast(t("set.saved", { root: r.chosen_root || r.save_root }) + "\n\n"
              + t("set.restart"));
        closeModal();
        await refreshState(true);
      } }]);
};
wrap($("btn-settings"), () => settingsModal());

// ── кнопки ──────────────────────────────────────────────────────────

function wrap(btn, fn) {
  btn.onclick = async () => {
    btn.disabled = true;
    try { await fn(); } catch (e) { toast(e.message, "err"); }
    finally { btn.disabled = false; await refreshState(); await pollJobs(); }
  };
}

wrap($("btn-scan"), async () => {
  // Прерванная опись продолжается с чекпоинта (очередь папок в базе),
  // но галочка «начать заново» отдаёт челу выбор -- как он и просил.
  await api("/api/scan", {
    root: "disk:/", previews: true,
    resume: !$("scan-restart").checked,
  });
});

wrap($("btn-adopt"), async () => {
  const s = await api("/api/adopt/survey", {});
  if (!s.exists) { toast(t("adopt.noFolder")); return; }
  if (!s.files && !s.linked) { toast(t("adopt.nothing")); return; }
  const byState = Object.entries(s.by_state || {})
    .map(([st, n]) => `${st}: ${n}`).join(", ");
  const total = (s.files || 0) + (s.linked || 0);
  modal(t("adopt.title"),
    (s.files
      ? t("adopt.body", { files: s.files, n: t("n.files", { n: s.files }),
                          size: human(s.bytes) })
        + (s.only_here
            ? `<div class="warnbox">${t("adopt.onlyWarn", { n: s.only_here })}</div>`
            : "")
        + (byState ? `<p class="dim">${t("adopt.states", { list: byState })}</p>` : "")
      : "")
    + (s.linked
        ? `<div class="warnbox">${t("adopt.linked", { n: s.linked,
                                                      size: human(s.linked_bytes) })}</div>`
        : "")
    + `<p>${t("adopt.moveNote")}</p>
       <label class="check"><input type="checkbox" id="adopt-del" checked>
         <span>${t("adopt.delCloud")}</span></label>
       <div class="warnbox">${t("adopt.delWarn")}</div>`,
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("adopt.go", { n: total }), cls: "primary", onClick: async () => {
        const deleteCloud = $("adopt-del").checked;
        closeModal();
        await api("/api/adopt", { mode: "move", verify: true,
                                  delete_cloud: deleteCloud });
        await pollJobs();
      } }]);
});

wrap($("btn-previews"), async () => { await api("/api/previews", {}); });

wrap($("btn-mirror"), async () => {
  const s = await api("/api/mirror/survey", {});
  if (!s.files) { toast(t("mirror.nothing")); return; }
  modal(t("mirror.title"),
    t("mirror.body", { files: s.files, n: t("n.files", { n: s.files }),
                       size: human(s.bytes), folders: s.folders })
    + t(s.with_cloud_meta ? "mirror.withMeta" : "mirror.noMeta",
        { n: s.with_cloud_meta })
    + t("mirror.how"),
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("mirror.go", { n: s.files }), cls: "primary", onClick: async () => {
        closeModal();
        await api("/api/mirror", {});
        await pollJobs();
      } }]);
});

wrap($("btn-hosts"), () => hostsModal());

wrap($("btn-probe"), async () => {
  const scope = $("probe-scope").value;
  const body = { paths: [], folders: [], states: null };
  if (scope === "selection") Object.assign(body, selectionBody());
  else if (scope === "unchecked") body.states = ["unchecked"];
  else if (scope === "unavailable") body.states = ["unavailable", "api_error", "unknown"];
  else if (scope === "stale") body.states = ["stale"];
  else body.recheck_all = true;
  const r = await api("/api/probe", body);
  if (!r.files) toast(t("probe.nothing"));
});

// Выгрузка с показом плана. Тело выбора приходит снаружи: из панели
// выбора (обычный клик) или из карточки «Что дальше» (вся коллекция).
async function downloadFlow(body) {
  const data = await api("/api/plan", body);
  const p = data.plan;
  modal(t("dl.title"),
    t("dl.body", { avail: p.will_try, files: t("n.files", { n: p.will_try }),
                   availSize: human(p.will_try_bytes),
                   already: p.already, alreadySize: human(p.already_bytes),
                   unavail: p.unavailable, unchecked: p.unchecked })
    + (body.salvage ? `<div class="warnbox">${t("dl.salvageWarn")}</div>` : "")
    + t("dl.note"),
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("dl.go", { n: p.will_try }), cls: "primary", onClick: async () => {
       closeModal();
       await api("/api/download", body);
       await pollJobs();
     } }]);
}

wrap($("btn-download"), () => {
  if (!sel.files.size && !sel.folders.size) return;  // кнопка выключена
  downloadFlow(selectionBody({ salvage: $("salvage").checked }));
});

wrap($("btn-loop"), async () => {
  const body = selectionBody({ salvage: $("salvage").checked });
  const plan = await api("/api/download/loop/plan", body);
  if (!plan.files) { toast(t("loop.nothing")); return; }
  modal(t("loop.title"),
    t("loop.plan", { n: plan.files, files: t("n.files", { n: plan.files }),
                     size: human(plan.bytes) })
    + `<div class="warnbox">${t("loop.why")}</div>`,
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("loop.go"), cls: "primary", onClick: async () => {
       closeModal();
       await api("/api/download/loop", body);
       await pollJobs();
     } }]);
});

// Настройки архивации: размер тома и сжатие. Запоминаются между
// запусками -- человек выбирает их один раз под свой Телеграм.
// Том задаётся в мегабайтах ползунком: 0 -- не дробить. Пресеты (1900 /
// 3900 / не дробить) остались кнопками -- это частые случаи.
const VOL_MIN = 0;
const VOL_MAX = 4000;
const VOL_STEP = 100;
const volMb = (v) => (String(v) === "0" ? 0 : Number(String(v).replace("m", "")) || 0);
const volStr = (mb) => (mb > 0 ? `${mb}m` : "0");
const ARCH_COMP = [["-mx0", "arch.comp.store"], ["-mx5", "arch.comp.normal"],
                   ["-mx9", "arch.comp.max"]];
let archOpts = {
  volume: localStorage.getItem("cr-arch-volume") || "3900m",
  compression: localStorage.getItem("cr-arch-comp") || "-mx0",
};

function archiveBody() {
  const extra = { volume: archOpts.volume, compression: archOpts.compression };
  // Что отмечено в дереве -- то и пакуем.
  if (sel.files.size || sel.folders.size) return selectionBody(extra);
  return { paths: null, folders: [], ...extra };
}

function archOptions(list, current) {
  return list.map(([value, key]) =>
    `<option value="${value}"${value === current ? " selected" : ""}>${
      esc(t(key))}</option>`).join("");
}

async function archiveModal() {
  const plan = await api("/api/archive/plan", archiveBody());
  if (!plan.files) { toast(t("arch.nothing")); return; }
  // arch.plan и arch.plan.volumes -- готовые абзацы (<p>…</p>). Внутри
  // общего блока они дают два абзаца с точкой посередине, поэтому
  // обёртку снимаем и склеиваем одной строкой.
  const bare = (html) => html.replace(/^<p>/, "").replace(/<\/p>$/, "");
  const summary = (p) => bare(t("arch.plan", {
    n: p.files, files: t("n.files", { n: p.files }), size: human(p.bytes),
  })) + " · " + (p.volumes
    ? bare(t("arch.plan.volumes", { vol: p.volume, k: p.volumes }))
    : t("arch.vol.none.short"));

  modal(t("arch.title"), `
    <div class="arch-row">
      <label for="arch-volume">${t("arch.volume")}</label>
      <div class="arch-slider">
        <input type="range" id="arch-volume" min="${VOL_MIN}" max="${VOL_MAX}"
               step="${VOL_STEP}" value="${volMb(archOpts.volume)}">
        <span id="arch-volume-val"></span>
      </div>
    </div>
    <div class="arch-row arch-presets">
      <button type="button" data-vol="1900"
              title="${t("arch.vol.1900")}">1900 ${t("unit.mb")}</button>
      <button type="button" data-vol="3900"
              title="${t("arch.vol.3900")}">3900 ${t("unit.mb")}</button>
      <button type="button" data-vol="0">${t("arch.vol.none")}</button>
    </div>
    <div class="arch-row">
      <label for="arch-comp">${t("arch.compression")}</label>
      <select id="arch-comp">${archOptions(ARCH_COMP, archOpts.compression)}</select>
    </div>
    <div id="arch-summary" class="arch-summary">${summary(plan)}</div>
    ${plan.selected ? "" : `<div class="warnbox">${t("arch.plan.whole")}</div>`}`,
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     { label: t("arch.list"), cls: "ghost", onClick: () => {
         closeModal(); $("btn-archives").click();
       } },
     { label: t("arch.go", { n: plan.files }), cls: "primary", onClick: async () => {
         closeModal();
         await api("/api/archive", archiveBody());
         await pollJobs();
       } }]);

  // Смена настроек -- пересчёт на месте, без закрытия окна.
  const paintVolume = () => {
    const mb = volMb(archOpts.volume);
    const val = $("arch-volume-val");
    if (val) val.textContent = mb ? `${mb} ${t("unit.mb")}` : t("arch.vol.none");
    for (const b of document.querySelectorAll(".arch-presets [data-vol]")) {
      b.classList.toggle("on", Number(b.dataset.vol) === mb);
    }
  };
  const refresh = async () => {
    archOpts.compression = $("arch-comp").value;
    localStorage.setItem("cr-arch-volume", archOpts.volume);
    localStorage.setItem("cr-arch-comp", archOpts.compression);
    paintVolume();
    try {
      const next = await api("/api/archive/plan", archiveBody());
      $("arch-summary").innerHTML = summary(next);
    } catch (e) { toast(e.message, "err"); }
  };
  paintVolume();
  $("arch-volume").oninput = () => {
    archOpts.volume = volStr(Number($("arch-volume").value));
    paintVolume();
  };
  // Пересчёт плана -- по отпусканию ползунка, а не на каждый шаг.
  $("arch-volume").onchange = refresh;
  $("arch-comp").onchange = refresh;
  for (const b of document.querySelectorAll(".arch-presets [data-vol]")) {
    b.onclick = () => {
      archOpts.volume = volStr(Number(b.dataset.vol));
      $("arch-volume").value = b.dataset.vol;
      refresh();
    };
  }
}

wrap($("btn-archive"), archiveModal);

// ── 3. Инструменты ───────────────────────────────────────────────────
function openTools() { $("tools").classList.remove("hidden"); }
function closeTools() { $("tools").classList.add("hidden"); }


wrap($("btn-archives"), async () => {
  const data = await api("/api/archives");
  const rows = data.items.map((a) => `
    <tr><td>${a.id}</td><td>${esc(a.name)}</td><td>${a.state}</td>
        <td>${a.files}</td>
        <td>${human((a.volumes || []).reduce((s, v) => s + (v.bytes || 0), 0))}</td>
        <td>${(a.volumes || []).length}</td>
        <td><button class="ghost" onclick="verifyArch(${a.id})">${t("arch.verify")}</button>
            <button class="ghost" onclick="releaseArch(${a.id})">${t("arch.release")}</button></td>
    </tr>`).join("");
  modal(t("arch.title"),
    (data.items.length
      ? `<table><tr><th>#</th><th>${t("arch.col.name")}</th><th>${t("arch.col.state")}</th>
           <th>${t("arch.col.files")}</th><th>${t("arch.col.size")}</th>
           <th>${t("arch.col.volumes")}</th><th></th></tr>${rows}</table>
         <p style="color:var(--fg-dim);margin-top:10px">${t("arch.note")}</p>`
      : `<p>${t("arch.none")}</p>`),
    [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }]);
});

window.verifyArch = async (id) => {
  const r = await api(`/api/archives/${id}/verify`, {});
  toast(t("arch.verifyResult", { ok: r.ok.length, bad: r.bad.length,
                                 missing: r.missing.length })
    + (r.bad.length ? "\n" + t("arch.corrupt", { list: r.bad.join(", ") }) : ""));
};
window.releaseArch = async (id) => {
  if (!confirm(t("arch.releaseConfirm"))) return;
  try {
    const r = await api(`/api/archives/${id}/release`, {});
    toast(t("arch.released", { n: r.released, files: t("n.files", { n: r.released }), size: human(r.freed_bytes) }));
    await refreshState();
  } catch (e) { toast(e.message, "err"); }
};

// Уровень удаления -- три разных решения, и раньше он прятался в
// выпадающем списке рядом с кнопкой. Теперь кнопка спрашивает.
async function cloudDeleteFlow(level) {
  const body = selectionBody({ level });
  const pre = await api("/api/cloud-delete/preview", body);
  const reasons = Object.entries(pre.reasons || {})
    .sort((a, b) => b[1] - a[1])
    .map(([r, n]) => `<tr><td>${n}</td><td>${esc(r)}</td></tr>`).join("");
  modal(t("del.title"),
    `<div class="warnbox">${t("del.warn")}</div>`
    + (level === "downloaded"
       ? `<div class="warnbox">${t("del.oneCopy")}</div>` : "")
    + (level === "junk"
       ? `<div class="warnbox">${t("del.junkWarn")}</div>` : "")
    + t("del.fits", { n: pre.allowed, files: t("n.files", { n: pre.allowed }), size: human(pre.allowed_bytes) })
    + t("del.blocked", { n: pre.blocked })
    + (reasons ? `<table><tr><th>${t("del.pcsCol")}</th>
         <th>${t("del.reasonCol")}</th></tr>${reasons}</table>` : "")
    + (pre.sample && pre.sample.length
       ? `<p style="margin-top:10px;color:var(--fg-dim)">${t("del.sample")}</p>
          <div class="mono">${pre.sample.map(esc).join("<br>")}</div>` : ""),
    [{ label: t("btn.cancel"), cls: "ghost", onClick: closeModal },
     ...(pre.allowed > 0 ? [{
       label: t("del.go", { n: pre.allowed }), cls: "danger",
       onClick: async () => {
         const ask = level === "junk"
           ? t("del.junkConfirm", { n: pre.allowed, files: t("n.files", { n: pre.allowed }) })
           : t("del.confirm", { n: pre.allowed, files: t("n.files", { n: pre.allowed }) });
         if (!confirm(ask)) return;
         closeModal();
         await api("/api/cloud-delete", selectionBody(
           { level, confirm: pre.confirm }));
         await pollJobs();
       },
     }] : [])]);
}

wrap($("btn-cloud-delete"), () => {
  const levels = [
    ["downloaded", "del.level.downloaded", "del.level.downloaded.why"],
    ["archived", "del.level.archived", "del.level.archived.why"],
    ["junk", "del.level.junk", "del.level.junk.why"],
  ];
  modal(t("del.choose"),
    `<p class="dim">${t("del.chooseWhy")}</p>`
    + levels.map(([v, k, why]) => `<div class="lvl">
         <b>${t(k)}</b><div class="dim">${t(why)}</div></div>`).join(""),
    [...levels.map(([v, k]) => ({
        label: t(k), cls: v === "junk" ? "danger" : "",
        onClick: () => { closeModal(); cloudDeleteFlow(v); },
      })),
     { label: t("btn.cancel"), cls: "ghost", onClick: closeModal }]);
});

// ── доступ к Диску ──────────────────────────────────────────────────
//
// Поля ввода одноразовые: значения уходят на сервер, в шифрованное
// хранилище, и обратно уже не возвращаются. UI видит только признаки.

async function authModal() {
  const st = await api("/api/auth/status");
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  const yes = (b) => b
    ? `<b style="color:var(--ok)">${t("auth.yes")}</b>`
    : `<b style="color:var(--bad)">${t("auth.no")}</b>`;
  let live = "";
  if (st.has_token) {
    try {
      const c = await api("/api/auth/check");
      live = `<p style="color:var(--ok)">${t("auth.works", {
        login: esc(c.login || "—"), used: human(c.used_space),
        total: human(c.total_space) })}</p>`;
    } catch (e) {
      live = `<p style="color:var(--bad)">${
        t("auth.rejected", { error: esc(e.message) })}</p>`;
    }
  }
  const until = st.expires_at
    ? new Date(st.expires_at * 1000).toLocaleString(I18N.lang) : "—";

  modal(t("auth.title"), `
    ${st.has_token ? accountBlock((lastState && lastState.account) || {}) : ""}
    ${live}
    <dl class="kv">
      ${row(t("auth.app"), st.has_app
        ? t("auth.appSet", { tail: esc(st.client_id_tail) })
        : `<b style="color:var(--bad)">${t("auth.appUnset")}</b>`)}
      ${row(t("auth.token"), yes(st.has_token))}
      ${row(t("auth.refresh"), yes(st.has_refresh))}
      ${row(t("auth.until"), until)}
      ${row(t("auth.scope"), esc(st.scope || "—"))}
      ${row(t("auth.store"), `<span class="mono">${esc(st.store)}</span>`)}
      ${row(t("auth.encryption"), st.encrypted
        ? t("auth.dpapi") : `<b style="color:var(--bad)">${t("auth.no")}</b>`)}
      ${row(t("auth.redirectUri"), `<span class="mono">${esc(st.redirect_uri)}</span>`)}
    </dl>

    <h4>${t("auth.step1")}</h4>
    <p style="color:var(--fg-dim)">${t("auth.step1note")}</p>
    <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 10px;align-items:center">
      <label>ClientID</label><input id="auth-id" type="text" autocomplete="off"
        placeholder="${st.has_app ? t("auth.placeholderSet") : ""}">
      <label>Client secret</label><input id="auth-secret" type="password"
        autocomplete="off" placeholder="${st.has_app ? t("auth.placeholderSet") : ""}">
    </div>
    <p style="margin-top:8px"><button id="auth-save">${t("auth.save")}</button></p>

    <h4>${t("auth.step2")}</h4>
    <p style="color:var(--fg-dim)">${t("auth.step2note")}</p>
    <p>
      <button id="auth-login" class="primary">${t("auth.openConsent")}</button>
      <button id="auth-manual" class="ghost">${t("auth.manual")}</button>
      ${st.has_refresh ? `<button id="auth-refresh" class="ghost">${t("auth.refreshBtn")}</button>` : ""}
      ${st.has_token ? `<button id="auth-logout" class="ghost">${t("auth.forget")}</button>` : ""}
    </p>
    <div id="auth-manual-box"></div>
  `, [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }]);

  $("auth-save").onclick = async () => {
    const id = $("auth-id").value.trim();
    const secret = $("auth-secret").value.trim();
    if (!id || !secret) { toast(t("auth.needBoth")); return; }
    try {
      await api("/api/auth/app", { client_id: id, client_secret: secret });
      $("auth-id").value = ""; $("auth-secret").value = "";
      toast(t("auth.saved"));
      await authModal();
    } catch (e) { toast(e.message, "err"); }
  };

  $("auth-login").onclick = async () => {
    try {
      const info = await api("/api/auth/start?manual=false", {});
      window.open(info.url, "_blank", "noreferrer");
      $("auth-manual-box").innerHTML =
        `<p style="color:var(--fg-dim)">${t("auth.waitReturn")}</p>`;
    } catch (e) { toast(e.message, "err"); }
  };

  $("auth-manual").onclick = async () => {
    try {
      const info = await api("/api/auth/start?manual=true", {});
      window.open(info.url, "_blank", "noreferrer");
      $("auth-manual-box").innerHTML = `
        <p style="color:var(--fg-dim)">${t("auth.codeHint")}</p>
        <input id="auth-code" type="text" autocomplete="off"
               placeholder="${t("auth.codePh")}">
        <button id="auth-code-go">${t("auth.codeGo")}</button>`;
      $("auth-code-go").onclick = async () => {
        try {
          await api("/api/auth/code", { code: $("auth-code").value.trim(),
                                        manual: true, state: info.state });
          toast(t("auth.gotToken")); await authModal(); await refreshState();
        } catch (e) { toast(e.message, "err"); }
      };
    } catch (e) { toast(e.message, "err"); }
  };

  const ab = $("auth-acc-refresh");
  if (ab) ab.onclick = async () => {
    ab.disabled = true;
    try {
      await api("/api/account/refresh", {});
      await refreshState(true);
      await authModal();
    } catch (e) { toast(e.message, "err"); ab.disabled = false; }
  };

  const rb = $("auth-refresh");
  if (rb) rb.onclick = async () => {
    try { await api("/api/auth/refresh", {}); toast(t("auth.refreshed")); await authModal(); }
    catch (e) { toast(e.message, "err"); }
  };
  const lb = $("auth-logout");
  if (lb) lb.onclick = async () => {
    if (!confirm(t("auth.forgetConfirm"))) return;
    await api("/api/auth/logout?keep_app=true", {});
    await authModal(); await refreshState();
  };
}

wrap($("btn-auth"), authModal);

// ── лог ─────────────────────────────────────────────────────────────

async function logModal(level) {
  const data = await api("/api/log?lines=400" + (level ? "&level=" + level : ""));
  const colour = (line) =>
    /\bERROR\b|\bCRITICAL\b/.test(line) ? "var(--bad)"
    : /\bWARNING\b/.test(line) ? "var(--warn)"
    : /\bDEBUG\b/.test(line) ? "var(--fg-dim)" : "var(--fg)";
  const body = data.lines.length
    ? data.lines.map((l) => `<div style="color:${colour(l)}">${esc(l)}</div>`).join("")
    : `<p>${t("log.empty")}</p>`;
  modal(t("log.title"), `
    <p style="color:var(--fg-dim)">
      <span class="mono">${esc(data.file)}</span><br>${t("log.hint")}
    </p>
    <p>
      <button onclick="logModal()">${t("log.all")}</button>
      <button onclick="logModal('WARNING')">${t("log.warnings")}</button>
      <button onclick="logModal('ERROR')">${t("log.errors")}</button>
    </p>
    <div class="mono" id="log-box" style="max-height:48vh;overflow:auto;
         background:var(--bg);border:1px solid var(--line);border-radius:6px;
         padding:8px;white-space:pre-wrap">${body}</div>`,
    [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }]);
  const box = $("log-box");
  if (box) box.scrollTop = box.scrollHeight;
}
window.revealFile = (enc) =>
  api("/api/reveal", { path: decodeURIComponent(enc) })
    .catch((e) => toast(e.message, "err"));
window.logModal = logModal;
wrap($("btn-log"), () => logModal());

$("btn-clear").onclick = () => {
  sel.files.clear(); sel.folders.clear();
  document.querySelectorAll('.node input[type=checkbox]')
    .forEach((c) => { c.checked = false; });
  refreshSelection();
};

$("f-ok").onchange = refreshSelection;
$("f-unsaved").onchange = refreshSelection;

let searchTimer = null;
$("search").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = $("search").value.trim();
    if (!q) { await loadTree(); return; }
    const data = await api("/api/search?q=" + encodeURIComponent(q));
    const box = $("tree");
    box.innerHTML = "";
    for (const it of data.items) {
      const node = Object.assign({ is_dir: false, bytes: it.size }, it);
      const r = nodeRow(node, 0, q);
      r.dataset.depth = 0;
      box.appendChild(r);
    }
    if (!data.items.length) {
      box.innerHTML = `<div class="detail empty" style="padding:14px">${
        t("search.empty")}</div>`;
    }
  }, 300);
};

// Смена языка перерисовывает всё, что собрано из строк в JS: статическую
// разметку обновляет сам i18n, а чипы, дерево и подписи -- мы.
function onLangChange() {
  return (async () => {
    // Подсказка у кнопки темы собрана из строк -- её надо пересобрать.
    applyTheme();
    await refreshState();
    await loadTree();
    await pollJobs();
    if (sel.files.size || sel.folders.size) refreshSelection();
    else $("selinfo").textContent = t("sel.hint");
    if (current) showDetail(current);
  })();
}

// ── клавиатура ──────────────────────────────────────────────────────
// Дерево на 27 тысяч строк мышью листать долго: стрелки и пробел делают
// то же самое, не отпуская рук с клавиатуры.
function focusRow(row) {
  if (!row) return;
  row.focus();
  row.scrollIntoView({ block: "nearest" });
}

// Справка по клавишам: ? открывает её, та же кнопка есть в шапке.
window.helpModal = () => {
  const rows = [
    ["/", t("help.search")],
    ["↑ ↓", t("help.move")],
    ["Space", t("help.select")],
    ["Enter", t("help.open")],
    ["← →", t("help.fold")],
    ["Esc", t("help.esc")],
    ["?", t("help.help")],
  ];
  modal(t("help.title"),
    `<table class="keys"><tbody>${rows.map(([k, what]) =>
      `<tr><td><kbd>${esc(k)}</kbd></td><td>${esc(what)}</td></tr>`).join("")}
     </tbody></table>`,
    [{ label: t("btn.close"), cls: "ghost", onClick: closeModal }]);
};

document.addEventListener("keydown", (e) => {
  const el = document.activeElement;
  const typing = el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
  const modalOpen = !$("modal").classList.contains("hidden");
  const paletteOpen = !$("palette").classList.contains("hidden");

  // Ctrl+K (Cmd+K) работает и во время набора -- это половина смысла
  // палитры: не надо убирать руки с клавиатуры.
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    togglePalette();
    return;
  }
  if (paletteOpen) {
    if (e.key === "Escape") { e.preventDefault(); closePalette(); }
    return;
  }

  if (e.key === "Escape") {
    if (!$("view-pop").classList.contains("hidden")) {
      $("view-pop").classList.add("hidden");
      return;
    }
    if (!$("tools").classList.contains("hidden")) { closeTools(); return; }
    if (modalOpen) { closeModal(); return; }
    if (el === $("search") && $("search").value) {
      $("search").value = "";
      loadTree();
      return;
    }
    if (el && el.classList && el.classList.contains("node")) $("search").focus();
    return;
  }
  if (typing || modalOpen) return;
  // «/» -- как в почте и трекерах: курсор в поиск, не мышью.
  if (e.key === "/") {
    e.preventDefault();
    $("search").focus();
    $("search").select();
    return;
  }
  if (e.key === "?") { e.preventDefault(); helpModal(); }
});

$("tree").addEventListener("keydown", (e) => {
  const row = e.target.closest ? e.target.closest(".node") : null;
  if (!row) return;
  const rows = [...$("tree").querySelectorAll(".node")];
  const i = rows.indexOf(row);
  const tw = row.querySelector(".twisty");
  const isDir = tw && !tw.classList.contains("leaf");

  if (e.key === "ArrowDown") {
    e.preventDefault(); focusRow(rows[i + 1]);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (i > 0) focusRow(rows[i - 1]); else $("search").focus();
  } else if (e.key === " ") {
    e.preventDefault();
    const cb = row.querySelector("input[type=checkbox]");
    if (cb) cb.click();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (isDir) tw.click(); else row.click();
  } else if (e.key === "ArrowRight") {
    if (isDir && tw.textContent === "▸") { e.preventDefault(); tw.click(); }
  } else if (e.key === "ArrowLeft") {
    if (isDir && tw.textContent === "▾") { e.preventDefault(); tw.click(); }
  }
});

// Из поиска вниз -- сразу в дерево, не переставляя руку на мышь.
$("search").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    focusRow($("tree").querySelector(".node"));
  }
});

// ── старт ───────────────────────────────────────────────────────────

(async () => {
  // Первый setLang тоже рассылает langchange. Если подписаться ДО него,
  // обработчик нарисует дерево, стартовый код нарисует его второй раз, и
  // обе отрисовки наложатся: каждая папка окажется в списке дважды.
  // Поэтому подписка -- после первичной загрузки языка.
  // null: язык определён автоматически, а не выбран человеком --
  // записывать его как выбор нельзя, иначе «авто» больше не сработает.
  await setLang(detectLang(), null);    // грузит словарь и красит разметку
  document.addEventListener("langchange", onLangChange);
  $("lang-slot").appendChild(langSelector());
  $("btn-help").onclick = helpModal;
  $("btn-palette").onclick = openPalette;
  initView();
  $("btn-view").onclick = (e) => { e.stopPropagation(); toggleView(); };
  applyTheme();
  applyView();
  $("btn-tools").onclick = openTools;
  $("tools-close").onclick = closeTools;
  $("tools").onclick = (e) => {
    // Клик мимо окна закрывает; клик по действию -- закрывает и выполняет.
    if (e.target === $("tools")) { closeTools(); return; }
    const action = e.target.closest("button[id^='btn-']");
    if (action && action.id !== "tools-close") setTimeout(closeTools, 0);
  };
  // Клик мимо поповера вида закрывает его.
  document.addEventListener("click", (e) => {
    const pop = $("view-pop");
    if (pop.classList.contains("hidden")) return;
    if (!pop.contains(e.target) && e.target.id !== "btn-view") {
      pop.classList.add("hidden");
    }
  });
  $("btn-health").onclick = () => healthModal();
  for (const b of $("lens").querySelectorAll("button")) {
    b.onclick = () => setLens(b.dataset.lens);
  }
  $("btn-show-empty").onclick = () => {
    showEmpty = !showEmpty;
    localStorage.setItem("cr-show-empty", showEmpty ? "1" : "0");
    paintLens();
    loadTree();
  };
  paintLens();
  await refreshState();
  refreshSelection();   // кнопки выбора стартуют выключенными
  // Ссылку можно дать с уже отмеченной папкой: ?select=disk:/Library,
  // с открытым поиском (?q=отчёт) и со справкой (?help=1).
  const params = new URLSearchParams(location.search);
  if (params.get("hosts") === "1") await hostsModal();
  if (params.get("help") === "1") helpModal();
  if (params.get("q")) {
    $("search").value = params.get("q");
    $("search").dispatchEvent(new Event("input"));
  }
  const selParam = new URLSearchParams(location.search).get("select");
  if (selParam) {
    sel.folders.add(selParam);
    await loadTree();
    refreshSelection();
  }
  await loadTree();
  await pollJobs();
})();
