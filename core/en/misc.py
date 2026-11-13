"""Traductions anglaises (compare, contribute, crashfinder, export, recommend, serverkit). Clé = texte français exact passé à _() / ng(), valeur = anglais avec les mêmes {champs}."""

EN = {
    # compare
    "Les deux packs ne tournent pas sous le même loader ({a} / {b}) : la plupart des mods diffèrent.":
        "The two packs don't run on the same loader ({a} / {b}): most mods will differ.",
    "Versions de Minecraft différentes ({a} / {b}).": "Different Minecraft versions ({a} / {b}).",
    # contribute
    "Base communautaire : {n} entrée(s) proposée(s)": "Community database: {n} proposed entr(ies)",
    "## Proposition d'entrées pour la base communautaire": "## Proposed entries for the community database",
    "### Ce que j'ai observé": "### What I observed",
    "### Fichiers (format `core/data/community/`)": "### Files (`core/data/community/` format)",
    "### Source / preuve": "### Source / evidence",
    "(colle ici un extrait de log, un lien Modrinth ou une issue)": "(paste a log excerpt, a Modrinth link or an issue here)",
    "Rien à proposer : ta base personnelle est vide. Enregistre d'abord un conflit ou un mod client.":
        "Nothing to propose: your personal database is empty. Save a conflict or a client-only mod first.",
    "Pack": "Pack",
    # crashfinder
    "Aucun suspect n'a été trouvé.": "No suspect was found.",
    "Le mod fautif est {names} : le jeu démarre sans lui.": "The faulty mod is {names}: the game starts without it.",
    "Le fautif est dans ce groupe de {n} mod, qui dépendent les uns des autres : {names}.":
        "The culprit is in this group of {n} mod, which depend on each other: {names}.",
    "Le fautif est dans ce groupe de {n} mods, qui dépendent les uns des autres : {names}.":
        "The culprit is in this group of {n} mods, which depend on each other: {names}.",
    "Aucun mod ne plante seul : c'est une combinaison de mods qui pose problème (conflit). Teste en retirant les mods suivants par paires : {names}.":
        "No single mod crashes the game on its own: a combination of mods is the problem (a conflict). Try removing the following mods in pairs: {names}.",
    "{names} semble impliqué, mais le jeu plante encore sans lui : plusieurs mods se gênent entre eux, ou la cause n'est pas un mod (version de Java, mémoire, configuration). Regarde le journal de crash.":
        "{names} seems to be involved, but the game still crashes without it: several mods are getting in each other's way, or the cause isn't a mod (Java version, memory, configuration). Check the crash log.",
    "Réponse inconnue.": "Unknown answer.",
    "Aucun test en cours.": "No test in progress.",
    "Le dossier de test ne doit pas être le dossier de mods (ni dedans, ni le contenir).":
        "The test folder must not be the mods folder (neither inside it nor containing it).",
    "« {path} » existe déjà et n'est pas vide. Choisis un autre nom.": "\"{path}\" already exists and is not empty. Choose another name.",
    "Le mod fautif est probablement {names} (non confirmé).": "The faulty mod is probably {names} (unconfirmed).",
    "Cité dans le journal": "Mentioned in the log",
    "Ajouté récemment": "Recently added",
    # export
    "Exporté avec ModMaestro": "Exported with ModMaestro",
    "Le fichier exporté ne doit pas être écrit dans le dossier de mods.": "The exported file must not be written inside the mods folder.",
    "« {path} » existe déjà : choisis un autre nom.": "\"{path}\" already exists: choose another name.",
    "La version de Minecraft est nécessaire pour un .mrpack.": "The Minecraft version is required for a .mrpack.",
    "Le loader du pack est inconnu : indique NeoForge, Forge, Fabric ou Quilt.": "The pack's loader is unknown: specify NeoForge, Forge, Fabric or Quilt.",
    "La version du loader est nécessaire (par exemple 21.1.172 pour NeoForge).": "The loader version is required (for example 21.1.172 for NeoForge).",
    "{n} mod(s) inconnu(s) de Modrinth ont été copiés dans le fichier. Ne publie pas ce pack tel quel : tu n'as peut-être pas le droit de redistribuer ces mods.":
        "{n} mod(s) unknown to Modrinth were copied into the file. Don't publish this pack as is: you may not have the right to redistribute these mods.",
    "{n} mod(s) inconnu(s) de Modrinth ont été laissés de côté : le pack sera incomplet.":
        "{n} mod(s) unknown to Modrinth were left out: the pack will be incomplete.",
    "L'analyse a été faite hors ligne : aucun mod n'a pu être référencé, tout est copié dans le fichier. Relance l'analyse avec Modrinth pour obtenir un .mrpack léger.":
        "The analysis was done offline: no mod could be referenced, so everything is copied into the file. Re-run the analysis with Modrinth to get a lightweight .mrpack.",
    # recommend
    "Disponibilité non vérifiée pour Minecraft {mc} : active Modrinth pour la contrôler.":
        "Availability not checked for Minecraft {mc}: turn on Modrinth to check it.",
    # serverkit
    "Le serveur du loader n'est pas installé : lis README-SERVER.txt.": "The loader's server is not installed: read README-SERVER.txt.",
    "Généré par ModMaestro": "Generated by ModMaestro",
    "Java {n} ou plus récent est nécessaire (trouvé : ${{JV:-aucun}}).": "Java {n} or newer is required (found: ${{JV:-none}}).",
    "Java {n} ou plus récent est nécessaire.": "Java {n} or newer is required.",
    "SERVEUR {loader} — Minecraft {mc}": "{loader} SERVER — Minecraft {mc}",
    "1. Installe Java {n} (ou plus récent).": "1. Install Java {n} (or newer).",
    "2. Télécharge l'installateur de {loader} sur le site officiel : {url}": "2. Download the {loader} installer from the official website: {url}",
    "   puis, dans ce dossier : {cmd}": "   then, in this folder: {cmd}",
    "3. Les mods sont déjà dans le dossier « mods ».": "3. The mods are already in the \"mods\" folder.",
    "5. Lance start.sh (Linux / macOS) ou start.bat (Windows).": "5. Run start.sh (Linux / macOS) or start.bat (Windows).",
    "Mémoire allouée : {ram} Go (estimation d'après le nombre de mods : ajuste-la dans {where}).":
        "Allocated memory: {ram} GB (estimated from the number of mods: adjust it in {where}).",
    "Les arguments Java sont ceux d'Aikar (G1GC), la référence pour les serveurs Minecraft.":
        "The Java arguments are Aikar's (G1GC), the reference for Minecraft servers.",
    "Le dossier de sortie ne doit pas être le dossier de mods.": "The output folder must not be the mods folder.",
    "Port invalide (1 à 65535).": "Invalid port (1 to 65535).",
    "Nombre de joueurs invalide (1 à 1000).": "Invalid number of players (1 to 1000).",
    "Les distances doivent être comprises entre 2 et 32.": "Distances must be between 2 and 32.",
    "Mémoire invalide (1 à 64 Go).": "Invalid memory (1 to 64 GB).",
    "eula.txt est à « false » : tu devras l'accepter toi-même avant le premier lancement.":
        "eula.txt is set to \"false\": you'll have to accept it yourself before the first launch.",
    "Fichiers déjà présents, laissés intacts : {names}.": "Files already present, left untouched: {names}.",
    "4. eula.txt : tu as accepté le CLUF de Mojang.": "4. eula.txt: you accepted Mojang's EULA.",
    "4. Ouvre eula.txt et remplace eula=false par eula=true si tu acceptes le CLUF de Mojang (https://aka.ms/MinecraftEULA).":
        "4. Open eula.txt and replace eula=false with eula=true if you accept Mojang's EULA (https://aka.ms/MinecraftEULA).",
}
