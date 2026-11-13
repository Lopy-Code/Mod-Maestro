"""Rapport HTML autonome (un seul fichier, sans connexion) à envoyer à un ami ou à poster pour demander de l'aide."""

from __future__ import annotations

import datetime as dt
import html
import json

from . import __version__
from .i18n import _, get_lang, ng

SEV_LABEL = {"error": lambda: _("Erreur"), "warning": lambda: _("Avertissement"), "info": lambda: _("Info")}
SIDE_LABEL = {"both": lambda: _("Client + serveur"), "client": lambda: _("Client"), "server": lambda: _("Serveur"),
              "unsure": lambda: _("À vérifier")}
VERDICT = {
    "ok": lambda: _("Rien d'important à signaler"),
    "warn": lambda: _("Quelques points à vérifier"),
    "bad": lambda: _("Au moins un problème certain"),
}


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def discord_summary(d: dict, include_files: bool = True) -> str:
    """Résumé en Markdown, prêt à coller dans un message."""
    lines = [f"**ModMaestro** — {d['loader_label']} · Minecraft {d['mc_version'] or '?'} · "
             + ng("{n} mod", "{n} mods", d["counts"]["mods"]) + f" · {_('score')} {d['score']}/100",
             f"> {VERDICT[d['verdict']]()}"]
    shown = [i for i in d["issues"] if not i.get("ignored") and i["severity"] != "info"][:8]
    for i in shown:
        lines.append(f"- {'🔴' if i['severity'] == 'error' else '🟠'} {i['title']}")
    more = len([i for i in d["issues"] if not i.get("ignored") and i["severity"] != "info"]) - len(shown)
    if more > 0:
        lines.append(_("… et {n} autre(s)", n=more))
    return "\n".join(lines)


_CSS = """
:root{--bg:#faf9f5;--card:#fff;--ink:#1f1e1d;--ink2:#5e5d59;--line:#e8e6dc;--acc:#d97757;--err:#b3261e;--errbg:#fceeec;
--warn:#8a5a00;--warnbg:#fdf3dc;--info:#2f5f8a;--infobg:#e8f0f8;--ok:#2e6b45;--okbg:#e6f3ea;--r:14px}
@media(prefers-color-scheme:dark){:root{--bg:#1c1b19;--card:#262522;--ink:#f3f1ea;--ink2:#a8a69d;--line:#383633;--acc:#e08a6c;
--err:#f2a8a0;--errbg:#3a2321;--warn:#e6c179;--warnbg:#38301d;--info:#9cc2e6;--infobg:#212d38;--ok:#9fd4b0;--okbg:#1f3226}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;align-items:center;gap:14px;margin-bottom:24px}
.mark{width:40px;height:40px;border-radius:12px;background:var(--acc);display:grid;place-items:center;color:#fff;font-weight:700;font-size:20px}
h1{font:600 28px/1.2 Georgia,"Times New Roman",serif;margin:0}h2{font:600 21px/1.3 Georgia,serif;margin:36px 0 12px}
.sub{color:var(--ink2);font-size:14px;margin-top:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:8px 0 8px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px}
.tile b{display:block;font-size:24px;line-height:1.2}.tile span{color:var(--ink2);font-size:13px}
.verdict{margin:16px 0;padding:14px 18px;border-radius:var(--r);font-weight:600}
.v-ok{background:var(--okbg);color:var(--ok)}.v-warn{background:var(--warnbg);color:var(--warn)}.v-bad{background:var(--errbg);color:var(--err)}
.note{margin:12px 0;padding:12px 16px;border-radius:var(--r);background:var(--infobg);color:var(--info);font-size:14px}
details.issue{background:var(--card);border:1px solid var(--line);border-left-width:4px;border-radius:var(--r);margin:10px 0;padding:0}
details.issue>summary{cursor:pointer;padding:12px 16px;list-style:none;font-weight:600}
details.issue>summary::-webkit-details-marker{display:none}
details.issue>summary::before{content:"▸";display:inline-block;margin-right:8px;color:var(--ink2);transition:transform .15s}
details[open].issue>summary::before{transform:rotate(90deg)}
.s-error{border-left-color:var(--err)}.s-warning{border-left-color:var(--warn)}.s-info{border-left-color:var(--info)}
.tag{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:99px;margin-left:8px;vertical-align:middle}
.t-error{background:var(--errbg);color:var(--err)}.t-warning{background:var(--warnbg);color:var(--warn)}.t-info{background:var(--infobg);color:var(--info)}
.body{padding:0 16px 14px 36px;color:var(--ink2);font-size:15px}.body p{margin:6px 0}.fix{color:var(--ink)}
.files{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink2);word-break:break-all}
.tools{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 12px}
input[type=search]{flex:1;min-width:200px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit}
button{padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;cursor:pointer}
button:hover{border-color:var(--acc)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r);background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px 14px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--ink2);font-weight:600;font-size:13px;background:var(--bg);position:sticky;top:0}tr:last-child td{border-bottom:0}
td.n{white-space:normal;font-weight:600}.mut{color:var(--ink2)}
footer{margin-top:40px;color:var(--ink2);font-size:13px;border-top:1px solid var(--line);padding-top:14px}
@media print{body{background:#fff}details.issue>.body{display:block}.tools{display:none}}
""".strip()

