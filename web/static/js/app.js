/* ModMaestro — interface locale (JS vanilla, sans dépendance) */
(() => {
  "use strict";
  const MM = window.MM || {};
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
  const size = (n) => {
    const u = ["o", "Ko", "Mo", "Go"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${i === 0 ? n : n.toFixed(1)} ${u[i]}`;
  };

  const ICON = {
    error: '<svg viewBox="0 0 24 24"><path d="M12 8v5M12 16.5v.01"/></svg>',
    warning: '<svg viewBox="0 0 24 24"><path d="M12 7v6M12 17v.01"/></svg>',
    info: '<svg viewBox="0 0 24 24"><path d="M12 11v6M12 7.5v.01"/></svg>',
    caret: '<svg class="caret" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    zip: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M11 6h2M11 9h2M11 12h2"/></svg>',
  };
  const SEV = { error: "Erreur", warning: "Avertissement", info: "Info" };
  const SIDE = { client: "Client", server: "Serveur", both: "Les deux", unsure: "À vérifier" };
  const CATS = [
    ["all", "Tout"], ["duplicates", "Doublons"], ["dependencies", "Dépendances"],
    ["versions", "Versions"], ["compat", "Compatibilité"], ["files", "Fichiers"],
  ];
  
  const S = {
    view: "home", a: null, filter: "all", q: "", side: "all",
    overrides: {}, plan: null, bytes: 0, buildResult: null, buildError: "",
    busy: null, homeError: "", logs: { text: "", path: "", findings: null, error: "" },
  };

  /* ---- API ---------------------------------------------------------------- */
  async function api(path, body) {
    const opt = { headers: { "X-MM-Token": MM.token || "" } };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    let r;
    try { r = await fetch(path, opt); } catch (e) { throw new Error("Impossible de joindre ModMaestro : le programme est-il toujours lancé ?"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Erreur ${r.status}`);
    return data;
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("Copié dans le presse-papiers"); }
    catch { toast("Copie impossible : sélectionne le texte à la main"); }
  }

  /* ---- Analyse -------------------------------------------------------------- */
  async function analyze(path, demo = false) {
    S.homeError = "";
    S.busy = { done: 0, total: 0 };
    go("home");
    try {
      const { job } = await api(demo ? "/api/demo" : "/api/analyze", demo ? {} : { path });
      for (;;) {
        const j = await api(`/api/job/${job}`);
        S.busy = { done: j.done, total: j.total };
        updateProgress();
        if (j.state === "done") { loadResult(j.result); return; }
        if (j.state === "error") throw new Error(j.error);
        await new Promise((r) => setTimeout(r, 180));
      }
    } catch (e) {
      S.busy = null; S.homeError = e.message; render();
    }
  }

  function loadResult(res) {
    S.a = res; S.busy = null; S.overrides = {}; S.plan = res.plan;
    S.bytes = res.plan.keep.reduce((n, f) => n + (sizeOf(f) || 0), 0);
    S.buildResult = null; S.buildError = ""; S.filter = "all"; S.q = ""; S.side = "all";
    S.logs = { text: "", path: "", findings: null, error: "" };
    updateNav();
    go("audit");
  }
  const sizeOf = (file) => { const m = S.a.mods.find((x) => x.file === file); return m ? m.size : 0; };

  function updateProgress() {
    const bar = $("#pbar"), lab = $("#plabel");
    if (!bar) return;
    const { done, total } = S.busy || {};
    if (total) { bar.style.width = `${Math.round((done / total) * 100)}%`; bar.parentElement.classList.remove("indeterminate"); }
    if (lab) lab.textContent = total ? `Lecture des fichiers… ${done} / ${total}` : "Recherche des fichiers .jar…";
  }

  /* ---- Navigation --------------------------------------------------------------- */
  function updateNav() {
    const has = !!S.a;
    $$(".nav-item").forEach((b) => {
      const v = b.dataset.view;
      b.disabled = (v === "audit" || v === "mods" || v === "server") && !has;
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
  }

  const titles = { audit: "Audit du modpack", mods: "Liste des mods", server: "Dossier serveur", logs: "Journal de crash" };

  function render() {
    const v = $("#view");
    $("#crumb-title").textContent = titles[S.view] || "";
    if (S.a) $("#crumb-path").textContent = S.a.mods_dir;
    const fn = { home: viewHome, audit: viewAudit, mods: viewMods, server: viewServer, logs: viewLogs }[S.view];
    v.innerHTML = fn();
    bind();
  }

  /* ---- Vue : accueil ----------------------------------------------------------------- */
  function viewHome() {
    const busy = S.busy;
    return `
    <section class="home">
      <div class="hero">
        <div>
          <h1>Le chef d'orchestre de ton <em>modpack</em>.</h1>
          <p class="lead">Dépose le dossier <code>mods</code> : ModMaestro lit chaque mod, repère les doublons, les dépendances manquantes et les incompatibilités, puis prépare un dossier serveur propre.</p>
          <div class="drop">
            <input class="input" id="path" placeholder="Colle le chemin de ton dossier mods…" spellcheck="false" value="${esc(MM.initial || "")}" ${busy ? "disabled" : ""}>
            <button class="btn" id="browse" ${busy ? "disabled" : ""}>Parcourir…</button>
            <button class="btn primary" id="go" ${busy ? "disabled" : ""}>Analyser</button>
          </div>
          ${busy ? `<div class="progress"><div class="progress-bar indeterminate"><i id="pbar"></i></div><div class="progress-label" id="plabel">Recherche des fichiers .jar…</div></div>` : ""}
          ${S.homeError ? `<div class="err-box">${esc(S.homeError)}</div>` : ""}
          <div class="home-actions">
            <button class="link-btn" id="demo" ${busy ? "disabled" : ""}>Essayer avec un modpack de démonstration →</button>
          </div>
          <p class="hint">Tout reste sur ton ordinateur : rien n'est envoyé sur Internet, et ton dossier d'origine n'est jamais modifié.</p>
        </div>
        <img class="hero-art" src="/assets/hero.svg" alt="">
      </div>
      <div class="features">
        <div class="feature"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg><h3>Doublons</h3><p>Deux versions du même mod ? ModMaestro garde la plus récente.</p></div>
        <div class="feature"><svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/></svg><h3>Dépendances</h3><p>Les mods manquants et les versions qui ne s'entendent pas.</p></div>
        <div class="feature"><svg viewBox="0 0 24 24"><path d="M13 3L5 14h6l-1 7 8-11h-6z"/></svg><h3>Incompatibilités</h3><p>Conflits déclarés par les auteurs et pièges connus (Sodium + OptiFine…).</p></div>
        <div class="feature"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/></svg><h3>Dossier serveur</h3><p>Retire les mods clients et copie le reste dans un dossier propre.</p></div>
      </div>
    </section>`;
  }

  /* ---- Vue : audit ------------------------------------------------------------------------- */
  function viewAudit() {
    const a = S.a, c = a.counts;
    const circ = 2 * Math.PI * 54;
    const verdictText = { ok: "Ton modpack est en pleine forme", warn: "Quelques points à surveiller", bad: "Ce modpack ne démarrera probablement pas" }[a.verdict];
    const cats = { all: a.issues.length };
    a.issues.forEach((i) => (cats[i.category] = (cats[i.category] || 0) + 1));
    const list = a.issues.filter((i) => S.filter === "all" || i.category === S.filter);

    const issues = list.map((i) => `
      <details class="issue ${i.severity}" ${list.length <= 3 ? "open" : ""}>
        <summary>
          <span class="sev" title="${SEV[i.severity]}">${ICON[i.severity]}</span>
          <div class="issue-main"><div class="issue-title">${esc(i.title)}</div><div class="issue-msg">${esc(i.message)}</div></div>
          ${ICON.caret}
        </summary>
        <div class="issue-body">
          ${i.fix ? `<div class="fix"><b>À faire :</b> ${esc(i.fix)}</div>` : ""}
          ${i.files.length ? `<div class="files">${i.files.map((f) => `<span class="chip mono">${esc(f)}</span>`).join("")}</div>` : ""}
          ${i.links.length ? `<div class="links">${i.links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">Chercher sur ${esc(l.label)} ↗</a>`).join("")}</div>` : ""}
        </div>
      </details>`).join("");

    const art = "ok";
    const empty = `<div class="empty"><img src="/assets/illustrations/${art}.svg" alt="">
      <h3>${S.filter === "all" ? "Rien à signaler" : "Rien dans cette catégorie"}</h3>
      <p>${S.filter === "all" ? "Aucun doublon, aucune dépendance manquante, aucune incompatibilité détectée." : "Cette catégorie est propre."}</p></div>`;

    return `
    <section>
      <div class="summary">
        <div class="ring ${a.verdict}"><svg viewBox="0 0 132 132"><circle class="track" cx="66" cy="66" r="54" fill="none"/><circle class="val" cx="66" cy="66" r="54" fill="none" stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="${circ * (1 - a.score / 100)}"/></svg>
          <div class="ring-num"><div><b>${a.score}</b><br><span>/ 100</span></div></div></div>
        <div>
          <h2>${verdictText}</h2>
          <div class="meta">
            <span class="chip accent">${esc(a.loader_label)}</span>
            ${a.mc_version ? `<span class="chip">Minecraft ${esc(a.mc_version)}</span>` : ""}
            <span class="chip">${plural(c.mods, "mod", "mods")} · ${plural(c.jars, "fichier", "fichiers")}</span>
            ${c.bundled ? `<span class="chip">${c.bundled} intégré${c.bundled > 1 ? "s" : ""} (jar-in-jar)</span>` : ""}
            <span class="chip">${size(c.size)}</span>
          </div>
          ${a.notes.length ? `<div class="notes">${a.notes.map(esc).join(" · ")}</div>` : ""}
        </div>
      </div>

      <div class="stats">
        <div class="stat err"><b>${c.errors}</b><span>${c.errors > 1 ? "erreurs" : "erreur"}</span></div>
        <div class="stat warn"><b>${c.warnings}</b><span>${c.warnings > 1 ? "avertissements" : "avertissement"}</span></div>
        <div class="stat"><b>${c.server_remove}</b><span>à retirer du serveur</span></div>
        <div class="stat"><b>${c.server_unsure}</b><span>à vérifier côté serveur</span></div>
      </div>

      <div class="tabs" role="group" aria-label="Filtrer">
        ${CATS.filter(([k]) => k === "all" || cats[k]).map(([k, label]) => `<button class="tab" data-filter="${k}" aria-pressed="${S.filter === k}">${label} <small>${cats[k] || 0}</small></button>`).join("")}
      </div>
      <div class="issues">${issues || empty}</div>
    </section>`;
  }

  /* ---- Vue : mods ---------------------------------------------------------------------------------- */
  function viewMods() {
    return `
    <section>
      <div class="toolbar">
        <input class="input" id="q" type="search" placeholder="Rechercher un mod…" value="${esc(S.q)}">
        <select class="input" id="side" aria-label="Filtrer par côté">
          ${[["all", "Tous les côtés"], ["client", "Client"], ["server", "Serveur"], ["both", "Les deux"], ["unsure", "À vérifier"]].map(([k, l]) => `<option value="${k}" ${S.side === k ? "selected" : ""}>${l}</option>`).join("")}
        </select>
      </div>
      <div id="modtable"></div>
    </section>`;
  }

  function fillMods() {
    const host = $("#modtable");
    if (!host) return;
    const q = S.q.trim().toLowerCase();
    const rows = S.a.mods
      .filter((m) => (S.side === "all" || m.side === S.side))
      .filter((m) => !q || `${m.name} ${m.modid || ""} ${m.file}`.toLowerCase().includes(q))
      .sort((x, y) => x.name.localeCompare(y.name, "fr", { sensitivity: "base" }));
    const shown = rows.slice(0, 1500);
    host.innerHTML = rows.length ? `
      <div class="table-wrap"><table>
        <thead><tr><th>Mod</th><th>Version</th><th>Loader</th><th>Côté</th><th>Fichier</th></tr></thead>
        <tbody>${shown.map((m) => `<tr>
          <td><div class="nm">${esc(m.name)}</div>${m.modid ? `<div class="id">${esc(m.modid)}</div>` : ""}</td>
          <td>${esc(m.version || "—")}</td>
          <td>${m.loader ? esc(m.loader) : '<span class="pill bad">illisible</span>'}</td>
          <td><span class="pill ${m.side}" title="${esc(m.side_reason || "")}">${SIDE[m.side]}</span></td>
          <td class="file">${esc(m.file)}</td></tr>`).join("")}</tbody>
      </table></div>
      <div class="count-note">${plural(rows.length, "mod affiché", "mods affichés")}${rows.length > shown.length ? ` (${shown.length} premiers)` : ""}</div>`
      : `<div class="empty"><img src="/assets/illustrations/welcome.svg" alt=""><h3>Aucun résultat</h3><p>Essaie un autre mot-clé ou un autre filtre.</p></div>`;
  }

  /* ---- Vue : serveur ----------------------------------------------------------------------------------- */
  function viewServer() {
    const a = S.a, p = S.plan;
    const allFiles = [...p.keep, ...p.remove.map((r) => r.file)].sort((x, y) => x.toLowerCase().localeCompare(y.toLowerCase()));
    const keepSet = new Set(p.keep), reasons = {};
    p.remove.forEach((r) => (reasons[r.file] = r.reason));
    p.restored.forEach((r) => (reasons[r.file] = r.reason));
    p.unsure.forEach((r) => (reasons[r.file] = r.reason));
    const unsure = new Set(p.unsure.map((u) => u.file));
    const row = (f) => `
      <div class="row"><div class="grow"><div class="nm">${esc(f)}</div>${reasons[f] ? `<div class="why">${unsure.has(f) ? "⚠ " : ""}${esc(reasons[f])}</div>` : ""}</div>
        ${S.overrides[f] ? '<span class="chip">modifié</span>' : ""}
        <label class="switch" title="${keepSet.has(f) ? "Sera copié sur le serveur" : "Ne sera pas copié"}"><input type="checkbox" data-file="${esc(f)}" ${keepSet.has(f) ? "checked" : ""} aria-label="Garder ${esc(f)} sur le serveur"></label>
      </div>`;
    const removed = allFiles.filter((f) => !keepSet.has(f)), kept = allFiles.filter((f) => keepSet.has(f));
    const toVerify = kept.filter((f) => unsure.has(f)), rest = kept.filter((f) => !unsure.has(f));
    const dirty = Object.keys(S.overrides).length;
    const warn = p.warnings.length ? `<div class="warn-box"><b>Attention :</b> ces mods gardés ont besoin d'un mod que tu as retiré.<ul>${p.warnings.map((w) => `<li><b>${esc(w.name)}</b> a besoin de <code>${esc(w.missing)}</code> (${esc(w.provider)})</li>`).join("")}</ul></div>` : "";
    const res = S.buildResult ? `<div class="success"><b>Dossier serveur créé !</b> ${plural(S.buildResult.copied, "mod copié", "mods copiés")} (${size(S.buildResult.bytes)}).
        <code>${esc(S.buildResult.output)}</code>${S.buildResult.zip ? `<code>${esc(S.buildResult.zip)}</code>` : ""}
        <div class="build-line" style="margin-top:10px"><button class="btn sm" data-copy="${esc(S.buildResult.output)}">Copier le chemin</button></div></div>` : "";

    return `
    <section>
      <div class="server-head">
        <div><h2>Prépare ton serveur</h2>
          <p>Les mods qui ne servent qu'au joueur (rendu, minimap, interface) n'ont rien à faire sur un serveur dédié. Voici ce qui sera copié ; tu peux corriger chaque choix.</p>
          <div class="kpis"><span class="chip accent">${p.keep.length} gardés</span><span class="chip">${p.remove.length} retirés</span><span class="chip">${size(S.bytes)}</span>${dirty ? `<button class="btn sm" id="reset">Revenir à la proposition</button>` : ""}</div></div>
        <img src="/assets/illustrations/server.svg" alt="">
      </div>
      ${warn}
      <div class="build-card">
        <label class="field">Dossier de destination
          <input class="input mono" id="out" value="${esc(S.outPath ?? a.suggested_output)}" spellcheck="false"></label>
        <div class="build-line">
          <label class="check"><input type="checkbox" id="zip" ${S.zip ? "checked" : ""}> Créer aussi une archive .zip</label>
          <span class="grow"></span>
          <button class="btn primary lg" id="build" ${S.busyBuild ? "disabled" : ""}>${S.busyBuild ? "Copie en cours…" : "Créer le dossier serveur"}</button>
        </div>
        ${S.buildError ? `<div class="err-box" style="margin:0">${esc(S.buildError)}</div>` : ""}${res}
      </div>
      ${removed.length ? `<div class="group-title"><h3>Retirés du serveur</h3><span>${removed.length}</span></div><div class="rows">${removed.map(row).join("")}</div>` : ""}
      ${toVerify.length ? `<div class="group-title"><h3>À vérifier</h3><span>gardés par défaut — retire-les si tu es sûr qu'ils sont inutiles côté serveur</span></div><div class="rows">${toVerify.map(row).join("")}</div>` : ""}
      <div class="group-title"><h3>Gardés</h3><span>${rest.length}</span></div><div class="rows">${rest.map(row).join("") || '<div class="row"><div class="grow why">Aucun.</div></div>'}</div>
    </section>`;
  }

  async function refreshPlan() {
    const exclude = [], include = [];
    for (const [f, v] of Object.entries(S.overrides)) (v === "include" ? include : exclude).push(f);
    const r = await api("/api/plan", { analysis: S.a.id, exclude, include });
    S.plan = r.plan; S.bytes = r.bytes;
  }

  function keepSnapshot() { const e = $("#out"); if (e) S.outPath = e.value; const z = $("#zip"); if (z) S.zip = z.checked; }

  async function toggleFile(file, wantKeep) {
    keepSnapshot();
    const baseKeep = S.a.plan.keep.includes(file);
    if (wantKeep === baseKeep) delete S.overrides[file]; else S.overrides[file] = wantKeep ? "include" : "exclude";
    S.buildResult = null;
    const sc = $("#view").scrollTop;
    try { await refreshPlan(); } catch (e) { toast(e.message); }
    render(); $("#view").scrollTop = sc;
  }

  async function build() {
    keepSnapshot();
    const exclude = [], include = [];
    for (const [f, v] of Object.entries(S.overrides)) (v === "include" ? include : exclude).push(f);
    S.busyBuild = true; S.buildError = ""; S.buildResult = null; render();
    try {
      S.buildResult = await api("/api/build", { analysis: S.a.id, output: S.outPath || S.a.suggested_output, zip: !!S.zip, exclude, include });
      S.outPath = undefined;
    } catch (e) { S.buildError = e.message; }
    S.busyBuild = false; render();
    const box = $(".success, .build-card .err-box");
    if (box) box.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  /* ---- Vue : journal --------------------------------------------------------------------------------------- */
  function viewLogs() {
    const L = S.logs, found = (S.a && S.a.logs) || [];
    const fmt = (s) => ({ error: "Erreur", warning: "Avertissement", info: "Info" }[s]);
    const results = L.findings === null ? "" : L.findings.length
      ? `<div class="issues" style="margin-top:22px">${L.findings.map((f) => `
        <details class="issue ${f.severity}" open><summary><span class="sev" title="${fmt(f.severity)}">${ICON[f.severity]}</span>
          <div class="issue-main"><div class="issue-title">${esc(f.title)}</div><div class="issue-msg">${esc(f.message)}</div></div>${ICON.caret}</summary>
          ${f.fix ? `<div class="issue-body"><div class="fix"><b>À faire :</b> ${esc(f.fix)}</div></div>` : ""}</details>`).join("")}</div>`
      : `<div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>Aucun problème reconnu</h3><p>Ce journal ne contient aucune des erreurs courantes que ModMaestro sait lire. Colle plutôt le crash-report complet, ou regarde l'onglet Audit.</p></div>`;
    return `
    <section>
      <div class="logs-head"><div><h2>Pourquoi ça plante ?</h2>
        <p>Colle ici le contenu de <code>latest.log</code> ou d'un <code>crash-report</code>. ModMaestro y cherche les causes les plus courantes : dépendance manquante, doublon, mod client sur serveur, mauvaise version de Java, mémoire…</p></div>
        <img src="/assets/illustrations/logs.svg" alt=""></div>
      <div class="stack">
        ${found.length ? `<div><div class="hint" style="margin:0 0 8px">Journaux trouvés près de ton modpack :</div><div class="chips">${found.map((f) => `<button class="chip" data-log="${esc(f.path)}">${esc(f.name)}</button>`).join("")}</div></div>` : ""}
        <input class="input mono" id="logpath" placeholder="Chemin d'un fichier .log / .txt / .log.gz (facultatif)" value="${esc(L.path)}" spellcheck="false">
        <textarea class="input mono" id="logtext" placeholder="…ou colle le texte du journal ici" spellcheck="false">${esc(L.text)}</textarea>
        ${L.error ? `<div class="err-box" style="margin:0">${esc(L.error)}</div>` : ""}
        <div><button class="btn primary" id="scanlog">Analyser le journal</button></div>
      </div>${results}
    </section>`;
  }

  async function scanLog() {
    S.logs.text = $("#logtext").value; S.logs.path = $("#logpath").value.trim(); S.logs.error = "";
    if (!S.logs.text.trim() && !S.logs.path) { S.logs.error = "Colle un journal ou indique son chemin."; return render(); }
    try {
      const r = await api("/api/logscan", S.logs.text.trim() ? { text: S.logs.text } : { path: S.logs.path });
      S.logs.findings = r.findings;
    } catch (e) { S.logs.error = e.message; S.logs.findings = null; }
    render();
  }

  /* ---- Export ---------------------------------------------------------------------------------------------------- */
  async function exportReport() {
    try {
      const { markdown } = await api("/api/report", { analysis: S.a.id });
      const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
      const el = Object.assign(document.createElement("a"), { href: url, download: "rapport-modmaestro.md" });
      document.body.appendChild(el); el.click(); el.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast("Rapport exporté");
    } catch (e) { toast(e.message); }
  }

  /* ---- Sélecteur de dossier ----------------------------------------------------------------------------------------- */
  const B = { path: "", data: null };
  async function openBrowser(start) {
    $("#modal").hidden = false;
    await browseTo(start || ($("#path") && $("#path").value) || "");
    $("#browse-path").focus();
  }
  async function browseTo(path) {
    try {
      const d = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
      B.data = d; B.path = d.path;
      $("#browse-path").value = d.path;
      $("#browse-up").disabled = !d.parent;
      $("#shortcuts").innerHTML = d.shortcuts.map((s) => `<button data-p="${esc(s.path)}">${esc(s.label)}<small>${esc(s.path)}</small></button>`).join("");
      $("#dirlist").innerHTML = d.entries.length ? d.entries.map((e) => `<li><button data-p="${esc(e.path)}" data-kind="${e.kind}">${e.kind === "zip" ? ICON.zip : ICON.folder}<span>${esc(e.name)}</span>${e.jars ? `<span class="chip accent jarcount">${e.jars} jar</span>` : ""}</button></li>`).join("") : '<li class="none">Aucun sous-dossier.</li>';
      const hint = $("#browse-hint");
      hint.innerHTML = d.jars ? `<b>${plural(d.jars, "mod trouvé", "mods trouvés")}</b> dans ce dossier` : d.has_mods_dir ? "Un dossier <code>mods</code> est présent ici" : "Aucun .jar ici — ouvre le dossier <code>mods</code>";
    } catch (e) { toast(e.message); }
  }
  const closeBrowser = () => ($("#modal").hidden = true);

  /* ---- Liaisons --------------------------------------------------------------------------------------------------------------- */
  function bind() {
    const on = (sel, ev, fn) => { const e = $(sel); if (e) e.addEventListener(ev, fn); };
    on("#go", "click", () => { const v = $("#path").value.trim(); if (!v) { S.homeError = "Indique le chemin du dossier mods, ou clique sur « Parcourir »."; return render(); } analyze(v); });
    on("#path", "keydown", (e) => { if (e.key === "Enter") $("#go").click(); });
    on("#browse", "click", () => openBrowser());
    on("#demo", "click", () => analyze("", true));
    $$("[data-filter]").forEach((b) => b.addEventListener("click", () => { S.filter = b.dataset.filter; render(); }));
    on("#q", "input", (e) => { S.q = e.target.value; fillMods(); });
    on("#side", "change", (e) => { S.side = e.target.value; fillMods(); });
    if (S.view === "mods") fillMods();
    $$("input[data-file]").forEach((i) => i.addEventListener("change", () => toggleFile(i.dataset.file, i.checked)));
    on("#reset", "click", async () => { keepSnapshot(); S.overrides = {}; S.buildResult = null; await refreshPlan(); render(); });
    on("#build", "click", build);
    $$("[data-copy]").forEach((b) => b.addEventListener("click", () => copy(b.dataset.copy)));
    on("#scanlog", "click", scanLog);
    $$("[data-log]").forEach((b) => b.addEventListener("click", () => { S.logs.path = b.dataset.log; S.logs.text = ""; $("#logpath").value = b.dataset.log; $("#logtext").value = ""; scanLog(); }));
    if (S.busy) updateProgress();
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#version").textContent = `v${MM.version || ""} · 100 % local`;
    $$(".nav-item").forEach((b) => b.addEventListener("click", () => !b.disabled && go(b.dataset.view)));
    $("#btn-new").addEventListener("click", () => { S.homeError = ""; go("home"); });
    $("#btn-export").addEventListener("click", exportReport);
    $("#theme-toggle").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") ||
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("mm-theme", next); } catch (e) { /* stockage indisponible */ }
    });
    $("#modal-close").addEventListener("click", closeBrowser);
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeBrowser(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeBrowser(); });
    $("#browse-up").addEventListener("click", () => B.data && B.data.parent && browseTo(B.data.parent));
    $("#browse-go").addEventListener("click", () => browseTo($("#browse-path").value));
    $("#browse-path").addEventListener("keydown", (e) => { if (e.key === "Enter") browseTo(e.target.value); });
    $("#shortcuts").addEventListener("click", (e) => { const b = e.target.closest("button[data-p]"); if (b) browseTo(b.dataset.p); });
    $("#dirlist").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-p]");
      if (!b) return;
      if (b.dataset.kind === "zip") { closeBrowser(); $("#path").value = b.dataset.p; $("#go").click(); } else browseTo(b.dataset.p);
    });
    $("#browse-pick").addEventListener("click", () => { closeBrowser(); const p = $("#path"); if (p) p.value = B.path; analyze(B.path); });

    updateNav(); render();
    if (MM.initial) analyze(MM.initial);
  });
})();
