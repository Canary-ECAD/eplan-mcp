# EPLAN-KI-Automatisierungs-Toolkit

[English](README.md) · [Español](README.es.md) · **Deutsch** · [中文](README.zh-CN.md) · [한국어](README.ko.md) · [Türkçe](README.tr.md) · [Polski](README.pl.md) · [Русский](README.ru.md)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

KI-gestützte Automatisierung für **EPLAN Electric P8** und **EPLAN EEC Pro 2026**, aufgebaut
auf dem Model Context Protocol (MCP).

📖 **Dokumentation, Installationsanleitung und vollständige Tool-Referenz: [covaga.dev](https://covaga.dev/de/)**

Dieses Repository enthält den lokalen MCP-Server, der eine laufende EPLAN-Instanz steuert.
Die drei entfernten Dokumentations-RAGs liegen im separaten Repository
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags).

> Arbeitest du hier mit einem LLM? Lies [`llm.md`](llm.md) – dort steht, für ein LLM
> formuliert, alles, was das Toolkit kann und was sich konfigurieren lässt.

## Repository-Struktur

```
.
└── eplan-p8-mcp-server/          # LOKAL: MCP-Server, der EPLAN P8 steuert
```

| Komponente | Typ | Zweck | EPLAN-Produkt |
|---|---|---|---|
| `eplan-p8-mcp-server/` | Lokaler Python-MCP | Eine laufende EPLAN-Instanz aus Claude steuern: Projekte öffnen/schließen, Exporte, Berichte, Skripte | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | Entfernte Cloudflare Workers, separates Repository | Die Dokumentation zu P8 2026, P8 2027 und EEC Pro über MCP und REST bereitstellen | EPLAN Electric P8 und EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Claude-Code-Skill, separates Repository | Claude beibringen, korrekte EPLAN-Skripte, API-Code und Remote-Client-Apps zu schreiben | EPLAN Electric P8 |

Jedes Repository hat ein eigenes README mit Installations- und Nutzungsdetails.

## Was ist MCP?

**MCP (Model Context Protocol)** ist ein offener Standard, mit dem KI-Assistenten mit externen
Werkzeugen und Diensten arbeiten können. Statt nur Code zu erzeugen, kann Claude Aktionen in
EPLAN in Echtzeit *ausführen* und die Dokumentation per Suche befragen.

## Schnellstart

### Lokale EPLAN-Automatisierung (P8)

```bash
pip install pythonnet mcp
claude mcp add eplan -- python DEIN_PFAD/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # sollte "eplan" anzeigen
```