_JS = """
(function(){var q=document.getElementById('q'),rows=[].slice.call(document.querySelectorAll('#mods tbody tr')),c=document.getElementById('cnt');
function f(){var v=(q.value||'').toLowerCase(),n=0;rows.forEach(function(r){var s=r.getAttribute('data-s').indexOf(v)>-1;r.style.display=s?'':'none';if(s)n++});c.textContent=n}
q.addEventListener('input',f);
var b=document.getElementById('copy');b.addEventListener('click',function(){var t=document.getElementById('summary').value;
function ok(){var o=b.textContent;b.textContent=b.getAttribute('data-done');setTimeout(function(){b.textContent=o},1600)}
if(navigator.clipboard){navigator.clipboard.writeText(t).then(ok,function(){})}else{var s=document.getElementById('summary');s.style.display='block';s.select();document.execCommand('copy');s.style.display='none';ok()}});})();
""".strip()


def to_html(d: dict, include_files: bool = True, include_source: bool = False, title: str = "") -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    c = d["counts"]
    issues = [i for i in d["issues"] if not i.get("ignored")]
    ignored = [i for i in d["issues"] if i.get("ignored")]
    title = title or _("Rapport ModMaestro")
    mods = [m for m in d["mods"] if m["status"] in ("ok", "no-metadata")]
    o = d.get("online") or {}
    boot = d.get("boot")

    tiles = [
        (d["loader_label"], _("Loader")), (d["mc_version"] or "?", "Minecraft"),
        (str(c["mods"]), _("Mods")), (f"{d['score']}/100", _("Score de santé")),
        (str(c["errors"]), _("Erreurs")), (str(c["warnings"]), _("Avertissements")),
    ]
    parts = [f"<!doctype html><html lang=\"{get_lang()}\"><head><meta charset=\"utf-8\">"
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             f"<title>{e(title)}</title><style>{_CSS}</style></head><body><main>",
             f"<header><div class=\"mark\">M</div><div><h1>{e(title)}</h1>"
             f"<div class=\"sub\">{e(now)} · ModMaestro {e(__version__)}"
             + (f" · {e(d['source'])}" if include_source else "") + "</div></div></header>",
             "<div class=\"tiles\">" + "".join(f"<div class=\"tile\"><b>{e(v)}</b><span>{e(k)}</span></div>" for v, k in tiles) + "</div>",
             f"<div class=\"verdict v-{d['verdict']}\">{e(VERDICT[d['verdict']]())}</div>"]
    if boot and boot.get("status") == "ok" and boot.get("fresh"):
        parts.append(f"<div class=\"note\">{e(_('Ce modpack a démarré d’après son journal (latest.log) : les alertes ci-dessous sont à prendre avec recul.'))}</div>")
    elif boot and boot.get("status") == "crashed" and boot.get("fresh"):
        parts.append(f"<div class=\"note\">{e(_('Le dernier lancement a échoué d’après latest.log.'))}</div>")
    if o.get("enabled"):
        parts.append(f"<div class=\"note\">{e(_('Mods reconnus sur Modrinth : {a}/{b}.', a=o.get('identified', 0), b=o.get('total', 0)))}</div>")

    # --- problèmes
    parts.append(f"<h2>{e(_('Problèmes détectés'))}</h2>")
    if not issues:
        parts.append(f"<p class=\"mut\">{e(_('Aucun problème détecté.'))}</p>")
    for i in issues:
        files = ""
        if include_files and i["files"]:
            files = f"<p class=\"files\">{e(', '.join(i['files'][:12]))}{e(' …') if len(i['files']) > 12 else ''}</p>"
        fix = f"<p class=\"fix\"><b>{e(_('À faire :'))}</b> {e(i['fix'])}</p>" if i.get("fix") else ""
        parts.append(
            f"<details class=\"issue s-{i['severity']}\"{' open' if i['severity'] == 'error' else ''}><summary>{e(i['title'])}"
            f"<span class=\"tag t-{i['severity']}\">{e(SEV_LABEL[i['severity']]())}</span></summary>"
            f"<div class=\"body\"><p>{e(i['message'])}</p>{fix}{files}</div></details>")
    if ignored:
        parts.append(f"<p class=\"mut\">{e(ng('{n} alerte ignorée par l’utilisateur.', '{n} alertes ignorées par l’utilisateur.', len(ignored)))}</p>")

    # --- liste des mods
    parts.append(f"<h2>{e(_('Liste des mods'))} (<span id=\"cnt\">{len(mods)}</span>)</h2>")
    parts.append(f"<div class=\"tools\"><input id=\"q\" type=\"search\" placeholder=\"{e(_('Filtrer…'))}\" aria-label=\"{e(_('Filtrer…'))}\">"
                 f"<button id=\"copy\" type=\"button\" data-done=\"{e(_('Copié !'))}\">{e(_('Copier un résumé pour Discord'))}</button></div>")
    head = [_("Mod"), _("Version"), _("Côté")] + ([_("Fichier")] if include_files else [])
    parts.append("<div class=\"wrap\"><table id=\"mods\"><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr></thead><tbody>")
    for m in sorted(mods, key=lambda x: (x["name"] or "").lower()):
        cells = [f"<td class=\"n\">{e(m['name'])}</td>", f"<td class=\"mut\">{e(m['version'] or '—')}</td>",
                 f"<td>{e(SIDE_LABEL.get(m['side'], lambda: m['side'])())}</td>"]
        if include_files:
            cells.append(f"<td class=\"mut\">{e(m['file'])}</td>")
        hay = " ".join([m["name"] or "", m["modid"] or "", m["version"] or "", m["file"] if include_files else ""]).lower()
        parts.append(f"<tr data-s=\"{e(hay)}\">{''.join(cells)}</tr>")
    parts.append("</tbody></table></div>")

    parts.append(f"<footer>{e(_('Rapport généré localement par ModMaestro. Il ne contient ni ton nom d’utilisateur ni le chemin de ton dossier.'))}"
                 f"{'' if include_files else ' ' + e(_('Les noms de fichiers sont masqués.'))}</footer>")
    summary = discord_summary(d, include_files)
    parts.append(f"<textarea id=\"summary\" style=\"display:none\">{e(summary)}</textarea>")
    parts.append(f"<script>{_JS}</script></main></body></html>")
    return "".join(parts)
