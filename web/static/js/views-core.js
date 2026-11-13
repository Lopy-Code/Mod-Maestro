/* ModMaestro — vues principales : accueil, audit, mods, serveur, base. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, $$, esc, t, tn, size, fmtDate, S, views, act, api, runJob, toast, copy, download, dialog, closeDialog, refresh, go, model } = X;

  const ICON = {
    error: '<svg viewBox="0 0 24 24"><path d="M12 8v5M12 16.5v.01"/></svg>',
    warning: '<svg viewBox="0 0 24 24"><path d="M12 7v6M12 17v.01"/></svg>',
    info: '<svg viewBox="0 0 24 24"><path d="M12 11v6M12 7.5v.01"/></svg>',
    caret: '<svg class="caret" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    zip: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M11 6h2M11 9h2M11 12h2"/></svg>',
  };
  X.ICON = ICON;
  const SEV = () => ({ error: t("Erreur"), warning: t("Avertissement"), info: t("Info") });
  const SIDE = () => ({ client: t("Client"), server: t("Serveur"), both: t("Les deux"), unsure: t("À vérifier") });
  const CATS = () => [["all", t("Tout")], ["duplicates", t("Doublons")], ["dependencies", t("Dépendances")],
    ["versions", t("Versions")], ["compat", t("Compatibilité")], ["updates", t("Mises à jour")], ["files", t("Fichiers")]];
  const PHASE = () => ({ scan: t("Lecture des fichiers"), hash: t("Calcul des empreintes"), query: t("Interrogation de Modrinth"),
    projects: t("Récupération des fiches Modrinth"), updates: t("Recherche de mises à jour") });
  const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : "#");
  X.safeUrl = safeUrl;
  const ext = (url, label) => `<a class="ext" href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  X.ext = ext;

  Object.assign(S, { filter: "all", q: "", side: "all", showIgnored: false, overrides: {}, plan: null, bytes: 0,
    buildResult: null, buildError: "", kb: null, kbErr: "", learnErr: "", learnOk: false, importMsg: "", learnForm: newLearn(),
    logs: { text: "", path: "", findings: null, error: "" } });
  function newLearn() { return { kind: "conflict", a: "", b: "", severity: "error", note: "", candidates: [], hint: "" }; }

  /* ---- Analyse ---------------------------------------------------------------------------------------------- */
  const pbar = (j) => {
    const bar = $("#pbar"), lab = $("#plabel");
    if (!bar) return;
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    bar.style.width = `${pct}%`;
    if (j.total) bar.parentElement.classList.remove("indeterminate");
    if (lab) lab.textContent = j.total ? `${j.step ? `[${j.step}] ` : ""}${PHASE()[j.phase] || t("Analyse")}… ${j.done} / ${j.total}` : t("Recherche des fichiers .jar…");
  };
  X.pbar = pbar;
  async function analyze(path, demo = false) {
    S.homeError = ""; S.busy = { }; go("home");
    try {
      const res = await runJob(api(demo ? "/api/demo" : "/api/analyze", demo ? {} : { path, online: S.online }), pbar);
      loadResult(res);
    } catch (e) { S.busy = null; S.homeError = e.message; refresh(); }
  }
  X.analyze = analyze;
  function loadResult(res) {
    S.a = res; S.busy = null; S.overrides = {}; S.plan = res.plan;
    S.bytes = res.plan.keep.reduce((n, f) => n + sizeOf(f), 0);
    Object.assign(S, { buildResult: null, buildError: "", filter: "all", q: "", side: "all", showIgnored: false, kit: null, kitResult: null,
      kitError: "", exp: null, tips: null, crash: null, logs: { text: "", path: "", findings: null, error: "" } });
    go("audit");
  }
  const sizeOf = (file) => { const m = S.a.mods.find((x) => x.file === file); return m ? m.size : 0; };

  act("analyze", () => {
    const v = $("#path").value.trim();
    if (!v) { S.homeError = t("Indique le chemin du dossier mods, ou clique sur « Parcourir »."); return refresh(); }
    analyze(v);
  });
  act("demo", () => analyze("", true));
  act("online", (el) => { S.online = el.checked; X.store.set("mm-online", S.online ? "1" : "0"); });

  /* ---- Accueil -------------------------------------------------------------------------------------------------- */
  views.home = {
    title: () => "",
    render() {
      const busy = S.busy;
      const feat = (svg, h, p) => `<div class="feature"><svg viewBox="0 0 24 24">${svg}</svg><h3>${t(h)}</h3><p>${t(p)}</p></div>`;
      return `
      <section class="home">
        <div class="hero">
          <div>
            <h1>${t("Le chef d'orchestre de ton")} <em>${t("modpack")}</em>.</h1>
            <p class="lead">${t("Dépose le dossier mods : ModMaestro lit chaque mod, repère les doublons, les dépendances manquantes et les incompatibilités, puis prépare un dossier serveur propre.")}</p>
            <div class="drop">
              <input class="input" id="path" placeholder="${t("Colle le chemin de ton dossier mods…")}" spellcheck="false" value="${esc(S.pathInput ?? X.MM.initial ?? "")}" ${busy ? "disabled" : ""}>
              <button class="btn" data-act="browse" ${busy ? "disabled" : ""}>${t("Parcourir…")}</button>
              <button class="btn primary" data-act="analyze" ${busy ? "disabled" : ""}>${t("Analyser")}</button>
            </div>
            <label class="online-opt">
              <span class="switch"><input type="checkbox" data-act="online" ${S.online ? "checked" : ""} ${busy ? "disabled" : ""} aria-label="${t("Interroger Modrinth")}"></span>
              <span><b>${t("Interroger Modrinth")}</b> <span class="chip">${t("en ligne · facultatif")}</span>
                <small>${t("Reconnaît tes mods, fiabilise le tri client/serveur, trouve des incompatibilités et des mises à jour. Seule l'empreinte (SHA-1) de chaque .jar est envoyée : jamais les noms de fichiers ni ton dossier.")}</small></span>
            </label>
            ${busy ? `<div class="progress"><div class="progress-bar indeterminate"><i id="pbar"></i></div><div class="progress-label" id="plabel">${t("Recherche des fichiers .jar…")}</div></div>` : ""}
            ${S.homeError ? `<div class="err-box">${esc(S.homeError)}</div>` : ""}
            <div class="home-actions">
              <button class="link-btn" data-act="demo" ${busy ? "disabled" : ""}>${t("Essayer avec un modpack de démonstration →")}</button>
              <button class="link-btn" data-act="goto" data-to="compare">${t("Comparer deux modpacks →")}</button>
            </div>
            <p class="hint">${t("Par défaut, tout reste sur ton ordinateur et ton dossier d'origine n'est jamais modifié. Modrinth est la seule exception, et seulement si tu l'actives ci-dessus.")}</p>
          </div>
          <img class="hero-art" src="/assets/hero.svg" alt="">
        </div>
        <div class="features">
          ${feat('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>', "Doublons", "Deux versions du même mod ? ModMaestro garde la plus récente.")}
          ${feat('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>', "Dépendances", "Les mods manquants et les versions qui ne s'entendent pas.")}
          ${feat('<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>', "Incompatibilités", "Conflits déclarés par les auteurs et pièges connus (Sodium + OptiFine…).")}
          ${feat('<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>', "Dossier serveur", "Retire les mods clients et copie le reste dans un dossier propre.")}
        </div>
      </section>`;
    },
    after() { if (S.busy) pbar(S.busy); const p = $("#path"); if (p) p.addEventListener("input", () => (S.pathInput = p.value)); if (p) p.addEventListener("keydown", (e) => { if (e.key === "Enter") actions.analyze(); }); },
  };
  const actions = X.actions;
  act("goto", (el) => go(el.dataset.to));

  /* ---- Audit ---------------------------------------------------------------------------------------------------- */
  const srcChip = (i) => {
    const src = i.data && i.data.source;
    if (!src) return "";
    return src === "modrinth" ? `<span class="chip src" title="${t("Donnée issue de Modrinth")}">Modrinth</span>` : `<span class="chip src" title="${esc(src)}">${t("Base de connaissances")}</span>`;
  };
  const confChip = (i) => (i.confidence === "likely" ? `<span class="chip likely" title="${t("Probable, mais pas certain : vérifie avant de t'inquiéter.")}">${t("probable")}</span>` : "");
  const updatesTable = (u) => (u && u.length ? `<div class="table-wrap"><table><thead><tr><th>${t("Mod")}</th><th>${t("Installée")}</th><th>${t("Disponible")}</th><th></th></tr></thead><tbody>${u.map((x) => `<tr><td class="nm">${esc(x.name)}</td><td>${esc(x.current)}</td><td>${esc(x.latest)}</td><td>${ext(x.url, "Modrinth ↗")}</td></tr>`).join("")}</tbody></table></div>` : "");

  function bootBanner(a) {
    const b = a.boot;
    if (!b || !b.fresh || b.status === "unknown") return "";
    const ok = b.status === "ok";
    return `<div class="boot ${ok ? "ok" : "bad"}"><b>${ok ? t("Ce modpack a bien démarré") : t("Le dernier lancement a échoué")}</b>
      <span>${ok ? t("D'après {log}, le jeu a fini de se charger : les alertes ci-dessous sont donc à prendre avec du recul.", { log: b.log })
        : t("D'après {log}, le jeu s'est arrêté avant la fin du chargement.", { log: b.log })}</span>
      ${ok ? "" : `<button class="btn sm" data-act="goto" data-to="crash">${t("Chercher la cause")}</button>`}</div>`;
  }

  views.audit = {
    title: () => t("Audit du modpack"),
    render() {
      const a = S.a, c = a.counts, circ = 2 * Math.PI * 54;
      const verdictText = { ok: t("Ton modpack est en pleine forme"), warn: t("Quelques points à surveiller"), bad: t("Ce modpack ne démarrera probablement pas") }[a.verdict];
      const live = a.issues.filter((i) => !i.ignored), ign = a.issues.filter((i) => i.ignored);
      const cats = { all: live.length };
      live.forEach((i) => (cats[i.category] = (cats[i.category] || 0) + 1));
      const list = live.filter((i) => S.filter === "all" || i.category === S.filter);
      const row = (i, open) => `
        <details class="issue ${i.severity} ${i.ignored ? "is-ignored" : ""}" ${open ? "open" : ""}>
          <summary><span class="sev" title="${SEV()[i.severity]}">${ICON[i.severity]}</span>
            <div class="issue-main"><div class="issue-title">${esc(i.title)}${confChip(i)}${srcChip(i)}</div><div class="issue-msg">${esc(i.message)}</div></div>${ICON.caret}</summary>
          <div class="issue-body">
            ${i.fix ? `<div class="fix"><b>${t("À faire :")}</b> ${esc(i.fix)}</div>` : ""}
            ${i.files.length ? `<div class="files">${i.files.map((f) => `<span class="chip mono">${esc(f)}</span>`).join("")}</div>` : ""}
            ${i.links.length ? `<div class="links">${i.links.map((l) => ext(l.url, `${t("Chercher sur {site}", { site: esc(l.label) })} ↗`)).join("")}</div>` : ""}
            ${updatesTable(i.data && i.data.updates)}
            <div class="issue-actions">${i.ignored
              ? `<button class="btn sm" data-act="unignore" data-id="${esc(i.id)}">${t("Ne plus ignorer")}</button>`
              : (i.severity !== "info" ? `<button class="btn sm" data-act="ignore" data-id="${esc(i.id)}" title="${t("C'est une fausse alerte : ModMaestro ne la signalera plus pour ce pack.")}">${t("Ignorer cette alerte")}</button>` : "")}</div>
          </div></details>`;
      const empty = `<div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${S.filter === "all" ? t("Rien à signaler") : t("Rien dans cette catégorie")}</h3>
        <p>${S.filter === "all" ? t("Aucun doublon, aucune dépendance manquante, aucune incompatibilité détectée.") : t("Cette catégorie est propre.")}</p></div>`;
      const canAll = live.some((i) => i.severity !== "info");
      return `
      <section>
        ${bootBanner(a)}
        <div class="summary">
          <div class="ring ${a.verdict}"><svg viewBox="0 0 132 132"><circle class="track" cx="66" cy="66" r="54" fill="none"/><circle class="val" cx="66" cy="66" r="54" fill="none" stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="${circ * (1 - a.score / 100)}" style="--from:${circ}"/></svg>
            <div class="ring-num"><div><b data-count="${a.score}">${a.score}</b><br><span>/ 100</span></div></div></div>
          <div>
            <h2>${verdictText}</h2>
            <div class="meta">
              <span class="chip accent">${esc(a.loader_label)}</span>
              ${a.mc_version ? `<span class="chip">Minecraft ${esc(a.mc_version)}</span>` : ""}
              <span class="chip">${tn(c.mods, "{n} mod", "{n} mods")} · ${tn(c.jars, "{n} fichier", "{n} fichiers")}</span>
              ${c.bundled ? `<span class="chip">${tn(c.bundled, "{n} intégré (jar-in-jar)", "{n} intégrés (jar-in-jar)")}</span>` : ""}
              <span class="chip">${size(c.size)}</span>
              ${a.online && a.online.enabled ? `<span class="chip accent" title="${t("Fichiers reconnus par empreinte SHA-1")}">${t("Modrinth : {a}/{b} reconnus", { a: a.online.identified, b: a.online.total })}</span>`
                : `<span class="chip" title="${t("Active « Interroger Modrinth » sur l'accueil pour des résultats plus précis")}">${t("Hors ligne")}</span>`}
            </div>
            ${a.notes.length ? `<div class="notes">${a.notes.map(esc).join(" · ")}</div>` : ""}
          </div>
        </div>
        <div class="stats">
          <div class="stat err"><b data-count="${c.errors}">${c.errors}</b><span>${tn(c.errors, "erreur", "erreurs")}</span></div>
          <div class="stat warn"><b data-count="${c.warnings}">${c.warnings}</b><span>${tn(c.warnings, "avertissement", "avertissements")}</span></div>
          <div class="stat"><b data-count="${c.server_remove}">${c.server_remove}</b><span>${t("à retirer du serveur")}</span></div>
          <div class="stat"><b data-count="${c.server_unsure}">${c.server_unsure}</b><span>${t("à vérifier côté serveur")}</span></div>
        </div>
        ${canAll || ign.length ? `<div class="works">
          <div><b>${t("Ton modpack fonctionne déjà ?")}</b> <span>${t("Si le jeu se lance bien, ces alertes sont probablement de fausses alertes. Tu peux toutes les mettre de côté : elles resteront consultables, et les nouveaux problèmes seront signalés.")}</span></div>
          ${canAll ? `<button class="btn" data-act="ignore-all">${t("Ce modpack fonctionne : tout ignorer")}</button>` : ""}
        </div>` : ""}
        <div class="tabs" role="group" aria-label="${t("Filtrer")}">
          ${CATS().filter(([k]) => k === "all" || cats[k]).map(([k, l]) => `<button class="tab" data-act="filter" data-k="${k}" aria-pressed="${S.filter === k}">${l} <small>${cats[k] || 0}</small></button>`).join("")}
        </div>
        <div class="issues">${list.map((i) => row(i, list.length <= 3)).join("") || empty}</div>
        ${ign.length ? `<button class="link-btn ign-toggle" data-act="toggle-ignored">${S.showIgnored ? t("Masquer") : t("Afficher")} ${tn(ign.length, "{n} alerte ignorée", "{n} alertes ignorées")}</button>
          ${S.showIgnored ? `<div class="issues">${ign.map((i) => row(i, false)).join("")}</div>` : ""}` : ""}
      </section>`;
    },
  };
  act("filter", (el) => { S.filter = el.dataset.k; refresh(); });
  act("toggle-ignored", () => { S.showIgnored = !S.showIgnored; refresh(); });
  async function reanalyze() { await analyze(S.a.source); }
  act("ignore", async (el) => {
    try { await api("/api/ignore", { id: el.dataset.id }); toast(t("Alerte ignorée pour ce pack")); await reanalyze(); } catch (e) { toast(e.message); }
  });
  act("ignore-all", async () => {
    try { const r = await api("/api/ignore", { all: true, analysis: S.a.id }); toast(t("{n} alerte(s) mises de côté", { n: r.ignored })); await reanalyze(); } catch (e) { toast(e.message); }
  });
  act("unignore", async (el) => {
    const rid = S.a.ignored_rows && S.a.ignored_rows[el.dataset.id];
    if (!rid) return;
    try { await api("/api/learn/delete", { id: rid }); await reanalyze(); } catch (e) { toast(e.message); }
  });

  /* ---- Mods ---------------------------------------------------------------------------------------------------- */
  views.mods = {
    title: () => t("Liste des mods"),
    render() {
      return `<section><div class="toolbar">
        <input class="input" id="q" type="search" placeholder="${t("Rechercher un mod…")}" value="${esc(S.q)}">
        <select class="input" id="side" aria-label="${t("Filtrer par côté")}">
          ${[["all", t("Tous les côtés")], ["client", t("Client")], ["server", t("Serveur")], ["both", t("Les deux")], ["unsure", t("À vérifier")]].map(([k, l]) => `<option value="${k}" ${S.side === k ? "selected" : ""}>${l}</option>`).join("")}
        </select></div><div id="modtable"></div></section>`;
    },
    after() {
      $("#q").addEventListener("input", (e) => { S.q = e.target.value; fillMods(); });
      $("#side").addEventListener("change", (e) => { S.side = e.target.value; fillMods(); });
      fillMods();
    },
  };
  function fillMods() {
    const q = S.q.trim().toLowerCase();
    const rows = S.a.mods.filter((m) => S.side === "all" || m.side === S.side)
      .filter((m) => !q || `${m.name} ${m.modid || ""} ${m.file}`.toLowerCase().includes(q))
      .sort((x, y) => x.name.localeCompare(y.name, X.lang(), { sensitivity: "base" }));
    const shown = rows.slice(0, 1500);
    $("#modtable").innerHTML = rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>${t("Mod")}</th><th>${t("Version")}</th><th>${t("Loader")}</th><th>${t("Côté")}</th><th>${t("Fichier")}</th></tr></thead>
      <tbody>${shown.map((m) => `<tr><td><div class="nm">${m.online ? ext(m.online.url, esc(m.name)) : esc(m.name)}</div>${m.modid ? `<div class="id">${esc(m.modid)}</div>` : ""}</td>
        <td>${esc(m.version || "—")}</td><td>${m.loader ? esc(m.loader) : `<span class="pill bad">${t("illisible")}</span>`}</td>
        <td><span class="pill ${m.side}" title="${esc(m.side_reason || "")}">${SIDE()[m.side]}</span></td><td class="file">${esc(m.file)}</td></tr>`).join("")}</tbody></table></div>
      <div class="count-note">${tn(rows.length, "{n} mod affiché", "{n} mods affichés")}${rows.length > shown.length ? ` ${t("({n} premiers)", { n: shown.length })}` : ""}</div>`
      : `<div class="empty"><img src="/assets/illustrations/welcome.svg" alt=""><h3>${t("Aucun résultat")}</h3><p>${t("Essaie un autre mot-clé ou un autre filtre.")}</p></div>`;
  }

  /* ---- Serveur : plan de copie + kit de lancement ------------------------------------------------------------------- */
  const picks = () => { const ex = [], inc = []; for (const [f, v] of Object.entries(S.overrides)) (v === "include" ? inc : ex).push(f); return { exclude: ex, include: inc }; };
  X.picks = picks;
  views.server = {
    title: () => t("Dossier serveur"),
    render() {
      const a = S.a, p = S.plan;
      const all = [...p.keep, ...p.remove.map((r) => r.file)].sort((x, y) => x.toLowerCase().localeCompare(y.toLowerCase()));
      const keepSet = new Set(p.keep), why = {};
      [...p.remove, ...p.restored, ...p.unsure].forEach((r) => (why[r.file] = r.reason));
      const unsure = new Set(p.unsure.map((u) => u.file));
      const row = (f) => `<div class="row"><div class="grow"><div class="nm">${esc(f)}</div>${why[f] ? `<div class="why">${unsure.has(f) ? "⚠ " : ""}${esc(why[f])}</div>` : ""}</div>
        ${S.overrides[f] ? `<span class="chip">${t("modifié")}</span>` : ""}
        <label class="switch" title="${keepSet.has(f) ? t("Sera copié sur le serveur") : t("Ne sera pas copié")}"><input type="checkbox" data-act="toggle-file" data-file="${esc(f)}" ${keepSet.has(f) ? "checked" : ""} aria-label="${esc(f)}"></label></div>`;
      const removed = all.filter((f) => !keepSet.has(f)), kept = all.filter((f) => keepSet.has(f));
      const toVerify = kept.filter((f) => unsure.has(f)), rest = kept.filter((f) => !unsure.has(f));
      const dirty = Object.keys(S.overrides).length;
      const warn = p.warnings.length ? `<div class="warn-box"><b>${t("Attention :")}</b> ${t("ces mods gardés ont besoin d'un mod que tu as retiré.")}<ul>${p.warnings.map((w) => `<li>${t("{name} a besoin de {missing} ({provider})", { name: `<b>${esc(w.name)}</b>`, missing: `<code>${esc(w.missing)}</code>`, provider: esc(w.provider) })}</li>`).join("")}</ul></div>` : "";
      const res = S.buildResult ? `<div class="success"><b>${t("Dossier serveur créé !")}</b> ${tn(S.buildResult.copied, "{n} mod copié", "{n} mods copiés")} (${size(S.buildResult.bytes)}).
        <code>${esc(S.buildResult.output)}</code>${S.buildResult.zip ? `<code>${esc(S.buildResult.zip)}</code>` : ""}
        <div class="build-line" style="margin-top:10px"><button class="btn sm" data-act="copy" data-v="${esc(S.buildResult.output)}">${t("Copier le chemin")}</button></div></div>` : "";
      return `
      <section>
        <div class="server-head"><div><h2>${t("Prépare ton serveur")}</h2>
          <p>${t("Les mods qui ne servent qu'au joueur (rendu, minimap, interface) n'ont rien à faire sur un serveur dédié. Voici ce qui sera copié ; tu peux corriger chaque choix.")}</p>
          <div class="kpis"><span class="chip accent">${t("{n} gardés", { n: p.keep.length })}</span><span class="chip">${t("{n} retirés", { n: p.remove.length })}</span><span class="chip">${size(S.bytes)}</span>
            ${dirty ? `<button class="btn sm" data-act="reset-plan">${t("Revenir à la proposition")}</button>` : ""}</div></div>
          <img src="/assets/illustrations/server.svg" alt=""></div>
        ${warn}
        <div class="build-card">
          <label class="field">${t("Dossier de destination")}<input class="input mono" data-model="outPath" value="${esc(S.outPath ?? a.suggested.server)}" spellcheck="false"></label>
          <div class="build-line"><label class="check"><input type="checkbox" data-model="zip" ${S.zip ? "checked" : ""}> ${t("Créer aussi une archive .zip")}</label><span class="grow"></span>
            <button class="btn primary lg" data-act="build" ${S.busyBuild ? "disabled" : ""}>${S.busyBuild ? t("Copie en cours…") : t("Créer le dossier serveur")}</button></div>
          ${S.buildError ? `<div class="err-box" style="margin:0">${esc(S.buildError)}</div>` : ""}${res}
        </div>
        ${kitCard()}
        ${removed.length ? `<div class="group-title"><h3>${t("Retirés du serveur")}</h3><span>${removed.length}</span></div><div class="rows">${removed.map(row).join("")}</div>` : ""}
        ${toVerify.length ? `<div class="group-title"><h3>${t("À vérifier")}</h3><span>${t("gardés par défaut — retire-les si tu es sûr qu'ils sont inutiles côté serveur")}</span></div><div class="rows">${toVerify.map(row).join("")}</div>` : ""}
        <div class="group-title"><h3>${t("Gardés")}</h3><span>${rest.length}</span></div><div class="rows">${rest.map(row).join("") || `<div class="row"><div class="grow why">${t("Aucun.")}</div></div>`}</div>
      </section>`;
    },
  };

  function kitCard() {
    const a = S.a, d = a.server_defaults;
    const k = (S.kit ??= { out: a.suggested.kit, ram: d.ram, port: 25565, players: 20, motd: "", vd: 10, sd: 8, eula: false, withMods: true });
    const r = S.kitResult;
    return `<div class="build-card kit" id="kit">
      <h3 class="card-title">${t("Fichiers de lancement optimisés")}</h3>
      <p class="muted">${t("Génère les scripts de démarrage (Windows et Linux/macOS), un server.properties raisonnable et les paramètres Java adaptés à ton pack : Java {java} pour Minecraft {mc}.", { java: d.java, mc: a.mc_version || "?" })}</p>
      <div class="two">
        <label class="field">${t("Dossier de destination")}<input class="input mono" data-model="kit.out" value="${esc(k.out)}" spellcheck="false"></label>
        <label class="field">${t("Mémoire (Go)")}<input class="input" type="number" min="1" max="64" data-model="kit.ram" value="${esc(k.ram)}"></label>
        <label class="field">${t("Port")}<input class="input" type="number" min="1" max="65535" data-model="kit.port" value="${esc(k.port)}"></label>
        <label class="field">${t("Joueurs max.")}<input class="input" type="number" min="1" max="1000" data-model="kit.players" value="${esc(k.players)}"></label>
        <label class="field">${t("Distance d'affichage")}<input class="input" type="number" min="2" max="32" data-model="kit.vd" value="${esc(k.vd)}"></label>
        <label class="field">${t("Distance de simulation")}<input class="input" type="number" min="2" max="32" data-model="kit.sd" value="${esc(k.sd)}"></label>
      </div>
      <label class="field">${t("Message d'accueil (MOTD)")}<input class="input" maxlength="120" data-model="kit.motd" value="${esc(k.motd)}"></label>
      <label class="check"><input type="checkbox" data-model="kit.withMods" ${k.withMods ? "checked" : ""}> ${t("Copier aussi les mods du serveur dans ce dossier")}</label>
      <label class="check eula"><input type="checkbox" data-model="kit.eula" ${k.eula ? "checked" : ""}> ${t("J'ai lu et j'accepte le contrat de licence de Minecraft (EULA)")} ${ext("https://www.minecraft.net/eula", "↗")}</label>
      <div class="hint" style="margin:0">${t("Sans cette case, eula.txt reste à « false » : tu l'accepteras toi-même.")}</div>
      ${S.kitError ? `<div class="err-box" style="margin:0">${esc(S.kitError)}</div>` : ""}
      <div class="build-line"><span class="grow"></span><button class="btn primary" data-act="kit" ${S.busyKit ? "disabled" : ""}>${S.busyKit ? t("Création…") : t("Générer les fichiers")}</button></div>
      ${r ? `<div class="success"><b>${t("Kit créé !")}</b> Java ${esc(r.java)} · ${r.ram} ${t("Go")}<code>${esc(r.output)}</code>
        <div class="files" style="margin-top:8px">${r.written.map((f) => `<span class="chip mono">${esc(f)}</span>`).join("")}</div>
        ${r.notes.map((n) => `<div class="why">${esc(n)}</div>`).join("")}
        <div class="build-line" style="margin-top:10px"><button class="btn sm" data-act="copy" data-v="${esc(r.output)}">${t("Copier le chemin")}</button></div></div>` : ""}
    </div>`;
  }
  act("toggle-file", async (el) => {
    const f = el.dataset.file, want = el.checked, base = S.a.plan.keep.includes(f);
    if (want === base) delete S.overrides[f]; else S.overrides[f] = want ? "include" : "exclude";
    S.buildResult = null;
    try { const r = await api("/api/plan", { analysis: S.a.id, ...picks() }); S.plan = r.plan; S.bytes = r.bytes; } catch (e) { toast(e.message); }
    refresh();
  });
  act("reset-plan", async () => {
    S.overrides = {}; S.buildResult = null;
    try { const r = await api("/api/plan", { analysis: S.a.id }); S.plan = r.plan; S.bytes = r.bytes; } catch (e) { toast(e.message); }
    refresh();
  });
  act("build", async () => {
    S.busyBuild = true; S.buildError = ""; S.buildResult = null; refresh();
    try { S.buildResult = await api("/api/build", { analysis: S.a.id, output: S.outPath || S.a.suggested.server, zip: !!S.zip, ...picks() }); S.outPath = undefined; }
    catch (e) { S.buildError = e.message; }
    S.busyBuild = false; refresh();
    const box = $(".build-card .success, .build-card .err-box"); if (box) box.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  act("kit", async () => {
    const k = S.kit;
    S.busyKit = true; S.kitError = ""; S.kitResult = null; refresh();
    try {
      S.kitResult = await api("/api/serverkit", { analysis: S.a.id, output: k.out, ram_gb: Number(k.ram) || undefined, port: Number(k.port), max_players: Number(k.players),
        motd: k.motd, view_distance: Number(k.vd), simulation_distance: Number(k.sd), eula: !!k.eula, with_mods: !!k.withMods, ...picks() });
    } catch (e) { S.kitError = e.message; }
    S.busyKit = false; refresh();
    const box = $("#kit .success, #kit .err-box"); if (box) box.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  act("copy", (el) => copy(el.dataset.v));

  /* ---- Ma base ---------------------------------------------------------------------------------------------------- */
  views.base = {
    title: () => t("Ma base de connaissances"),
    enter: loadKb,
    render() {
      const kb = S.kb, f = S.learnForm, isC = f.kind === "conflict";
      const ids = S.a ? [...new Set(S.a.mods.map((m) => m.modid).filter(Boolean))].sort() : [];
      const kindLabel = (r) => (r.kind === "conflict" ? t("Conflit") : r.kind === "ignore" ? t("Alerte ignorée") : r.side === "client" ? t("Client uniquement") : t("À garder sur le serveur"));
      const stats = kb ? `<div class="stats">
        <div class="stat"><b>${kb.stats.community_sides}</b><span>${t("mods connus (communauté)")}</span></div>
        <div class="stat"><b>${kb.stats.community_conflicts}</b><span>${t("conflits connus (communauté)")}</span></div>
        <div class="stat"><b>${kb.learned.length}</b><span>${t("entrées à toi")}</span></div>
        <div class="stat"><b>${kb.cache.files}</b><span>${t("mods reconnus en cache")}</span></div></div>
        ${kb.stats.errors.length ? `<div class="warn-box"><b>${t("Fichiers ignorés dans la base :")}</b><ul>${kb.stats.errors.slice(0, 5).map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}`
        : (S.kbErr ? `<div class="err-box">${esc(S.kbErr)}</div>` : `<div class="hint">${t("Chargement…")}</div>`);
      const shareable = kb ? kb.learned.filter((r) => r.kind === "conflict" || r.kind === "side").length : 0;
      const learned = kb && kb.learned.length ? `<div class="group-title"><h3>${t("Ta base")}</h3><span>${t("stockée sur ton ordinateur")}</span></div>
        <div class="rows">${kb.learned.map((r) => `<div class="row"><div class="grow"><div class="nm">${esc(r.kind === "ignore" ? r.a.replace(/^.*?:/, "") || r.a : r.a)}${r.b ? ` ↔ ${esc(r.b)}` : ""}</div>
          <div class="why">${kindLabel(r)}${r.kind === "conflict" ? ` · ${SEV()[r.severity] || ""}` : ""}${r.note ? ` · ${esc(r.note)}` : ""}</div></div>
          <span class="chip">${r.source === "import" ? t("importé") : t("à toi")}</span>
          <button class="btn sm" data-act="ldel" data-id="${r.id}">${t("Supprimer")}</button></div>`).join("")}</div>` : "";
      return `
      <section>
        <div class="logs-head"><div><h2>${t("Ma base de connaissances")}</h2>
          <p>${t("ModMaestro apprend de toi. Un conflit que tu as découvert, ou un mod qui n'a rien à faire sur un serveur : enregistre-le, et il sera repéré dans tous tes prochains audits.")}</p></div>
          <img src="/assets/illustrations/conflict.svg" alt=""></div>
        ${stats}
        <div class="build-card" id="learn">
          <h3 class="card-title">${t("Apprendre quelque chose de nouveau")}</h3>
          ${f.hint ? `<div class="hint" style="margin:0">${esc(f.hint)}</div>` : ""}
          <label class="field">${t("Que veux-tu enregistrer ?")}
            <select class="input" data-model="learnForm.kind" data-rerender>
              <option value="conflict" ${f.kind === "conflict" ? "selected" : ""}>${t("Deux mods qui ne vont pas ensemble")}</option>
              <option value="client" ${f.kind === "client" ? "selected" : ""}>${t("Un mod qui ne doit pas aller sur le serveur")}</option>
              <option value="both" ${f.kind === "both" ? "selected" : ""}>${t("Un mod à garder sur le serveur (fausse alerte)")}</option></select></label>
          <div class="two">
            <label class="field">${isC ? t("Premier mod") : t("Mod")}<input class="input mono" data-model="learnForm.a" list="ids" value="${esc(f.a)}" placeholder="${t("identifiant, ex. sodium")}" spellcheck="false" autocomplete="off"></label>
            ${isC ? `<label class="field">${t("Second mod")}<input class="input mono" data-model="learnForm.b" list="ids" value="${esc(f.b)}" placeholder="${t("identifiant")}" spellcheck="false" autocomplete="off"></label>` : ""}
          </div>
          <datalist id="ids">${ids.map((i) => `<option value="${esc(i)}">`).join("")}</datalist>
          ${f.candidates.length ? `<div><div class="hint" style="margin:0 0 8px">${t("Mods du pack qui pourraient être en cause :")}</div><div class="chips">${f.candidates.slice(0, 40).map((c) => `<button class="chip" data-act="cand" data-v="${esc(c)}">${esc(c)}</button>`).join("")}</div></div>` : ""}
          ${isC ? `<label class="field">${t("Gravité")}<select class="input" data-model="learnForm.severity">${[["error", t("Erreur — le jeu plante ou le mod ne marche pas")], ["warning", t("Avertissement — problèmes probables")], ["info", t("Info — simple redondance")]].map(([k, l]) => `<option value="${k}" ${f.severity === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>` : ""}
          <label class="field">${t("Note (facultative)")}<input class="input" maxlength="500" data-model="learnForm.note" value="${esc(f.note)}" placeholder="${t("Ce qui s'est passé, pour t'en souvenir")}"></label>
          ${S.learnErr ? `<div class="err-box" style="margin:0">${esc(S.learnErr)}</div>` : ""}
          <div class="build-line"><button class="btn primary" data-act="lsave">${t("Enregistrer")}</button>
            ${S.learnOk && S.a ? `<button class="btn" data-act="reanalyze">${t("Relancer l'analyse pour l'appliquer")}</button>` : ""}
            ${S.learnOk && !S.a ? `<span class="hint" style="margin:0">${t("Enregistré : il sera pris en compte à ta prochaine analyse.")}</span>` : ""}</div>
        </div>
        ${learned}
        <div class="build-card">
          <h3 class="card-title">${t("Proposer à la communauté")}</h3>
          <p class="muted">${t("Tu as découvert un conflit ou un mod client ? Propose-le : ModMaestro prépare un message prêt à publier sur le dépôt du projet. Rien n'est envoyé sans que tu le publies toi-même.")}</p>
          <div class="build-line"><button class="btn primary" data-act="contribute" ${shareable ? "" : "disabled"}>${t("Proposer à la communauté")}</button>
            ${shareable ? `<span class="hint" style="margin:0">${tn(shareable, "{n} entrée prête", "{n} entrées prêtes")}</span>` : `<span class="hint" style="margin:0">${t("Enregistre d'abord un conflit ou un mod client.")}</span>`}</div>
        </div>
        <div class="build-card">
          <h3 class="card-title">${t("Partager ou récupérer une base")}</h3>
          <p class="muted">${t("Exporte ta base dans un fichier, ou importe celle de quelqu'un d'autre. Rien n'est jamais envoyé automatiquement.")}</p>
          <div class="build-line"><button class="btn" data-act="lexport">${t("Exporter ma base")}</button>
            <label class="btn" for="limport">${t("Importer un fichier…")}</label><input type="file" id="limport" accept=".json,application/json" hidden></div>
          ${S.importMsg ? `<div class="hint" style="margin:0">${esc(S.importMsg)}</div>` : ""}
        </div>
        ${kb ? `<div class="build-card"><h3 class="card-title">${t("Cache Modrinth")}</h3>
          <p class="muted">${tn(kb.cache.files, "{n} mod reconnu", "{n} mods reconnus")}, ${tn(kb.cache.projects, "{n} fiche", "{n} fiches")}, ${size(kb.cache.size)} · ${t("dernière vérification : {when}", { when: fmtDate(kb.cache.last_check) })}<br><code>${esc(kb.cache.path)}</code></p>
          ${kb.cache.degraded ? `<div class="warn-box" style="margin:0">${esc(kb.cache.degraded)}</div>` : ""}
          <div class="build-line"><button class="btn" data-act="cclear">${t("Vider le cache")}</button><span class="hint" style="margin:0">${t("Ta base personnelle n'est pas touchée.")}</span></div></div>` : ""}
      </section>`;
    },
    after() { const i = $("#limport"); if (i) i.addEventListener("change", (e) => e.target.files[0] && importBase(e.target.files[0])); },
  };
  async function loadKb() { try { S.kb = await api("/api/kb"); S.kbErr = ""; } catch (e) { S.kbErr = e.message; } if (S.view === "base") refresh(); }
  act("lsave", async () => {
    const f = S.learnForm; S.learnErr = ""; S.learnOk = false;
    try {
      await api("/api/learn", f.kind === "conflict" ? { kind: "conflict", a: f.a.trim(), b: f.b.trim(), severity: f.severity, note: f.note } : { kind: "side", a: f.a.trim(), side: f.kind, note: f.note });
      S.learnForm = newLearn(); S.learnOk = true; toast(t("Enregistré dans ta base")); await loadKb();
    } catch (e) { S.learnErr = e.message; refresh(); }
  });
  act("reanalyze", () => analyze(S.a.source));
  act("cand", (el) => { const f = S.learnForm, c = el.dataset.v; if (f.kind === "conflict" && f.a && !f.b && f.a !== c) f.b = c; else f.a = c; refresh(); });
  act("ldel", async (el) => { try { await api("/api/learn/delete", { id: Number(el.dataset.id) }); toast(t("Supprimé")); } catch (e) { toast(e.message); } loadKb(); });
  act("lexport", async () => { try { const { bundle } = await api("/api/learn/export", {}); download(JSON.stringify(bundle, null, 2), "modmaestro-ma-base.json", "application/json"); toast(t("Base exportée")); } catch (e) { toast(e.message); } });
  async function importBase(file) {
    try {
      const r = await api("/api/learn/import", { bundle: JSON.parse(await file.text()) });
      S.importMsg = tn(r.added, "{n} entrée importée", "{n} entrées importées") + (r.errors.length ? ` · ${tn(r.errors.length, "{n} ignorée", "{n} ignorées")} : ${r.errors.slice(0, 2).join(" ")}` : "");
      S.learnOk = r.added > 0;
    } catch (e) { S.importMsg = e instanceof SyntaxError ? t("Ce fichier n'est pas du JSON valide.") : e.message; }
    loadKb();
  }
  act("cclear", async () => {
    if (!confirm(t("Vider le cache Modrinth ? Il sera reconstruit à la prochaine analyse en ligne. Ta base personnelle est conservée."))) return;
    try { await api("/api/cache/clear", {}); toast(t("Cache vidé")); } catch (e) { toast(e.message); }
    loadKb();
  });
  act("contribute", async () => {
    try {
      const r = await api("/api/contribute", { analysis: S.a && S.a.id });
      const link = r.url ? `<a class="btn primary" href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">${t("Ouvrir sur GitHub")} ↗</a>`
        : `<span class="hint" style="margin:0">${t("Le dépôt du projet n'est pas configuré dans cette version : copie le message et publie-le où tu veux.")}</span>`;
      dialog(t("Proposer à la communauté"), `<p class="muted">${r.body_in_url || !r.url ? t("Voici le message préparé. Relis-le avant de le publier : il ne contient que tes entrées, jamais tes chemins ni tes fichiers.") : t("Le message est long : le lien ouvre une page vide, colle-y le message copié.")}</p>
        <textarea class="input mono" readonly rows="12" id="contrib-text">${esc(r.body)}</textarea>`,
        `<button class="btn" data-act="copy-contrib">${t("Copier le message")}</button>${link}`);
    } catch (e) { toast(e.message); }
  });
  act("copy-contrib", () => copy($("#contrib-text").value));
  act("close-dialog", closeDialog);

  /* ---- Journal de crash (lecture du log) — la recherche par essais est dans views-new.js ------------------------------ */
  X.logsSection = function logsSection() {
    const L = S.logs, found = (S.a && S.a.logs) || [];
    const results = L.findings === null ? "" : L.findings.length ? `<div class="issues" style="margin-top:22px">${L.findings.map((f, idx) => `
      <details class="issue ${f.severity}" open><summary><span class="sev" title="${SEV()[f.severity]}">${ICON[f.severity]}</span>
        <div class="issue-main"><div class="issue-title">${esc(f.title)}</div><div class="issue-msg">${esc(f.message)}</div></div>${ICON.caret}</summary>
        <div class="issue-body">${f.fix ? `<div class="fix"><b>${t("À faire :")}</b> ${esc(f.fix)}</div>` : ""}
        ${(L.suggestions || []).some((x) => x.finding === idx) ? `<div><button class="btn sm" data-act="sugg" data-i="${idx}">${t("Enregistrer dans ma base…")}</button></div>` : ""}</div></details>`).join("")}</div>`
      : `<div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${t("Aucun problème reconnu")}</h3><p>${t("Ce journal ne contient aucune des erreurs courantes que ModMaestro sait lire. Colle plutôt le crash-report complet, ou essaie la recherche par essais.")}</p></div>`;
    return `<div class="logs-head"><div><h2>${t("Pourquoi ça plante ?")}</h2>
      <p>${t("Colle ici le contenu de latest.log ou d'un crash-report. ModMaestro y cherche les causes les plus courantes : dépendance manquante, doublon, mod client sur serveur, mauvaise version de Java, mémoire…")}</p></div><img src="/assets/illustrations/logs.svg" alt=""></div>
      <div class="stack">
        ${found.length ? `<div><div class="hint" style="margin:0 0 8px">${t("Journaux trouvés près de ton modpack :")}</div><div class="chips">${found.map((f) => `<button class="chip" data-act="log" data-p="${esc(f.path)}">${esc(f.name)}</button>`).join("")}</div></div>` : ""}
        <input class="input mono" data-model="logs.path" placeholder="${t("Chemin d'un fichier .log / .txt / .log.gz (facultatif)")}" value="${esc(L.path)}" spellcheck="false">
        <textarea class="input mono" data-model="logs.text" placeholder="${t("…ou colle le texte du journal ici")}" spellcheck="false">${esc(L.text)}</textarea>
        ${L.error ? `<div class="err-box" style="margin:0">${esc(L.error)}</div>` : ""}
        <div><button class="btn primary" data-act="scanlog">${t("Analyser le journal")}</button></div>
      </div>${results}`;
  };
  async function scanLog() {
    const L = S.logs; L.error = "";
    if (!L.text.trim() && !L.path) { L.error = t("Colle un journal ou indique son chemin."); return refresh(); }
    try { const r = await api("/api/logscan", { ...(L.text.trim() ? { text: L.text } : { path: L.path }), analysis: S.a && S.a.id }); L.findings = r.findings; L.suggestions = r.suggestions || []; }
    catch (e) { L.error = e.message; L.findings = null; }
    refresh();
  }
  act("scanlog", scanLog);
  act("log", (el) => { S.logs.path = el.dataset.p; S.logs.text = ""; scanLog(); });
  act("sugg", (el) => {
    const s = (S.logs.suggestions || []).find((x) => x.finding === Number(el.dataset.i));
    if (!s) return;
    S.learnForm = s.kind === "side" ? { kind: "client", a: "", b: "", severity: "error", note: s.note, candidates: s.candidates || [], hint: s.hint || "" }
      : { kind: "conflict", a: s.a, b: "", severity: "error", note: s.note, candidates: [], hint: s.hint || "" };
    S.learnOk = false; S.learnErr = ""; go("base");
  });
})();
