/* ModMaestro — bibliothèque commune : traduction, état, API, actions, boîte de dialogue, animations. */
(() => {
  "use strict";
  const MM = window.MM || {};
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* stockage indisponible : on s'en passe */ } },
  };

  /* ---- Traduction : le texte français sert de clé (voir web/static/i18n/en.json) ------------------------ */
  let LANG = store.get("mm-lang") || ((navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en");
  let EN = {};
  const t = (fr, p) => {
    const s = LANG === "en" && EN[fr] !== undefined ? EN[fr] : fr;
    return p ? s.replace(/\{(\w+)\}/g, (m, k) => (p[k] !== undefined ? p[k] : m)) : s;
  };
  const tn = (n, one, many, p) => t((LANG === "en" ? n !== 1 : n > 1) ? many : one, { n, ...p });
  const size = (n) => {
    const u = LANG === "en" ? ["B", "KB", "MB", "GB"] : ["o", "Ko", "Mo", "Go"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${i === 0 ? n : n.toFixed(1)} ${u[i]}`;
  };
  const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleString(LANG === "en" ? "en-GB" : "fr-FR", { dateStyle: "short", timeStyle: "short" }) : t("jamais"));
  async function loadLang() {
    if (LANG === "en") {
      try { EN = await (await fetch("/static/i18n/en.json")).json(); } catch { EN = {}; }
    }
    document.documentElement.lang = LANG;
    $$("[data-t]").forEach((e) => (e.textContent = t(e.dataset.t)));
    $$("[data-t-title]").forEach((e) => { e.title = t(e.dataset.tTitle); e.setAttribute("aria-label", e.title); });
    $$("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  }

  /* ---- État partagé ------------------------------------------------------------------------------------------ */
  const S = {
    view: "home", a: null, online: store.get("mm-online") === "1", busy: null, homeError: "",
    motion: store.get("mm-motion") !== "off",
  };
  const views = {};   // nom -> { render(): string, after?(): void, title: () => string }
  const actions = {}; // data-act -> (element, event) => void
  const act = (name, fn) => { actions[name] = fn; };
  const setPath = (path, value) => {
    const parts = path.split(".");
    let o = S;
    for (const p of parts.slice(0, -1)) o = (o[p] ??= {});
    o[parts[parts.length - 1]] = value;
  };

  /* ---- API ------------------------------------------------------------------------------------------------------ */
  async function api(path, body) {
    const opt = { headers: { "X-MM-Token": MM.token || "" } };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify({ lang: LANG, ...body });
    } else if (path.startsWith("/api/")) {
      path += (path.includes("?") ? "&" : "?") + "lang=" + LANG;
    }
    let r;
    try { r = await fetch(path, opt); } catch { throw new Error(t("Impossible de joindre ModMaestro : le programme est-il toujours lancé ?")); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || t("Erreur {code}", { code: r.status }));
    return data;
  }
  /** Lance une tâche en arrière-plan et attend son résultat ; `onTick(job)` reçoit la progression. */
  async function runJob(start, onTick) {
    const { job } = await start;
    for (;;) {
      const j = await api(`/api/job/${job}`);
      onTick && onTick(j);
      if (j.state === "done") return j.result;
      if (j.state === "error") throw new Error(j.error);
      await new Promise((r) => setTimeout(r, 160));
    }
  }

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg; el.hidden = false;
    el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (el.hidden = true), 2600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast(t("Copié dans le presse-papiers")); }
    catch { toast(t("Copie impossible : sélectionne le texte à la main")); }
  }
  function download(text, name, type) {
    const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
    const el = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(el); el.click(); el.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  /* ---- Boîte de dialogue ---------------------------------------------------------------------------------------- */
  function dialog(title, body, foot = "") {
    $("#dlg-title").textContent = title;
    $("#dlg-body").innerHTML = body;
    $("#dlg-foot").innerHTML = foot;
    $("#dlg").hidden = false;
    const first = $("#dlg button, #dlg input");
    if (first) first.focus();
  }
  const closeDialog = () => ($("#dlg").hidden = true);

  /* ---- Rendu & navigation ------------------------------------------------------------------------------------------ */
  function render() {
    const v = views[S.view];
    const host = $("#view");
    host.innerHTML = v.render();
    host.classList.toggle("no-motion", !S.motion);
    v.after && v.after();
    $("#crumb-title").textContent = v.title ? v.title() : "";
    if (S.a) $("#crumb-path").textContent = S.a.mods_dir;
    countUps();
  }
  const NEEDS_ANALYSIS = new Set(["audit", "mods", "tips", "server", "export"]);
  function updateNav() {
    const has = !!S.a;
    $$(".nav-item").forEach((b) => {
      const v = b.dataset.view;
      b.disabled = NEEDS_ANALYSIS.has(v) && !has;
      if (v === S.view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    const ba = $("#badge-audit"), bm = $("#badge-mods");
    if (has) {
      const c = S.a.counts, n = c.errors + c.warnings;
      ba.hidden = false; ba.textContent = n || "✓";
      ba.className = "badge" + (c.errors ? "" : c.warnings ? " warn" : " ok");
      bm.hidden = false; bm.textContent = c.mods;
    } else { ba.hidden = true; bm.hidden = true; }
    $("#topbar").hidden = !has || S.view === "home";
  }
  function go(view) {
    S.view = view; updateNav(); render();
    $("#view").scrollTop = 0;
    const v = views[view];
    v.enter && v.enter();
  }
  /** Redessine sans perdre le défilement (formulaires, filtres). */
  function refresh() { const sc = $("#view").scrollTop; render(); $("#view").scrollTop = sc; }

  /* ---- Nombres qui « montent » --------------------------------------------------------------------------------------- */
  function countUps() {
    $$("[data-count]").forEach((el) => {
      const to = Number(el.dataset.count);
      if (!S.motion || matchMedia("(prefers-reduced-motion: reduce)").matches || !Number.isFinite(to)) { el.textContent = to; return; }
      const t0 = performance.now(), dur = 700;
      const tick = (now) => {
        const k = Math.min(1, (now - t0) / dur);
        el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  /* ---- Délégation d'événements --------------------------------------------------------------------------------------------- */
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (el && !el.disabled) { const fn = actions[el.dataset.act]; if (fn) fn(el, e); }
  });
  const onModel = (e) => {
    const el = e.target.closest("[data-model]");
    if (!el) return;
    setPath(el.dataset.model, el.type === "checkbox" ? el.checked : el.value);
    if (el.dataset.rerender !== undefined && e.type === "change") refresh();
  };
  document.addEventListener("input", onModel);
  document.addEventListener("change", onModel);
  /** Valeur d'un champ lié, avec repli sur sa valeur par défaut. */
  const model = (path, d = "") => path.split(".").reduce((o, k) => (o == null ? o : o[k]), S) ?? d;

  window.MMX = { MM, $, $$, esc, t, tn, size, fmtDate, store, S, views, actions, act, api, runJob, toast, copy, download, dialog, closeDialog,
    render, refresh, go, updateNav, model, setPath, loadLang, countUps, lang: () => LANG,
    setLang(l) { LANG = l === "en" ? "en" : "fr"; store.set("mm-lang", LANG); } };
})();
