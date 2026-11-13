"""Traductions anglaises : analyse (analyzer, parser, builder, pipeline) et règles de la base de connaissances.

Clé = texte français exact passé à _() / ng() / tr(), valeur = anglais avec les mêmes {champs}.
"""

EN = {
    # --- analyzer : côté client / serveur ------------------------------------------------------------
    "le loader": "the loader",
    "Inconnu": "Unknown",
    "Déclaré côté client dans les métadonnées": "Declared client-side in its metadata",
    "Déclaré côté serveur dans les métadonnées": "Declared server-side in its metadata",
    "Marqué « à garder sur le serveur » dans la base de connaissances": "Marked “keep on the server” in the knowledge base",
    "Modrinth : ce mod ne fonctionne pas côté serveur": "Modrinth: this mod does not work on the server",
    "Modrinth : ce mod ne fonctionne pas côté client": "Modrinth: this mod does not work on the client",
    "Mod connu pour ne servir que côté client (rendu, interface, minimap…)": "Known to be client-only (rendering, interface, minimap…)",
    "Visionneuse de recettes : facultative sur un serveur": "Recipe viewer: optional on a server",
    "Modrinth : prend en charge le serveur": "Modrinth: supports the server",
    "Le nom évoque un mod côté client (« {kw} ») — à vérifier": "The name suggests a client-side mod (“{kw}”) — to check",
    "Sans métadonnées : bibliothèque ou mod ancien — à vérifier": "No metadata: library or old mod — to check",
    "Fichier illisible": "Unreadable file",
    "Conçu pour un autre loader que {loader}": "Built for a loader other than {loader}",
    "Doublon : version plus ancienne": "Duplicate: older version",
    "Gardé manuellement": "Kept manually",
    "Retiré manuellement": "Removed manually",
    "Gardé car requis par {name}": "Kept because {name} requires it",
    # --- analyzer : fichiers ---------------------------------------------------------------------------
    "Fichier illisible : {file}": "Unreadable file: {file}",
    "Retélécharge ce mod depuis sa source officielle, ou retire-le.": "Download this mod again from its official source, or remove it.",
    "Sans métadonnées : {file}": "No metadata: {file}",
    "Aucun neoforge.mods.toml / mods.toml / fabric.mod.json n'a été trouvé. C'est normal pour une bibliothèque ; si c'est censé être un mod, il ne sera pas chargé.":
        "No neoforge.mods.toml / mods.toml / fabric.mod.json was found. That is normal for a library; if this is supposed to be a mod, it will not be loaded.",
    "Vérifie que c'est bien un mod pour ce loader ; sinon ignore ce message.": "Check that this is really a mod for this loader; otherwise ignore this message.",
    "Mauvais loader : {file}": "Wrong loader: {file}",
    "Ce mod est conçu pour {found}, mais le pack tourne sous {loader}. Il ne sera pas chargé.":
        "This mod is built for {found}, but the pack runs on {loader}. It will not be loaded.",
    "Télécharge la version {loader} de ce mod, ou retire-le.": "Download the {loader} version of this mod, or remove it.",
    "Mod Forge dans un pack NeoForge : {file}": "Forge mod in a NeoForge pack: {file}",
    "NeoForge reste compatible avec les mods Forge jusqu'à Minecraft 1.20.1 : ce mod devrait se charger.":
        "NeoForge stays compatible with Forge mods up to Minecraft 1.20.1: this mod should load.",
    "Forge et NeoForge ont divergé depuis Minecraft 1.20.2 : ce mod risque de ne pas se charger (ou de planter) s'il n'existe pas en version NeoForge.":
        "Forge and NeoForge have diverged since Minecraft 1.20.2: this mod may fail to load (or crash) if it has no NeoForge version.",
    "Cherche la version NeoForge de ce mod.": "Look for the NeoForge version of this mod.",
    "une passerelle": "a compatibility layer",
    "Mod {loader} chargé via {via} : {file}": "{loader} mod loaded through {via}: {file}",
    "Ce mod n'est pas conçu pour {loader}, mais {via} est présent dans le pack et sait en faire tourner beaucoup. Ce n'est pas garanti pour tous : si le jeu plante, ce mod est un suspect de choix.":
        "This mod is not built for {loader}, but {via} is in the pack and can run many of them. It is not guaranteed for all of them: if the game crashes, this mod is a prime suspect.",
    "{n} fichier(s) désactivé(s) ignoré(s)": "{n} disabled file(s) ignored",
    "Les fichiers .jar.disabled / .jar.old ne sont pas chargés par le jeu et ne sont pas analysés.":
        ".jar.disabled / .jar.old files are not loaded by the game and are not analysed.",
    "{n} jar dans des sous-dossiers ignoré(s)": "{n} jar(s) in subfolders ignored",
    "Seuls les .jar situés directement dans le dossier mods sont lus par ModMaestro (comme par la plupart des loaders).":
        "Only .jar files directly inside the mods folder are read by ModMaestro (as with most loaders).",
    # --- analyzer : doublons, dépendances, versions ---------------------------------------------------
    "Doublon : {name}": "Duplicate: {name}",
    "Même version présente en plusieurs fichiers (copie ?) : ": "Same version present in several files (a copy?): ",
    "Plusieurs versions du même mod sont installées — le jeu refuse de démarrer : ": "Several versions of the same mod are installed — the game refuses to start: ",
    "Garde {keep} (version la plus récente) et supprime : {removed}.": "Keep {keep} (most recent version) and delete: {removed}.",
    "Dépendance manquante : {name}": "Missing dependency: {name}",
    " et {n} autre(s)": " and {n} other(s)",
    " Version attendue : {ranges}.": " Expected version: {ranges}.",
    "Requise par {n} mod(s) : {shown}.{hint}": "Required by {n} mod(s): {shown}.{hint}",
    "Télécharge « {name} » ({target}) et place-le dans le dossier mods.": "Download “{name}” ({target}) and put it in the mods folder.",
    "Version incompatible : {name} {have}": "Incompatible version: {name} {have}",
    "{names} demande {ranges}, mais la version installée est {have}.": "{names} requires {ranges}, but the installed version is {have}.",
    "{names} demandent {ranges}, mais la version installée est {have}.": "{names} require {ranges}, but the installed version is {have}.",
    " (dépendance facultative : l'intégration sera simplement désactivée)": " (optional dependency: the integration will simply be disabled)",
    "Mets à jour « {name} » (ou le mod qui l'exige) pour que les versions concordent.": "Update “{name}” (or the mod that requires it) so the versions match.",
    # --- analyzer : incompatibilités et règles connues -------------------------------------------------
    " Raison donnée par l'auteur : {reason}": " Reason given by the author: {reason}",
    "{a} déclare être incompatible avec {b}.{why}": "{a} declares itself incompatible with {b}.{why}",
    "{a} déclare se marier mal avec {b}.{why}": "{a} declares it does not get along with {b}.{why}",
    "Retire l'un des deux mods (ou cherche une version qui les rend compatibles).": "Remove one of the two mods (or look for a version that makes them compatible).",
    " Présents : {found}.": " Present: {found}.",
    " (source : {src})": " (source: {src})",
    # --- analyzer : version de Minecraft ----------------------------------------------------------------
    "{n} mod ne vise pas Minecraft {mc}": "{n} mod does not target Minecraft {mc}",
    "{n} mods ne visent pas Minecraft {mc}": "{n} mods do not target Minecraft {mc}",
    "La majorité du pack ({pct} %) vise Minecraft {mc}, mais {shown}{more}. Si le pack démarre, c'est que la version déduite est fausse : ignore cette alerte.":
        "Most of the pack ({pct}%) targets Minecraft {mc}, but {shown}{more}. If the pack starts, the inferred version is wrong: ignore this alert.",
    "{name} (vise {wanted})": "{name} (targets {wanted})",
    " ou ": " or ",
    "Prends la version de ces mods pour Minecraft {mc}.": "Get the Minecraft {mc} version of these mods.",
    # --- builder ----------------------------------------------------------------------------------------
    "Le dossier de sortie ne doit pas être le dossier de mods (ni dedans, ni le contenir).": "The output folder must not be the mods folder (neither inside it nor containing it).",
    "« {path} » existe déjà et n'est pas vide. Choisis un autre nom : je ne mélange jamais mes fichiers avec les tiens.":
        "“{path}” already exists and is not empty. Pick another name: I never mix my files with yours.",
    "« {path} » existe déjà.": "“{path}” already exists.",
    # --- pipeline ---------------------------------------------------------------------------------------
    "Le dernier lancement a échoué": "The last launch failed",
    "{log} indique que le jeu n'a pas démarré.": "{log} shows that the game did not start.",
    "Ouvre « Journal de crash » pour le détail, ou « Trouver le mod fautif » pour isoler la cause.":
        "Open “Crash” for details, or use the trial-and-error search to isolate the cause.",
    "Causes repérées : {titles}.": "Causes spotted: {titles}.",
    # --- parser -----------------------------------------------------------------------------------------
    "Aucun fichier .jar trouvé ici. Choisis le dossier `mods` de ton modpack (ou la racine de l'instance qui le contient).":
        "No .jar file found here. Pick your modpack's `mods` folder (or the root of the instance that contains it).",
    "Aucune métadonnée de mod (bibliothèque, coremod ou format trop ancien).": "No mod metadata (library, coremod or format too old).",
    "environment = « {env} » dans fabric.mod.json": "environment = “{env}” in fabric.mod.json",
    "minecraft.environment = « {env} » dans quilt.mod.json": "minecraft.environment = “{env}” in quilt.mod.json",
    "Choisis un dossier de mods ou une archive .zip.": "Pick a mods folder or a .zip archive.",
    "{n} jar extraits de l'archive vers un dossier temporaire.": "{n} jar(s) extracted from the archive to a temporary folder.",
    "Seul un point d'entrée « client » est déclaré": "Only a “client” entrypoint is declared",
    "Dossier de mods détecté automatiquement : {rel}/": "Mods folder detected automatically: {rel}/",
    "Cette archive est corrompue ou n'est pas un zip valide.": "This archive is corrupted or is not a valid zip.",
    "Aucun dossier `mods/` contenant des .jar dans cette archive.": "No `mods/` folder containing .jar files in this archive.",
    "Archive zip invalide (téléchargement interrompu ou fichier abîmé).": "Invalid zip archive (interrupted download or damaged file).",
    "Lecture impossible : {exc}": "Cannot read: {exc}",
    "Un seul fichier .jar a été donné : analyse du dossier qui le contient.": "A single .jar file was given: analysing the folder that contains it.",
    "Ce zip ne contient que la liste des mods (manifest), pas les .jar eux-mêmes. Installe le modpack avec ton launcher, puis choisis le dossier `mods` de l'instance.":
        "This zip only contains the mod list (manifest), not the .jar files themselves. Install the modpack with your launcher, then pick the instance's `mods` folder.",
    "Déclaré côté client uniquement dans ses métadonnées": "Declared client-only in its metadata",
    "Déclaré côté serveur uniquement dans ses métadonnées": "Declared server-only in its metadata",
    # --- données : règles de conflit (core/data/knowledge.json et base communautaire) -------------------
    "Plusieurs optimiseurs de rendu": "Several rendering optimisers",
    "Sodium, Embeddium et Rubidium font le même travail : les charger ensemble provoque des conflits de mixins ou un crash au démarrage.":
        "Sodium, Embeddium and Rubidium do the same job: loading them together causes mixin conflicts or a crash on startup.",
    "Garde un seul de ces mods (Embeddium sur la plupart des packs Forge/NeoForge).": "Keep only one of these mods (Embeddium on most Forge/NeoForge packs).",
    "OptiFine mélangé à un mod de rendu moderne": "OptiFine mixed with a modern rendering mod",
    "OptiFine est connu pour être incompatible avec Sodium, Embeddium, Rubidium, Iris et Oculus.": "OptiFine is known to be incompatible with Sodium, Embeddium, Rubidium, Iris and Oculus.",
    "Retire OptiFine : Sodium/Embeddium + Iris/Oculus couvrent ses fonctions (performances et shaders).": "Remove OptiFine: Sodium/Embeddium + Iris/Oculus cover its features (performance and shaders).",
    "Deux moteurs de shaders": "Two shader engines",
    "Iris et Oculus (son équivalent Forge) ne doivent pas être présents ensemble.": "Iris and Oculus (its Forge equivalent) must not be installed together.",
    "Garde celui qui correspond à ton loader.": "Keep the one that matches your loader.",
    "Plusieurs variantes de Lithium": "Several Lithium variants",
    "Canary et Radium sont des ports/forks de Lithium : l'un des deux suffit.": "Canary and Radium are ports/forks of Lithium: one of them is enough.",
    "Garde une seule variante.": "Keep a single variant.",
    "Plusieurs visionneuses de recettes": "Several recipe viewers",
    "JEI, REI et EMI font le même travail. Ce n'est pas un bug, mais c'est redondant.": "JEI, REI and EMI do the same job. It is not a bug, but it is redundant.",
    "Garde celle que tu préfères.": "Keep the one you prefer.",
    "Plusieurs minimaps": "Several minimaps",
    "Plusieurs minimaps sont installées : elles se gênent à l'écran sans pour autant planter.": "Several minimaps are installed: they get in each other's way on screen without crashing.",
    "Garde-en une seule.": "Keep only one.",
    "Deux mods de lumière dynamique": "Two dynamic lighting mods",
    "LambDynamicLights et Sodium Dynamic Lights ajoutent la même fonction (les objets tenus éclairent autour du joueur).":
        "LambDynamicLights and Sodium Dynamic Lights add the same feature (held items light up the area around the player).",
    "Garde-en un seul.": "Keep only one.",
    "ModMaestro (entrée de départ)": "ModMaestro (starter entry)",
    "Deux moteurs d'éclairage": "Two lighting engines",
    "Starlight et Phosphor réécrivent tous deux le calcul de la lumière : ils font le même travail et se marchent dessus.":
        "Starlight and Phosphor both rewrite the light calculation: they do the same job and step on each other.",
    "Ne garde que l'un des deux.": "Keep only one of the two.",
}