Starte dann EPLAN, öffne Claude Code und sag `connect to eplan`. Die vollständige Anleitung
steht in [`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md).

![Claude CLI eingerichtet](assets/claude-cli-configured.png)

#### Voraussetzung

Der Fernzugriff muss in EPLAN aktiviert sein, bevor sich der Server verbinden kann: Schalte
**Fernzugriff über Remote Client erlauben** unter **Datei → Einstellungen… → Arbeitsplatz →
Schnittstellen → Fernzugriff** ein.

![Fernzugriff über Remote Client erlauben](assets/remoting-allow-local-access.png)

#### Was der Server bereitstellt

Im Standardmodus `full` veröffentlicht der Server **199 Tools**:

| Gruppe | Anzahl | Was sie abdeckt |
|---|---|---|
| Verbindung / Hilfsfunktionen | 8 | Verbinden, Versionswahl, Status, Erweiterungen auflisten |
| Typisierte EPLAN-Aktionen (`eplan_*`) | 183 | Ein Tool pro dokumentierter oder verifizierter Aktion; jede läuft still in einem C#-Skript im QuietMode, sodass kein EPLAN-Dialog einen unbeaufsichtigten Lauf blockieren kann |
| Aktionskatalog (`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`) | 4 | Erreicht weitere ~1.050 Aktionen, die nur als GUI-Schaltflächen existieren – gewonnen aus der `MFTools.xml` der Installation, nicht aus der offiziellen Doku |
| Asset Administration Shell (`aas_*`) | 4 | Export und Import digitaler Zwillinge im AAS/AASX-Format |

Die ~1.050 Katalogaktionen bekommen bewusst *kein* eigenes Wrapper-Tool: Das hätte die Zahl
der Tools verdreifacht und die Tool-Auswahl für alles andere verschlechtert.

Unter den 183 typisierten Tools sind vier Live-DataModel-Tools –
`eplan_live_query_functions`, `eplan_live_query_pages`, `eplan_live_set_function_text`
und `eplan_live_set_connection_designations` –, die das Objektmodell des geöffneten Projekts
per Laufzeit-Reflection lesen und bearbeiten und so die Einschränkung der Skript-Engine bei
statischen `using`-Direktiven umgehen.

Über einzelne Aktionen hinaus deckt das Toolset die Bausteine einer vollständig
unbeaufsichtigten Schleife Entwickeln → Bereitstellen → Testen ab:

- **Anwendungslebenszyklus** – `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`: EPLAN beenden, Add-in-DLLs tauschen, neu starten, neu verbinden, Projekt wieder öffnen.
- **Wegwerf-Fixtures** – `eplan_scratch_project_*`: Testprojekte, aus einer Vorlage geklont.
- **Diagnose** – `eplan_get_system_messages`: den Meldungsbaum von EPLAN lesen und dieselben
  Fehler und Warnungen sehen wie der Benutzer in der Oberfläche.
- **Private Erweiterungsmodule** – siehe [unten](#private-erweiterungsmodule-eplan_mcp_extensions).

Eine Referenz Tool für Tool, erzeugt aus den Docstrings dieses Repositorys, gibt es unter
[covaga.dev/docs/tools](https://covaga.dev/de/docs/tools/project-and-workspace-management/).

#### Discovery-Modus

`EPLAN_MCP_MODE=discovery` veröffentlicht 13 statt 199 Tools und tauscht damit eine
tokenintensive Tool-Liste gegen einen zusätzlichen Suchschritt pro Aufgabe. Das lohnt sich bei
MCP-Clients, die bei jeder Anfrage das vollständige Schema aller Tools mitschicken.

**In Claude Code nicht verwenden.** Claude Code lädt Tool-Schemas bereits selbst verzögert –
zuerst eine Namensliste, das Schema erst bei Bedarf –, daher kostet die `full`-Liste mit 199
Tools dort ungefähr so wenig wie die 13 von `discovery`, und die zusätzliche Umleitung Suchen →
Beschreiben → Aufrufen bringt nur einen weiteren Roundtrip. Abwägung und Messungen stehen in
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode).

### Entfernte Dokumentations-RAGs (P8, EEC Pro, 2027)

Bereits bereitgestellt und sofort nutzbar – keine lokalen Daten nötig:

```bash
# Dokumentation zu EPLAN Electric P8 (2026, semantische Suche)
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# Dokumentation zu EPLAN EEC Pro 2026
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# Dokumentation zu EPLAN Electric P8 (2027, Schlagwort-/Volltextsuche)
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027` ist bewusst ein eigener Server und kein Upgrade von `eplan-rag` von 2026 auf
2027: Er indexiert eine andere Dokumentationsversion *und* nutzt eine andere Suchart
(Schlagwortsuche mit SQLite FTS5/bm25 über das mitgelieferte Wiki in
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027)
statt semantischer Suche mit Vectorize + bge). Im direkten Vergleich mit echten Anfragen
scheitern sie an unterschiedlichen Stellen: FTS5 gewinnt bei exakten Namen („Welche Signatur hat
X?“), die semantische Suche, wenn die Anfrage keine Begriffe mit der Doku teilt. Installiere beide.

Beide bieten außerdem eine einfache REST-API, praktisch, um beim Entwickeln Namen und Parameter
von EPLAN-Aktionen zu prüfen:

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

Tools, REST-Endpunkte und Architektur sind in
[`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) und
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md) beschrieben.

### Visuelles Symbol-RAG (neu)

EPLAN-Elektrosymbole aus Bildern erkennen: Ein ausgeschnittenes Symbol aus einem PDF, Schaltplan
oder Screenshot rein, der echte `short_name` raus:

- Index: 33.502 EPLAN-Symbolbilder (IEC/NFPA), mit CLIP ViT-B/32 eingebettet (512 Dimensionen,
  Kosinus) in Cloudflare Vectorize, aus
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset).
- Öffentlicher Endpunkt `https://symbols.covaga.xyz` (gleiches offenes Muster wie die anderen
  RAGs – keine Zugangsdaten):

