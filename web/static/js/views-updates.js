/* ModMaestro — mise à jour des mods depuis Modrinth : test de compatibilité, puis création d'un NOUVEAU dossier. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, esc, t, tn, S, views, act, api, runJob, toast, refresh, go, ICON } = X;
  const U = (S.upd = { sel: null, res: null, busy: "", err: "", out: null, key: "" });

  const list = () => {
    const i = ((S.a && S.a.issues) || []).find((x) => x.id === "updates");
    return ((i && i.data && i.data.updates) || []).filter((u) => u.new);
  };
  function reset() {   // nouvelle analyse : on repart de zéro
    if (U.key !== (S.a && S.a.id)) { U.key = S.a && S.a.id; U.sel = new Set(list().map((u) => u.file)); U.res = null; U.out = null; U.err = ""; }
  }
  const selected = () => [...U.sel].sort();
  const tested = () => !!U.res && JSON.stringify(U.res.tested) === JSON.stringify(selected());
  const phase = (j) => (j.phase === "download" && j.total ? `${t("Téléchargement des mods du pack")} ${j.done}/${j.total}` : t("Test de compatibilité…"));

  views.updates = {
    title: () => t("Mises à jour des mods"),
    render() {
      reset();
      if (!S.a.online || !S.a.online.enabled) {
        return `<section><div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${t("Modrinth est désactivé")}</h3>
          <p>${t("Pour chercher des mises à jour, active l'option Modrinth sur l'accueil puis relance l'analyse. Seules les empreintes (SHA-1) des fichiers sont envoyées.")}</p>
          <button class="btn primary" data-act="upd-home">${t("Retour à l'accueil")}</button></div></section>`;
      }
      const ups = list();
      if (!ups.length) return `<section><div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${t("Tout est à jour")}</h3><p>${t("Aucune version plus récente trouvée sur Modrinth pour ton loader et ta version de Minecraft.")}</p></div></section>`;
      const by = {}; ((U.res && U.res.results) || []).forEach((r) => (by[r.file] = r));
      const rows = ups.map((u) => {
        const r = by[u.file];
        return `<div class="upd-row"><label class="check"><input type="checkbox" data-act="upd-toggle" data-file="${esc(u.file)}" ${U.sel.has(u.file) ? "checked" : ""} ${U.busy ? "disabled" : ""}>
          <span><b>${esc(u.name)}</b> <span class="muted">${esc(u.current)} → ${esc(u.latest)}</span></span></label>
          ${r ? `<span class="chip ${r.verdict === "ok" ? "accent" : "warn"}">${r.verdict === "ok" ? t("sans problème") : t("à risque")}</span>` : ""}
          ${r && r.problems.length ? `<ul class="upd-problems">${r.problems.map((p) => `<li><b>${esc(p.title)}</b> — ${esc(p.message)}</li>`).join("")}</ul>` : ""}</div>`;
      }).join("");
      const res = U.res;
      const extra = res ? `${res.new_issues.length ? `<div class="hint">${t("Autres problèmes créés par cette sélection")} : ${res.new_issues.map((p) => esc(p.title)).join(", ")}</div>` : ""}
        ${res.resolved.length ? `<div class="hint">${tn(res.resolved.length, "{n} problème résolu par la sélection", "{n} problèmes résolus par la sélection")} : ${res.resolved.map((p) => esc(p.title)).join(", ")}</div>` : ""}
        ${res.results.some((r) => r.verdict === "risky") ? `<button class="btn sm" data-act="upd-safe">${t("Garder seulement celles sans problème")}</button>` : ""}` : "";
      const out = U.out ? `<div class="success"><b>${t("Dossier créé")}</b><div class="mono" style="overflow-wrap:anywhere">${esc(U.out.output)}</div>
        <div>${tn(U.out.replaced, "{n} mod mis à jour", "{n} mods mis à jour")} · ${tn(U.out.kept, "{n} inchangé", "{n} inchangés")}. ${t("Ton dossier d'origine n'a pas été touché.")}</div></div>` : "";
      return `<section><div class="logs-head"><div><h2>${t("Mettre à jour les mods")}</h2>
        <p>${t("ModMaestro télécharge les versions plus récentes (adresses officielles Modrinth, empreinte vérifiée), les assemble dans un pack de test et le ré-analyse pour voir ce qui change. Le résultat est écrit dans un NOUVEAU dossier : ton dossier de mods n'est jamais modifié.")}</p></div></div>
        <div class="build-card">${rows}${extra}
          ${U.err ? `<div class="err-box">${esc(U.err)}</div>` : ""}
          <div class="build-line"><button class="btn ${tested() ? "" : "primary"}" data-act="upd-test" ${U.busy || !U.sel.size ? "disabled" : ""}>${U.busy ? esc(U.busy) : t("Tester la compatibilité")}</button>
            <button class="btn ${tested() ? "primary" : ""}" data-act="upd-apply" ${U.busy || !tested() ? "disabled" : ""}>${t("Créer le dossier mis à jour")}</button></div>
          ${!tested() && U.res ? `<div class="hint" style="margin:0">${t("La sélection a changé : relance le test avant de créer le dossier.")}</div>` : ""}${out}</div></section>`;
    },
  };

  act("upd-home", () => go("home"));
  act("upd-toggle", (el) => { el.checked ? U.sel.add(el.dataset.file) : U.sel.delete(el.dataset.file); U.out = null; refresh(); });
  act("upd-safe", () => { U.sel = new Set(U.res.results.filter((r) => r.verdict === "ok").map((r) => r.file)); U.out = null; refresh(); });
  act("upd-test", async () => {
    U.err = ""; U.out = null; U.busy = t("Téléchargement des mods du pack"); refresh();
    try {
      U.res = await runJob(api("/api/updates/test", { analysis: S.a.id, files: selected() }), (j) => { U.busy = phase(j); const b = $('[data-act="upd-test"]'); if (b) b.textContent = U.busy; });
    } catch (e) { U.err = e.message; U.res = null; }
    U.busy = ""; refresh();
  });
  act("upd-apply", async () => {
    U.err = ""; U.busy = t("Création du dossier…"); refresh();
    try { U.out = await api("/api/updates/apply", { analysis: S.a.id, files: selected() }); toast(t("Dossier créé")); }
    catch (e) { U.err = e.message; }
    U.busy = ""; refresh();
  });
})();
