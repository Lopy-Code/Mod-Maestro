/* ModMaestro — glisser-déposer d'un dossier, de .jar, d'un .zip ou d'un .mrpack dans la fenêtre.
   Le navigateur ne donne pas le chemin des fichiers déposés : on envoie leur contenu au programme local (127.0.0.1),
   qui les range dans un dossier temporaire. On n'envoie que les .jar, logs/latest.log et les archives. */
(() => {
  "use strict";
  const X = window.MMX;
  const { $, esc, t, S, toast } = X;
  let depth = 0, busy = false;

  const veil = document.createElement("div");
  veil.className = "drop-veil"; veil.hidden = true;
  document.body.appendChild(veil);
  const say = (title, sub = "") => { veil.hidden = false; veil.innerHTML = `<div class="drop-box"><b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`; };
  const hide = () => { veil.hidden = true; };

  const hasFiles = (e) => e.dataTransfer && Array.prototype.includes.call(e.dataTransfer.types || [], "Files");

  /* Lecture récursive d'un dossier déposé (API FileSystemEntry). */
  const readAll = (reader) => new Promise((res, rej) => {
    const out = [];
    const next = () => reader.readEntries((b) => (b.length ? (out.push(...b), next()) : res(out)), rej);
    next();
  });
  const fileOf = (entry) => new Promise((res, rej) => entry.file(res, rej));
  async function walk(entry, prefix, out) {
    if (entry.isFile) { out.push({ rel: prefix + entry.name, file: await fileOf(entry) }); return; }
    if (entry.isDirectory) for (const c of await readAll(entry.createReader())) await walk(c, prefix + entry.name + "/", out);
  }

  /* Nom du fichier sur le disque temporaire, ou null si on n'en veut pas. */
  function target(rel, fromDir) {
    const p = rel.replace(/\\/g, "/");
    const low = p.toLowerCase();
    if (!fromDir) {                                 // fichier déposé seul (pas dans un dossier)
      if (/\.(zip|mrpack)$/.test(low)) return p;
      if (/\.jar(\.disabled)?$/.test(low)) return "mods/" + p;
      return null;
    }
    const parts = p.split("/").slice(1);            // on retire le nom du dossier déposé
    const joined = parts.join("/"), jl = joined.toLowerCase();
    const m = jl.match(/(?:^|\/)mods\/(.+\.jar(?:\.disabled)?)$/);
    if (m) return "mods/" + joined.slice(joined.length - m[1].length);
    if (/(?:^|\/)logs\/latest\.log$/.test(jl) && parts.length <= 3) return "logs/latest.log";
    const base = joined.replace(/^(?:\.?minecraft\/)/i, "");                            // instance : dossier racine ou sous-dossier minecraft
    if (/^(server\.properties|options\.txt|user_jvm_args\.txt)$/i.test(base)) return base.toLowerCase();
    if (/^config\/(?:[^/]+\/){0,2}[^/]+\.(toml|json5?|properties|cfg)$/i.test(base)) return base;
    if (parts.length === 1 && /\.jar(\.disabled)?$/.test(jl)) return "mods/" + parts[0];   // le dossier déposé est « mods » lui-même
    return null;
  }

  async function send(file, rel, session) {
    let r;
    try {
      r = await fetch(`/api/upload?session=${encodeURIComponent(session)}&rel=${encodeURIComponent(rel)}&lang=${X.lang()}`,
        { method: "POST", headers: { "X-MM-Token": X.MM.token || "", "Content-Type": "application/octet-stream" }, body: file });
    } catch { throw new Error(t("Impossible de joindre ModMaestro : le programme est-il toujours lancé ?")); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || t("Erreur {code}", { code: r.status }));
    return d;
  }

  async function handle(items, files) {
    // Les entrées doivent être lues tout de suite : elles disparaissent à la fin de l'évènement « drop ».
    const entries = items.map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
    const found = [];
    if (entries.length) {
      for (const e of entries) {
        const tmp = []; await walk(e, "", tmp);
        for (const f of tmp) found.push({ file: f.file, rel: target(e.isDirectory ? f.rel : f.rel, e.isDirectory) });
      }
    } else for (const f of files) found.push({ file: f, rel: target(f.name, false) });
    const list = found.filter((x) => x.rel && (!/^(config\/|server\.properties|options\.txt|user_jvm_args\.txt)/.test(x.rel) || x.file.size <= 2 * 1024 * 1024));
    if (!list.length) throw new Error(t("Aucun .jar, .zip ou .mrpack trouvé dans ce que tu as déposé."));
    const archives = list.filter((x) => /\.(zip|mrpack)$/i.test(x.rel));
    const send1 = archives.length ? [archives[0]] : list;      // une archive à la fois, sinon tous les mods
    let session = "", root = "", path = "";
    for (let i = 0; i < send1.length; i++) {
      say(t("Envoi à ModMaestro…"), `${i + 1}/${send1.length} · ${send1[i].rel.split("/").pop()}`);
      const r = await send(send1[i].file, send1[i].rel, session);
      session = r.session; root = r.root; path = r.path;
    }
    return archives.length ? path : root;
  }

  document.addEventListener("dragenter", (e) => { if (!hasFiles(e) || busy) return; depth++; say(t("Dépose ton dossier de mods, un .jar ou un .zip ici")); e.preventDefault(); });
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("dragleave", (e) => { if (!hasFiles(e) || busy) return; depth = Math.max(0, depth - 1); if (!depth) hide(); });
  document.addEventListener("drop", async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0;
    if (busy || S.busy) { hide(); return toast(t("Une analyse est déjà en cours.")); }
    busy = true;
    try {
      const path = await handle(Array.from(e.dataTransfer.items || []), Array.from(e.dataTransfer.files || []));
      hide(); X.analyze(path);
    } catch (err) { hide(); toast(err.message); }
    busy = false;
  });
})();
