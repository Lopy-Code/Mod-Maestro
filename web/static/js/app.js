/* ModMaestro — démarrage : navigation, sélecteur de dossier, thème, langue, animations. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, $$, esc, t, tn, S, act, api, toast, go, refresh, render, updateNav, loadLang, setPath, ICON, store } = X;

  /* ---- Sélecteur de dossier --------------------------------------------------------------------------------------- */
  const B = { data: null, onPick: null, label: "" };
  async function openBrowser(start, onPick, label) {
    B.onPick = onPick; B.label = label || t("Analyser ce dossier");
    $("#browse-pick").textContent = B.label;
    $("#modal").hidden = false;
    await browseTo(start || "");
    $("#browse-path").focus();
  }
  async function browseTo(path) {
    try {
      const d = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
      B.data = d;
      $("#browse-path").value = d.path;
      $("#browse-up").disabled = !d.parent;
      $("#shortcuts").innerHTML = d.shortcuts.map((s) => `<button data-p="${esc(s.path)}">${esc(s.label)}<small>${esc(s.path)}</small></button>`).join("");
      $("#dirlist").innerHTML = d.entries.length ? d.entries.map((e) => `<li><button data-p="${esc(e.path)}" data-kind="${e.kind}">${e.kind === "zip" ? ICON.zip : ICON.folder}<span>${esc(e.name)}</span>${e.jars ? `<span class="chip accent jarcount">${e.jars} jar</span>` : ""}</button></li>`).join("") : `<li class="none">${t("Aucun sous-dossier.")}</li>`;
      $("#browse-hint").innerHTML = d.jars ? `<b>${tn(d.jars, "{n} mod trouvé", "{n} mods trouvés")}</b> ${t("dans ce dossier")}` : d.has_mods_dir ? t("Un dossier mods est présent ici") : t("Aucun .jar ici — ouvre le dossier mods");
    } catch (e) { toast(e.message); }
  }
  const closeBrowser = () => ($("#modal").hidden = true);
  act("browse", () => openBrowser($("#path") && $("#path").value, (p) => { S.pathInput = p; X.analyze(p); }));
  act("browse-to", (el) => {
    const m = el.dataset.model;
    openBrowser(X.model(m), (p) => { setPath(m, p); refresh(); }, t("Choisir ce dossier"));
  });

  /* ---- Réglages : thème, langue, animations --------------------------------------------------------------------------- */
  function applyMotion() {
    document.documentElement.classList.toggle("no-motion", !S.motion);
    const b = $("#motion-toggle"); if (b) b.setAttribute("aria-pressed", String(S.motion));
  }
  async function setLanguage(l) {
    if (l === X.lang()) return;
    X.setLang(l);
    await loadLang();
    $("#version").textContent = `v${X.MM.version || ""} · ${t("local par défaut")}`;
    updateNav(); render();
    // Les textes générés par le moteur (alertes, conseils…) sont dans la langue de l'analyse : on la refait.
    if (S.a && S.a.source && !S.busy) { toast(t("Langue changée : nouvelle analyse…")); X.analyze(S.a.source); S.tips = null; }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    await loadLang();
    $("#version").textContent = `v${X.MM.version || ""} · ${t("local par défaut")}`;
    $$(".nav-item").forEach((b) => b.addEventListener("click", () => !b.disabled && go(b.dataset.view)));
    $("#btn-new").addEventListener("click", () => { S.homeError = ""; go("home"); });
    $("#btn-export").addEventListener("click", () => go("export"));
    $("#theme-toggle").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next); store.set("mm-theme", next);
    });
    $("#motion-toggle").addEventListener("click", () => { S.motion = !S.motion; store.set("mm-motion", S.motion ? "on" : "off"); applyMotion(); refresh(); });
    $$("[data-lang]").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));
    applyMotion();

    $("#modal-close").addEventListener("click", closeBrowser);
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeBrowser(); });
    $("#dlg").addEventListener("click", (e) => { if (e.target.id === "dlg") X.closeDialog(); });
    $("#dlg-close").addEventListener("click", X.closeDialog);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeBrowser(); X.closeDialog(); } });
    $("#browse-up").addEventListener("click", () => B.data && B.data.parent && browseTo(B.data.parent));
    $("#browse-go").addEventListener("click", () => browseTo($("#browse-path").value));
    $("#browse-path").addEventListener("keydown", (e) => { if (e.key === "Enter") browseTo(e.target.value); });
    $("#shortcuts").addEventListener("click", (e) => { const b = e.target.closest("button[data-p]"); if (b) browseTo(b.dataset.p); });
    $("#dirlist").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-p]");
      if (!b) return;
      if (b.dataset.kind === "zip") { closeBrowser(); B.onPick && B.onPick(b.dataset.p); } else browseTo(b.dataset.p);
    });
    $("#browse-pick").addEventListener("click", () => { closeBrowser(); B.onPick && B.data && B.onPick(B.data.path); });

    updateNav(); render();
    if (X.MM.initial) X.analyze(X.MM.initial);
  });
})();