```bash
# vector = L2-normalisiertes CLIP-ViT-B/32-Embedding des Symbolbilds
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

Jeder Treffer enthält `short_name`, die Katalog-`number`, `description` und `variant_id` sowie
einen Kosinus-Score – der `short_name` ist der Bezeichner, den Aufrufe der EPLAN-API erwarten.
Neuindexierung und erneutes Deployment laufen über GitHub Actions in
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols).

#### Nutzung aus diesem MCP-Server

Eine fertige Erweiterung liegt in
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py).
Aktiviere sie, und der Agent bekommt das Tool `eplan_symbol_search`:

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

Mit einem ausgeschnittenen Symbolbild ruft Claude dann
`eplan_symbol_search(image_path="C:\\...\\crop.png")` auf → das Bild wird lokal mit CLIP
eingebettet → `symbols.covaga.xyz` liefert Kandidaten wie
`F1 (no. 50, variant B) — Fuse, single-pole` → den besten `short_name` in EPLAN-API-Aufrufen
verwenden. Kein Cloudflare-Token nötig: Der Worker hält das Index-Binding.

### Claude-Code-Skill für die EPLAN-Entwicklung

Die MCP-Server lassen Claude in EPLAN *handeln*. Der Skill
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) bringt ihm bei,
*korrekten EPLAN-Code zu schreiben*: Skript-Einstiegspunkte, verifizierte Aktionsparameter,
Zugriff auf die Artikeldatenbank, Remote-Client-Automatisierung (dynamische Ports, EPLAN ohne
Oberfläche, Cogineer) und die Fallstricke im Betrieb – pseudoasynchron blockierende Befehle,
der Monitor-Thread der Message-Loop, saubere Dispose-Disziplin, die Remoting-Änderungen in EPLAN 2025.

Der Skill liegt in einem eigenen Repository und ist bewusst **hostunabhängig**: Er setzt keinen
MCP-Server, keinen bestimmten Skript-Runner und keinen bestimmten Dokumentationsindex voraus und
ist daher auch allein nützlich, egal ob du sonst etwas von hier verwendest.

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # Router + P8-Skill + P8-Doku-RAGs
/plugin install eplan-scripting@eplan-tools  # nur Electric P8
/plugin install eec-pro@eplan-tools          # nur EEC Pro
```

