/* ModMaestro — surveillance d'un serveur en cours : lit son journal et prévient quand un mod pose problème. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, esc, t, tn, S, act, api, toast, refresh, views, ICON } = X;
  const M = (S.mon = { path: "", id: null, snap: null, err: "", timer: null, seen: {}, busy: false });

  const SEV = () => ({ error: t("Erreur"), warning: t("Avertissement"), info: t("Info") });
  const STATUS = () => ({ waiting: t("En attente du journal…"), active: t("Serveur actif"), quiet: t("Aucune activité depuis 2 minutes") });
  const canNotify = () => "Notification" in window;

  function out() {
    const s = M.snap;
    if (!s) return "";
    const st = s.stats;
    const chips = `<div class="chips"><span class="chip ${s.status === "active" ? "accent" : ""}">${STATUS()[s.status] || s.status}</span>
      <span class="chip mono">${esc(s.log)}</span>
      <span class="chip">${tn(st.errors, "{n} erreur", "{n} erreurs")}</span><span class="chip">${tn(st.warns, "{n} avertissement", "{n} avertissements")}</span>
      ${st.lag ? `<span class="chip">${tn(st.lag, "{n} retard", "{n} retards")}</span>` : ""}${st.started ? `<span class="chip">${t("Démarrage terminé")}</span>` : ""}</div>`;
    const list = s.alerts.length ? `<div class="issues" style="margin-top:18px">${s.alerts.map((a) => `
      <details class="issue ${a.severity}" open><summary><span class="sev" title="${SEV()[a.severity]}">${ICON[a.severity]}</span>
        <div class="issue-main"><div class="issue-title">${esc(a.title)}${a.count > 1 ? ` <span class="chip">×${a.count}</span>` : ""}</div>
        <div class="issue-msg">${esc(a.message)}</div></div>${ICON.caret}</summary>
        <div class="issue-body"><div class="chips">${a.mods.map((m) => `<span class="chip accent">${esc((s.mods && s.mods[m]) || m)}</span>`).join("")}
          <span class="chip mono">${esc(a.first)}${a.last !== a.first ? ` → ${esc(a.last)}` : ""}</span></div></div></details>`).join("")}</div>`
      : `<div class="empty"><img src="/assets/illustrations/ok.svg" alt=""><h3>${t("Aucun problème détecté pour l'instant")}</h3><p>${t("ModMaestro continue de lire le journal et te prévient dès qu'un mod pose problème.")}</p></div>`;
    return chips + list;
  }
  const paint = () => { const o = $("#mon-out"); if (o) o.innerHTML = out(); };

  function notifyNew(alerts) {
    for (const a of alerts) {
      const rank = { info: 0, warning: 1, error: 2 }[a.severity];
      const prev = M.seen[a.id];
      if (prev === undefined || rank > prev) {
        M.seen[a.id] = rank;
        if (rank >= 1) {
          toast(a.title);
          if (canNotify() && Notification.permission === "granted" && document.hidden) {
            try { new Notification(a.title, { body: a.message.slice(0, 140) }); } catch { /* ignoré */ }
          }
        }
      }
    }
    const bad = alerts.some((a) => a.severity === "error");
    document.title = (bad ? "(!) " : "") + document.title.replace(/^\(!\) /, "");
  }

  async function tick() {
    if (!M.id) return;
    try { M.snap = await api("/api/monitor/poll", { id: M.id }); notifyNew(M.snap.alerts); paint(); }
    catch (e) { stop(false); M.err = e.message; refresh(); }
  }
  function stop(call = true) {
    clearInterval(M.timer); M.timer = null;
    if (call && M.id) api("/api/monitor/stop", { id: M.id }).catch(() => {});
    M.id = null; document.title = document.title.replace(/^\(!\) /, "");
  }

  views.monitor = {
    title: () => t("Surveillance du serveur"),
    render() {
      const running = !!M.id;
      return `<section><div class="logs-head"><div><h2>${t("Surveiller un serveur en cours")}</h2>
        <p>${t("ModMaestro lit le journal du serveur au fil de l'eau (lecture seule) et te prévient quand un mod produit des erreurs, quand le serveur n'arrive plus à suivre ou qu'il manque de mémoire. Rien n'est envoyé nulle part.")}</p></div>
        <img src="/assets/illustrations/logs.svg" alt=""></div>
        <div class="stack">
          <input class="input mono" data-model="mon.path" placeholder="${t("Dossier du serveur ou fichier latest.log")}" value="${esc(M.path)}" spellcheck="false" ${running ? "disabled" : ""}>
          <div class="hint" style="margin:0">${S.a && !M.path ? t("Vide : ModMaestro suit le journal du dossier analysé.") : t("Indique le dossier qui contient « logs/latest.log » ou le fichier lui-même.")}</div>
          ${M.err ? `<div class="err-box" style="margin:0">${esc(M.err)}</div>` : ""}
          <div class="build-line">${running ? `<button class="btn" data-act="mon-stop">${t("Arrêter la surveillance")}</button>` : `<button class="btn primary" data-act="mon-start">${t("Démarrer la surveillance")}</button>`}
            ${canNotify() && Notification.permission === "default" ? `<button class="btn" data-act="mon-notify">${t("Activer les notifications")}</button>` : ""}</div>
        </div><div id="mon-out">${out()}</div></section>`;
    },
  };

  act("mon-start", async () => {
    M.err = ""; M.seen = {}; M.snap = null;
    try {
      const r = await api("/api/monitor/start", { analysis: S.a && S.a.id, path: M.path.trim() });
      M.id = r.id; M.snap = r;
      notifyNew(r.alerts);
      M.timer = setInterval(tick, 2500);
    } catch (e) { M.err = e.message; }
    refresh();
  });
  act("mon-stop", () => { stop(); refresh(); });
  act("mon-notify", async () => { try { await Notification.requestPermission(); } catch { /* ignoré */ } refresh(); });
})();
