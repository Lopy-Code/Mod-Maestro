/* ModMaestro — fenêtre de l'application : enregistrement par la boîte native et liens ouverts dans le navigateur du système.
   Chargé juste après lib.js (avant les écrans), et sans effet dans le navigateur. */
(() => {
  "use strict";
  const X = window.MMX;
  if (!X || !X.MM.desktop) return;
  const { t, api, toast } = X;

  /* La fenêtre n'a pas de dossier « Téléchargements » : on demande où enregistrer. */
  X.download = async (text, name) => {
    try {
      const r = await api("/api/desktop/save", { name, text });
      toast(r.saved ? t("Enregistré : {p}", { p: r.path }) : t("Enregistrement annulé"));
    } catch (e) { toast(e.message); }
  };

  /* Un lien https:// s'ouvre dans le navigateur du système, pas dans la fenêtre. */
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    const url = a && a.getAttribute("href");
    if (!url || !/^https:\/\//.test(url)) return;
    e.preventDefault();
    api("/api/open-external", { url }).catch((err) => toast(err.message));
  });
})();
