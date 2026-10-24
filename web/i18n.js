"use strict";

// Перевод интерфейса.
//
// Языки выбраны по тому, где реально пользуются Яндексом: русский,
// английский, турецкий (Яндекс в Турции -- второй дом), казахский,
// узбекский, азербайджанский.
//
// Множественное число -- не косметика: "1 файл / 2 файла / 5 файлов"
// по-русски и "1 fayl / 5 fayl" по-азербайджански считаются по разным
// правилам, а в интерфейсе числа почти в каждой строке. Правила взяты из
// CLDR: русский -- one/few/many, тюркские и английский -- one/other.

const I18N = {
  lang: "ru",
  dict: {},
  fallback: {},
  ready: false,
};

const LANGS = [
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
  { code: "tr", name: "Türkçe" },
  { code: "kk", name: "Қазақша" },
  { code: "uz", name: "Oʻzbekcha" },
  { code: "az", name: "Azərbaycanca" },
];

// Правило one/few/many -- здесь только у русского; остальные по one/other.
const SLAVIC = new Set(["ru"]);

function pluralForm(lang, n) {
  const i = Math.abs(Math.trunc(n));
  if (SLAVIC.has(lang)) {
    const mod10 = i % 10, mod100 = i % 100;
    if (mod10 === 1 && mod100 !== 11) return "one";
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "few";
    return "many";
  }
  return i === 1 ? "one" : "other";
}

// Язык браузера, без учёта выбора человека. Нужен и при первом запуске,
// и для пункта «авто»: человек мог случайно выбрать не тот язык, и должен
// уметь вернуться к системному.
function detectAuto() {
  for (const tag of (navigator.languages || [navigator.language || "ru"])) {
    const code = String(tag).toLowerCase().split("-")[0];
    if (LANGS.some((l) => l.code === code)) return code;
  }
  return "ru";
}

// Явный выбор человека. Старый код сохранял язык при каждом запуске,
// поэтому одного cr-lang мало: без отметки cr-lang-manual это не выбор,
// а автоопределение, и его надо пересчитывать.
function savedLang() {
  try {
    if (localStorage.getItem("cr-lang-manual") !== "1") return null;
    const saved = localStorage.getItem("cr-lang");
    if (saved && LANGS.some((l) => l.code === saved)) return saved;
  } catch (e) { /* приватный режим -- просто берём язык браузера */ }
  return null;
}

function detect() {
  return savedLang() || detectAuto();
}

async function loadDict(code) {
  const resp = await fetch(`i18n/${code}.json`, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`нет словаря ${code}`);
  return resp.json();
}

// save: true -- человек выбрал язык, false -- вернулся к «авто»,
// null -- ничего не запоминать (первый запуск, автоопределение).
async function setLang(code, save = true) {
  I18N.lang = code;
  try {
    if (save === true) {
      localStorage.setItem("cr-lang", code);
      localStorage.setItem("cr-lang-manual", "1");
    } else if (save === false) {
      localStorage.removeItem("cr-lang");
      localStorage.removeItem("cr-lang-manual");
    }
  } catch (e) { /* не страшно */ }
  I18N.dict = await loadDict(code);
  if (code !== "ru" && !Object.keys(I18N.fallback).length) {
    // Русский -- язык оригинала: если в переводе строки нет, пусть будет
    // хоть она, а не пустое место или сырой ключ.
    I18N.fallback = await loadDict("ru");
  }
  I18N.ready = true;
  document.documentElement.lang = code;
  applyStatic();
  document.dispatchEvent(new CustomEvent("langchange", { detail: code }));
}

// t("btn.scan") -- строка.
// t("files.count", {n: 5}) -- с подстановкой и множественным числом:
// ключ ищется как files.count.one / .few / .many / .other.
function t(key, vars) {
  const n = vars && typeof vars.n === "number" ? vars.n : null;
  let value = null;
  if (n !== null) {
    const form = pluralForm(I18N.lang, n);
    value = I18N.dict[`${key}.${form}`]
         ?? I18N.fallback[`${key}.${form}`]
         ?? I18N.dict[`${key}.other`] ?? I18N.fallback[`${key}.other`];
  }
  if (value == null) value = I18N.dict[key] ?? I18N.fallback[key];
  if (value == null) return key;  // видно сразу, что строка не переведена
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      value = value.replaceAll(`{${k}}`, String(v));
    }
  }
  return value;
}