Manuelle Installation und Details:
[das README des Skills](https://github.com/Canary-ECAD/eplan-scripting-skill#readme).

## Neue EPLAN-Aktionen hinzufügen

Der lokale MCP-Server registriert Tools **dynamisch** aus der `__all__`-Liste jedes
Aktionspakets. Eine Aktion hinzuzufügen braucht daher zwei Schritte und keinen Boilerplate-Code pro Tool.

### 1. Aktion implementieren

In `eplan-p8-mcp-server/mcp_server/api/actions/<dein_modul>.py`:

```python
def open_project(project_path: str, open_mode: str = None) -> dict:
    """Open a project in EPLAN.

    Args:
        project_path: Full path to the .elk project file.
        open_mode: "Standard", "ReadOnly", or "Exclusive" (optional).
    """
    manager, error = _get_connected_manager()
    if error:
        return error
    action = _build_action("ProjectOpen", Project=project_path, OpenMode=open_mode)
    return manager.execute_action(action)
```

### 2. Exportieren

Füge die Funktion zu den Imports **und** zu `__all__` in
`eplan-p8-mcp-server/mcp_server/api/actions/__init__.py` hinzu. Sie wird dann automatisch als
`eplan_open_project` registriert.

### 3. MCP-Server neu starten

Das neue Tool steht zur Verfügung, sobald Claude bzw. der Server neu gestartet ist.

### 4. Gegen die offizielle Doku prüfen (optional)

`eplan-p8-mcp-server/tools/validate_actions.py` gleicht jeden in den Wrappern deklarierten
Aktionsnamen und Parameter mit dem RAG der offiziellen EPLAN-Doku ab und schreibt einen
Markdown-Bericht:

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![EPLAN-Test](assets/eplan-test.png)

### Tipps

1. **Mit der Doku abgleichen.** Nutze das entfernte P8-RAG (`https://rag2026.covaga.xyz`), um
   den genauen Namen der EPLAN-Aktion und ihre Parameter zu bestätigen.
2. **Aussagekräftige Docstrings und Typangaben schreiben.** Sie werden zur Tool-Beschreibung und
   zum Eingabeschema, die das LLM sieht und auf die es sich verlässt.
3. **Vorsicht mit Pfaden.** Windows-Pfade brauchen Escaping (`\\`) oder Schrägstriche (`/`).

## Private Erweiterungsmodule (`EPLAN_MCP_EXTENSIONS`)

Der Server kann **zusätzliche Tool-Module von außerhalb dieses Repositorys** laden –
firmenspezifische oder private Werkzeuge (Testumgebungen für eigene Add-ins, interne Abläufe),
die nicht in ein öffentliches Repository gehören.

Setze die Umgebungsvariable `EPLAN_MCP_EXTENSIONS` auf ein oder mehrere Verzeichnisse (unter
Windows durch `;` getrennt). Jede `*.py`-Datei auf oberster Ebene, die nicht mit `_` beginnt,
wird beim Start importiert, und ihre `__all__`-Funktionen werden genau wie die eingebauten
Aktionen als MCP-Tools registriert:

```python
# my_company_tools.py  (in einem privaten Repo, NICHT in eplan-mcp)
TOOL_PREFIX = "acme_"          # optional, Standard "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # der api/-Ordner des Servers liegt im sys.path
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

Regeln und Verhalten:

- `TOOL_PREFIX` gibt den Tools einen Namensraum (`acme_run_smoke_test` oben).
- Erweiterungen dürfen alles importieren, was die eingebauten Aktionen nutzen: `actions`,
  `actions._base`, `actions.scripted._execute_script` (C# in EPLAN ausführen), `eplan_connection`.
- Eine fehlerhafte Erweiterung wird auf stderr gemeldet und übersprungen; sie verhindert nie den
  Start des Servers.
- `eplan_list_extensions` zeigt, was geladen wurde.

Zusammen mit den Lebenszyklus- und Wegwerfprojekt-Tools ermöglicht das eine vollständig
unbeaufsichtigte Schleife für die Entwicklung privater EPLAN-Add-ins: DLL bauen → bereitstellen →
`eplan_app_restart` → prüfen, ob die Aktionen des Add-ins registriert sind (z. B. per
`FindAction`-Skript) → sie gegen ein Wegwerfprojekt ausführen → `eplan_get_system_messages`,
um alles abzufangen, was EPLAN beanstandet.

## Auswahl der EPLAN-Version (automatisch)

Es gibt **nichts zu konfigurieren**. Beim Start durchsucht der Server
`C:\Program Files\EPLAN\Platform` nach installierten Versionen und:

- **Automatikmodus (Standard):** `eplan_connect` nimmt die **neueste installierte Version** und
  wählt automatisch die passende .NET-Laufzeit – coreclr für EPLAN 2027+, .NET Framework für 2026
  und älter.
- **Expliziter Modus:** Das LLM kann `eplan_versions` aufrufen, um die installierten Versionen
  aufzulisten, und sich dann mit `eplan_connect(version="2026")` mit einer bestimmten verbinden –
  z. B. „connect to eplan 2026“.

Hinweise:

- EPLAN an einem nicht standardmäßigen Ort installiert? Setze `EPLAN_PLATFORM_ROOT` auf dessen
  `Platform`-Ordner.
- Sind die DLLs einer Version einmal im Prozess geladen, erfordert ein Versionswechsel einen
  Neustart des MCP-Servers – eine .NET-Laufzeit lässt sich zur Laufzeit nicht austauschen.
- `eplan_connect` akzeptiert auch einen `host` (und `"host:port"`), um eine EPLAN-Instanz auf
  einem anderen Rechner zu erreichen; die automatische Port-Erkennung funktioniert nur auf localhost.

## Verwandte Repositories

| Repository | Was es ist |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Der Claude-Code-Skill von oben, eigenständig und hostunabhängig. Installation mit `/plugin marketplace add Canary-ECAD/eplan-mcp`. |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | Eigene Einträge in EPLANs Kontextmenüs hinzufügen und die vom Benutzer angeklickte Zeile lesen. Ein Erkundungswerkzeug plus ein ausgearbeitetes Beispiel. |

## Ressourcen

- [EPLAN-API-Dokumentation](https://www.eplan.help/)
- [Spezifikation des MCP-Protokolls](https://modelcontextprotocol.io/)
- [Claude-Code-Dokumentation](https://docs.anthropic.com/claude-code)

## Lizenz

MIT – siehe [`LICENSE`](LICENSE).

> **Hinweis:** Dies ist ein unabhängiges Community-Projekt von [Canary E-cad](https://github.com/Canary-ECAD). Es steht in keiner Verbindung zur EPLAN GmbH & Co. KG und wird von ihr weder unterstützt noch empfohlen. EPLAN, EPLAN Electric P8 und EPLAN EEC Pro sind Marken ihres jeweiligen Inhabers.
