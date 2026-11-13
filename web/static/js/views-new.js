/* ModMaestro — nouvelles vues : comparer, crash, exporter, conseils. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, esc, t, tn, size, S, views, act, api, runJob, toast, copy, download, dialog, refresh, go, ext, ICON } = X;
  const SEV = () => ({ error: t("Erreur"), warning: t("Avertissement"), info: t("Info") });

  /* ---- Comparer ------------------------------------------------------------------------------------------------ */
  Object.assign(S, { cmp: { a: "", b: "", result: null, error: "", busy: false }, crashTab: "log", crash: null, exp: null, tips: null });

  const pathField = (label, model, value) => `<label class="field">${label}
    <span class="pathrow"><input class="input mono" data-model="${model}" value="${esc(value)}" spellcheck="false" placeholder="${t("Chemin du dossier mods")}">
    <button class="btn" data-act="browse-to" data-model="${model}">${t("Parcourir…")}</button></span></label>`;

  const headCard = (h, tag) => `<div class="cmp-head"><span class="chip accent">${tag}</span>
    <div class="cmp-score ${h.score >= 80 ? "ok" : h.score >= 50 ? "warn" : "bad"}"><b data-count="${h.score}">${h.score}</b><small>/100</small></div>
    <div><b>${esc(h.loader_label)}${h.mc_version ? ` · ${esc(h.mc_version)}` : ""}</b>
    <div class="muted">${tn(h.mods, "{n} mod", "{n} mods")} · ${tn(h.errors, "{n} erreur", "{n} erreurs")} · ${tn(h.warnings, "{n} avertissement", "{n} avertissements")}</div>
    <div class="muted mono small">${esc(h.source)}</div></div></div>`;

  const modList = (title, rows, render, cls = "") => (rows.length ? `<div class="group-title"><h3>${title}</h3><span>${rows.length}</span></div>
    <div class="rows ${cls}">${rows.map(render).join("")}</div>` : "");
  const issueMini = (i) => `<div class="row"><span class="sev-dot ${i.severity}" title="${SEV()[i.severity]}"></span><div class="grow"><div class="nm">${esc(i.title)}</div><div class="why">${esc(i.message)}</div></div></div>`;

  views.compare = {
    title: () => t("Comparer deux modpacks"),
    render() {
      const c = S.cmp, r = c.result;
      const delta = r ? r.score_delta : 0;
      return `<section>
        <div class="logs-head"><div><h2>${t("Quoi de neuf entre deux packs ?")}</h2>
          <p>${t("Compare deux dossiers mods (deux versions d'un même pack, ou ton pack et celui d'un ami) : mods ajoutés, retirés, mis à jour, et problèmes apparus ou résolus.")}</p></div><img src="/assets/illustrations/conflict.svg" alt=""></div>
        <div class="build-card">
          ${pathField(t("Pack de départ (avant)"), "cmp.a", c.a)}
          ${pathField(t("Pack d'arrivée (après)"), "cmp.b", c.b)}
          ${S.a ? `<div class="build-line"><button class="link-btn" data-act="cmp-use" data-side="a">${t("Utiliser le pack analysé comme départ")}</button>
            <button class="link-btn" data-act="cmp-use" data-side="b">${t("…comme arrivée")}</button></div>` : ""}
          ${c.error ? `<div class="err-box" style="margin:0">${esc(c.error)}</div>` : ""}
          ${c.busy ? `<div class="progress"><div class="progress-bar indeterminate"><i id="pbar"></i></div><div class="progress-label" id="plabel">${t("Recherche des fichiers .jar…")}</div></div>` : ""}
          <div class="build-line"><span class="muted">${S.online ? t("Modrinth activé") : t("Hors ligne")}</span><span class="grow"></span>
            <button class="btn primary" data-act="compare" ${c.busy ? "disabled" : ""}>${t("Comparer")}</button></div>
        </div>
        ${r ? `<div class="cmp-grid">${headCard(r.a, t("Avant"))}<div class="cmp-arrow ${delta > 0 ? "up" : delta < 0 ? "down" : ""}">${delta > 0 ? "+" : ""}${delta}</div>${headCard(r.b, t("Après"))}</div>
          ${r.notes.length ? `<div class="warn-box">${r.notes.map(esc).join("<br>")}</div>` : ""}
          <div class="stats">
            <div class="stat ok"><b data-count="${r.added.length}">${r.added.length}</b><span>${t("ajoutés")}</span></div>
            <div class="stat err"><b data-count="${r.removed.length}">${r.removed.length}</b><span>${t("retirés")}</span></div>
            <div class="stat"><b data-count="${r.updated.length}">${r.updated.length}</b><span>${t("mis à jour")}</span></div>
            <div class="stat"><b data-count="${r.unchanged}">${r.unchanged}</b><span>${t("inchangés")}</span></div></div>
          ${modList(t("Problèmes apparus"), r.new_issues, issueMini)}
          ${modList(t("Problèmes résolus"), r.fixed_issues, issueMini)}
          ${modList(t("Ajoutés"), r.added, (m) => `<div class="row add"><div class="grow"><div class="nm">${esc(m.name)}</div><div class="why">${esc(m.version || "")}</div></div></div>`)}
          ${modList(t("Retirés"), r.removed, (m) => `<div class="row rem"><div class="grow"><div class="nm">${esc(m.name)}</div><div class="why">${esc(m.version || "")}</div></div></div>`)}
          ${modList(t("Mis à jour"), r.updated, (m) => `<div class="row"><div class="grow"><div class="nm">${esc(m.name)}</div></div><span class="chip mono">${esc(m.from || "?")} → ${esc(m.to || "?")}</span></div>`)}
          ${modList(t("Version plus ancienne"), r.downgraded, (m) => `<div class="row"><div class="grow"><div class="nm">${esc(m.name)}</div></div><span class="chip mono">${esc(m.from || "?")} → ${esc(m.to || "?")}</span></div>`)}` : ""}
      </section>`;
    },
    after() { if (S.cmp.busy && S.cmp.job) X.pbar(S.cmp.job); },
  };
  act("cmp-use", (el) => { S.cmp[el.dataset.side] = S.a.source; refresh(); });
  act("compare", async () => {
    const c = S.cmp; c.error = ""; c.result = null;
    if (!c.a.trim() || !c.b.trim()) { c.error = t("Indique les deux dossiers à comparer."); return refresh(); }
    c.busy = true; c.job = {}; refresh();
    try { c.result = await runJob(api("/api/compare", { a: c.a.trim(), b: c.b.trim(), online: S.online }), (j) => { c.job = j; X.pbar(j); }); }
    catch (e) { c.error = e.message; }
    c.busy = false; refresh();
  });

  /* ---- Crash : journal + recherche par essais ------------------------------------------------------------------------- */
  views.crash = {
    title: () => t("Chercher la cause d'un crash"),
    render() {
      const tabs = `<div class="tabs" role="group">
        <button class="tab" data-act="crash-tab" data-k="log" aria-pressed="${S.crashTab === "log"}">${t("Lire un journal")}</button>
        <button class="tab" data-act="crash-tab" data-k="find" aria-pressed="${S.crashTab === "find"}">${t("Recherche par essais")}</button></div>`;
      return `<section>${tabs}${S.crashTab === "log" ? X.logsSection() : finder()}</section>`;
    },
  };
  act("crash-tab", (el) => { S.crashTab = el.dataset.k; refresh(); });

  function finder() {
    if (!S.a) return `<div class="empty"><h3>${t("Analyse d'abord un modpack")}</h3><p>${t("La recherche par essais a besoin de connaître tes mods.")}</p><button class="btn primary" data-act="goto" data-to="home">${t("Analyser un modpack")}</button></div>`;
    const c = S.crash;
    const intro = `<div class="logs-head"><div><h2>${t("Trouver le mod fautif par essais")}</h2>
      <p>${t("Quand le journal ne dit rien de clair : ModMaestro prépare des dossiers de test avec une partie de tes mods. Tu lances le jeu avec, tu réponds « ça plante » ou « ça marche », et il réduit les suspects (en général 5 à 8 essais pour des centaines de mods). Ton dossier d'origine n'est jamais modifié.")}</p></div><img src="/assets/illustrations/logs.svg" alt=""></div>`;
    if (!c) return `${intro}<div class="build-card"><div class="hint" style="margin:0">${t("Avant de commencer : le jeu doit planter avec le modpack complet, et tu dois pouvoir le relancer à chaque essai.")}</div>
      ${S.crashErr ? `<div class="err-box" style="margin:0">${esc(S.crashErr)}</div>` : ""}
      <div class="build-line"><span class="grow"></span><button class="btn primary" data-act="crash-start">${t("Commencer la recherche")}</button></div></div>`;
    const hint = c.hint && c.hint.length ? `<div class="build-card"><h3 class="card-title">${t("Suspects évidents")}</h3><p class="muted">${t("À regarder avant de commencer les essais :")}</p>
      <div class="chips">${c.hint.map((h) => `<span class="chip" title="${esc(h.why)}">${esc(h.name)} · ${esc(h.why)}</span>`).join("")}</div></div>` : "";
    if (c.done) {
      const names = (c.result && c.result.names) || [];
      return `${intro}<div class="success big"><b>${esc(c.summary || t("Aucun suspect n'a été trouvé."))}</b>
        <div class="chips" style="margin-top:12px">${names.map((n) => `<span class="chip accent">${esc(n.name)}</span>`).join("")}</div></div>
        <div class="build-line" style="margin-top:14px"><button class="btn" data-act="crash-reset">${t("Recommencer")}</button>
          <button class="btn" data-act="goto" data-to="base">${t("Enregistrer dans ma base…")}</button></div>${history(c)}`;
    }
    const p = c.pending;
    const confirm = p.kind === "confirm";
    return `${intro}${hint}<div class="build-card step">
      <div class="step-head"><span class="chip accent">${t("Essai {n}", { n: c.step })}</span><span class="muted">${t("environ {n} essai(s) restant(s)", { n: c.estimate })}</span></div>
      <div class="bar"><i style="width:${Math.max(4, Math.round((c.cleared / Math.max(1, c.cleared + c.remaining)) * 100))}%"></i></div>
      <h3 class="card-title">${confirm ? t("Dernier contrôle : lance le jeu sans le suspect") : t("Lance le jeu avec ces {n} mods", { n: p.count })}</h3>
      <p class="muted">${confirm ? t("ModMaestro retire le suspect trouvé : si le jeu démarre, c'est bien lui.") : t("{n} suspects restent en lice ; {m} sont mis de côté pour cet essai.", { n: p.in_play, m: p.excluded })}</p>
      <label class="field">${t("Dossier de test (nouveau, vide)")}<input class="input mono" data-model="crashOut" value="${esc(S.crashOut ?? c.suggested_output)}" spellcheck="false"></label>
      <div class="build-line"><button class="btn" data-act="crash-folder">${t("Créer le dossier de test")}</button></div>
      ${S.crashFolder ? `<div class="success"><b>${t("Dossier prêt")}</b> · ${tn(S.crashFolder.copied, "{n} mod copié", "{n} mods copiés")}<code>${esc(S.crashFolder.output)}</code>
        <div class="hint" style="margin:6px 0 0">${t("Place son contenu à la place de ton dossier mods (ou pointe ton lanceur dessus), lance le jeu, puis réponds ci-dessous.")}</div></div>` : ""}
      ${S.crashErr ? `<div class="err-box" style="margin:0">${esc(S.crashErr)}</div>` : ""}
      <div class="answers"><button class="btn danger" data-act="crash-ans" data-o="crash">${t("Ça plante")}</button>
        <button class="btn ok" data-act="crash-ans" data-o="fine">${t("Ça marche")}</button>
        <button class="btn" data-act="crash-ans" data-o="skip">${t("Je n'ai pas pu tester")}</button></div></div>${history(c)}`;
  }
  const history = (c) => (c.history.length ? `<div class="group-title"><h3>${t("Essais déjà faits")}</h3><span>${c.history.length}</span></div>
    <div class="rows">${c.history.map((h) => `<div class="row"><div class="grow"><div class="nm">${t("Essai {n}", { n: h.step })}</div><div class="why">${tn(h.in_play, "{n} mod en jeu", "{n} mods en jeu")}</div></div>
    <span class="chip ${h.outcome === "crash" ? "bad" : h.outcome === "fine" ? "ok" : ""}">${{ crash: t("plante"), fine: t("marche"), skip: t("non testé") }[h.outcome]}</span></div>`).join("")}</div>` : "");
  const setCrash = (v) => { S.crash = v; S.crashFolder = null; S.crashOut = undefined; S.crashErr = ""; };
  act("crash-start", async () => {
    try { const v = await api("/api/crash/start", { analysis: S.a.id, log_mods: ((S.logs.findings || []).flatMap((f) => f.mods || [])) }); setCrash(v); }
    catch (e) { S.crashErr = e.message; }
    refresh();
  });
  act("crash-reset", () => { S.crash = null; refresh(); });
  act("crash-folder", async () => {
    try { S.crashFolder = await api("/api/crash/folder", { analysis: S.a.id, id: S.crash.id, output: S.crashOut ?? S.crash.suggested_output }); S.crashErr = ""; }
    catch (e) { S.crashErr = e.message; }
    refresh();
  });
  act("crash-ans", async (el) => {
    try {
      const v = await api("/api/crash/answer", { analysis: S.a.id, id: S.crash.id, outcome: el.dataset.o });
      setCrash(v);
    } catch (e) { S.crashErr = e.message; }
    refresh();
  });

  /* ---- Exporter ---------------------------------------------------------------------------------------------------- */
  const ex = () => (S.exp ??= { name: (S.a.source || "modpack").split(/[\\/]/).filter(Boolean).pop().replace(/\.zip$/i, ""), version: "1.0.0",
    mc: S.a.instance.mc || S.a.mc_version || "", loader: S.a.instance.loader || S.a.loader || "", lv: S.a.instance.loader_version || "",
    mrOut: S.a.suggested.mrpack, zipOut: S.a.suggested.zip, unknown: true, serverOnly: false, res: null, err: "", busy: "", reportFiles: true, reportSource: false });
  const LOADERS = ["fabric", "forge", "neoforge", "quilt"];

  views.export = {
    title: () => t("Exporter le modpack"),
    render() {
      const e = ex(), a = S.a;
      const result = (r, kind) => (r && r.kind === kind ? `<div class="success"><b>${t("Fichier créé !")}</b> ${size(r.bytes)}<code>${esc(r.path)}</code>
        ${r.referenced !== undefined ? `<div class="why">${t("{a} mods référencés, {b} copiés dans le fichier.", { a: r.referenced, b: r.embedded })}</div>` : ""}
        ${(r.warnings || []).map((w) => `<div class="warn-box" style="margin:8px 0 0">${esc(w)}</div>`).join("")}
        <div class="build-line" style="margin-top:10px"><button class="btn sm" data-act="copy" data-v="${esc(r.path)}">${t("Copier le chemin")}</button></div></div>` : "");
      return `<section>
        <div class="server-head"><div><h2>${t("Partage ton modpack")}</h2><p>${t("Crée un fichier à envoyer à tes amis, ou un rapport qui les aide à t'aider. Ton dossier d'origine n'est jamais modifié.")}</p></div><img src="/assets/illustrations/server.svg" alt=""></div>

        <div class="build-card"><h3 class="card-title">${t("Rapport HTML pour demander de l'aide")}</h3>
          <p class="muted">${t("Une page unique, lisible partout : la liste propre des mods et des problèmes. À envoyer à un ami ou à poster sur un forum. Aucun chemin de ton ordinateur n'y figure.")}</p>
          <label class="check"><input type="checkbox" data-model="exp.reportFiles" ${e.reportFiles ? "checked" : ""}> ${t("Inclure les noms de fichiers des mods")}</label>
          <label class="check"><input type="checkbox" data-model="exp.reportSource" ${e.reportSource ? "checked" : ""}> ${t("Inclure le nom du dossier analysé")}</label>
          <div class="build-line"><button class="btn primary" data-act="report-html">${t("Télécharger le rapport HTML")}</button>
            <button class="btn" data-act="report-md">${t("Télécharger en Markdown")}</button></div></div>

        <div class="build-card"><h3 class="card-title">${t("Modpack Modrinth (.mrpack)")}</h3>
          <p class="muted">${t("Le format ouvert lu par Prism, ATLauncher, la Modrinth App… Les mods reconnus sont simplement référencés (fichier léger) ; l'analyse en ligne est donc recommandée.")}</p>
          ${a.online && a.online.enabled ? "" : `<div class="warn-box" style="margin:0">${t("Cette analyse est hors ligne : tous les mods seraient copiés dans le fichier. Active Modrinth sur l'accueil puis relance l'analyse.")}</div>`}
          <div class="two"><label class="field">${t("Nom")}<input class="input" data-model="exp.name" value="${esc(e.name)}"></label>
            <label class="field">${t("Version du pack")}<input class="input" data-model="exp.version" value="${esc(e.version)}"></label>
            <label class="field">${t("Version de Minecraft")}<input class="input" data-model="exp.mc" value="${esc(e.mc)}" placeholder="1.20.1"></label>
            <label class="field">${t("Loader")}<select class="input" data-model="exp.loader">${LOADERS.map((l) => `<option value="${l}" ${e.loader === l ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="field">${t("Version du loader")}<input class="input" data-model="exp.lv" value="${esc(e.lv)}" placeholder="0.15.11"></label>
            <label class="field">${t("Fichier de sortie")}<input class="input mono" data-model="exp.mrOut" value="${esc(e.mrOut)}" spellcheck="false"></label></div>
          <label class="check"><input type="checkbox" data-model="exp.unknown" ${e.unknown ? "checked" : ""}> ${t("Copier dans le fichier les mods inconnus de Modrinth")}</label>
          ${e.err && e.busy === "" && e.errKind === "mr" ? `<div class="err-box" style="margin:0">${esc(e.err)}</div>` : ""}
          <div class="build-line"><span class="grow"></span><button class="btn primary" data-act="export-mr" ${e.busy ? "disabled" : ""}>${e.busy === "mr" ? t("Création…") : t("Créer le .mrpack")}</button></div>
          ${result(e.res, "mr")}</div>

        <div class="build-card"><h3 class="card-title">${t("Archive .zip des mods")}</h3>
          <p class="muted">${t("Une archive simple de tes mods, pour les envoyer tels quels.")}</p>
          <label class="field">${t("Fichier de sortie")}<input class="input mono" data-model="exp.zipOut" value="${esc(e.zipOut)}" spellcheck="false"></label>
          <label class="check"><input type="checkbox" data-model="exp.serverOnly" ${e.serverOnly ? "checked" : ""}> ${t("Seulement les mods du serveur")}</label>
          ${e.err && e.busy === "" && e.errKind === "zip" ? `<div class="err-box" style="margin:0">${esc(e.err)}</div>` : ""}
          <div class="build-line"><span class="grow"></span><button class="btn primary" data-act="export-zip" ${e.busy ? "disabled" : ""}>${e.busy === "zip" ? t("Création…") : t("Créer le .zip")}</button></div>
          ${result(e.res, "zip")}</div>
      </section>`;
    },
  };
  act("report-html", async () => {
    const e = ex();
    try { const r = await api("/api/report/html", { analysis: S.a.id, files: e.reportFiles, source: e.reportSource }); download(r.html, r.filename, "text/html"); toast(t("Rapport créé")); }
    catch (err) { toast(err.message); }
  });
  act("report-md", async () => {
    try { const { markdown } = await api("/api/report", { analysis: S.a.id }); download(markdown, "rapport-modmaestro.md", "text/markdown"); toast(t("Rapport créé")); } catch (err) { toast(err.message); }
  });
  async function doExport(kind, path, body) {
    const e = ex(); e.busy = kind; e.err = ""; e.res = null; refresh();
    try { e.res = { ...(await api(path, { analysis: S.a.id, ...body, ...X.picks() })), kind }; } catch (err) { e.err = err.message; e.errKind = kind; }
    e.busy = ""; refresh();
    const box = X.$(".success"); if (box) box.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  act("export-mr", () => { const e = ex(); doExport("mr", "/api/export/mrpack", { output: e.mrOut, name: e.name, version: e.version, mc: e.mc, loader: e.loader, loader_version: e.lv, include_unknown: e.unknown }); });
  act("export-zip", () => { const e = ex(); doExport("zip", "/api/export/zip", { output: e.zipOut, server_only: e.serverOnly }); });

  /* ---- Conseils de mods -------------------------------------------------------------------------------------------- */
  const CAT = () => ({ performance: t("Performances"), qol: t("Confort"), compat: t("Compatibilité"), library: t("Bibliothèques"), server: t("Serveur"), visual: t("Visuel") });
  views.tips = {
    title: () => t("Mods conseillés"),
    enter() { if (!S.tips && S.a) loadTips(); },
    render() {
      const T = S.tips;
      const head = `<div class="logs-head"><div><h2>${t("Des mods pour que les autres marchent mieux")}</h2>
        <p>${t("Selon les mods que tu as déjà, ModMaestro propose des compagnons connus : optimisation, correctifs de crash, bibliothèques utiles… Ce sont des suggestions, jamais des obligations.")}</p></div><img src="/assets/illustrations/welcome.svg" alt=""></div>`;
      if (!T) return `${head}<div class="hint">${S.tipsErr ? esc(S.tipsErr) : t("Chargement…")}</div>`;
      const groups = {};
      T.items.forEach((i) => (groups[i.category] ||= []).push(i));
      const card = (i) => `<div class="tip ${i.available === false ? "na" : ""}"><div class="grow"><div class="nm">${ext(i.url, esc(i.name))}
        ${i.available === true ? `<span class="chip ok">${t("disponible")}${i.version ? ` · ${esc(i.version)}` : ""}</span>` : i.available === false ? `<span class="chip bad">${t("pas pour Minecraft {mc}", { mc: esc(T.mc_version || "?") })}</span>` : ""}
        <span class="chip">${{ client: t("Client"), server: t("Serveur"), both: t("Les deux") }[i.side] || ""}</span></div>
        <div class="why">${esc(i.why)}</div>
        ${i.alternatives && i.alternatives.length ? `<div class="why">${t("Alternatives :")} ${i.alternatives.map(esc).join(", ")}</div>` : ""}</div></div>`;
      return `${head}
        ${T.note ? `<div class="hint">${esc(T.note)}</div>` : ""}${T.error ? `<div class="warn-box">${esc(T.error)}</div>` : ""}
        ${T.items.length ? Object.entries(groups).map(([k, items]) => `<div class="group-title"><h3>${CAT()[k] || esc(k)}</h3><span>${items.length}</span></div><div class="tips">${items.map(card).join("")}</div>`).join("")
          : `<div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${t("Rien à ajouter")}</h3><p>${t("Ton pack a déjà les compagnons habituels.")}</p></div>`}
        ${S.online ? "" : `<div class="hint">${t("Active Modrinth sur l'accueil pour vérifier la disponibilité de chaque mod pour ta version.")}</div>`}`;
    },
  };
  async function loadTips() {
    S.tips = null; S.tipsErr = "";
    try { S.tips = await api("/api/recommend", { analysis: S.a.id, online: S.online }); } catch (e) { S.tipsErr = e.message; }
    if (S.view === "tips") refresh();
  }
})();