// Статическая разметка: data-i18n -- текст, data-i18n-title -- подсказка,
// data-i18n-ph -- placeholder.
function applyStatic(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  scope.querySelectorAll("[data-i18n-ph]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
}

// Язык нельзя искать по названию: человек, которому интерфейс достался
// на чужом языке, не узнает слово «Русский» в списке. Поэтому -- глобус
// и код языка на кнопке, а в списке каждый язык подписан сам собой.
function langSelector() {
  const wrap = document.createElement("span");
  wrap.className = "lang-wrap";

  const btn = document.createElement("button");
  btn.id = "btn-lang";
  btn.type = "button";
  btn.className = "ghost lang-btn";
  const ico = document.createElement("span");
  ico.className = "lang-ico";
  ico.textContent = "🌐";
  ico.setAttribute("aria-hidden", "true");
  const code = document.createElement("span");
  code.id = "lang-code";
  code.textContent = I18N.lang.toUpperCase();
  btn.append(ico, code);
  btn.title = t("lang.pick");

  const pop = document.createElement("div");
  pop.id = "lang-pop";
  pop.className = "view-pop lang-pop hidden";
  pop.setAttribute("role", "dialog");

  const row = (value, name, badge, on) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "lang-row" + (on ? " on" : "");
    el.dataset.lang = value;
    const n = document.createElement("span");
    n.className = "lr-n";
    n.textContent = name;
    const c = document.createElement("span");
    c.className = "lr-c";
    c.textContent = badge;
    el.append(n, c);
    return el;
  };

  const paint = () => {
    const auto = !savedLang();
    pop.replaceChildren();
    pop.appendChild(row("auto", t("lang.auto"), detectAuto().toUpperCase(), auto));
    for (const l of LANGS) {
      pop.appendChild(row(l.code, l.name, l.code.toUpperCase(),
                           !auto && l.code === I18N.lang));
    }
    code.textContent = I18N.lang.toUpperCase();
    btn.title = t("lang.pick");
  };

  btn.onclick = (e) => {
    e.stopPropagation();
    if (pop.classList.contains("hidden")) paint();
    pop.classList.toggle("hidden");
  };
  pop.onclick = (e) => {
    const picked = e.target.closest("[data-lang]");
    if (!picked) return;
    pop.classList.add("hidden");
    if (picked.dataset.lang === "auto") resetLang();
    else setLang(picked.dataset.lang);
  };
  document.addEventListener("click", (e) => {
    if (pop.classList.contains("hidden")) return;
    if (pop.contains(e.target) || btn.contains(e.target)) return;
    pop.classList.add("hidden");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.classList.contains("hidden")) {
      pop.classList.add("hidden");
    }
  });
  document.addEventListener("langchange", paint);

  return wrap.appendChild(btn), wrap.appendChild(pop), wrap;
}

async function resetLang() {
  await setLang(detectAuto(), false);
}

// Размеры: единицы тоже переводятся, и разделитель дробной части берём
// по локали -- "2.2 GB" против "2,2 ГБ".
function humanSize(bytes) {
  let v = Number(bytes || 0);
  const units = ["unit.b", "unit.kb", "unit.mb", "unit.gb", "unit.tb"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const num = i === 0
    ? String(Math.round(v))
    : v.toLocaleString(I18N.lang, { minimumFractionDigits: 1,
                                    maximumFractionDigits: 1 });
  return `${num} ${t(units[i])}`;
}

window.I18N = I18N;
window.LANGS = LANGS;
window.t = t;
window.setLang = setLang;
window.applyStatic = applyStatic;
window.langSelector = langSelector;
window.humanSize = humanSize;
window.detectLang = detect;
window.detectAuto = detectAuto;
window.resetLang = resetLang;
