# Zestaw narzędzi do automatyzacji EPLAN z AI

[English](README.md) · [Español](README.es.md) · [Deutsch](README.de.md) · [中文](README.zh-CN.md) · [한국어](README.ko.md) · [Türkçe](README.tr.md) · **Polski** · [Русский](README.ru.md)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

Automatyzacja **EPLAN Electric P8** i **EPLAN EEC Pro 2026** wspierana przez AI, zbudowana na
Model Context Protocol (MCP).

📖 **Dokumentacja, instrukcja instalacji i pełny opis narzędzi: [covaga.dev](https://covaga.dev)** (po angielsku)

To repozytorium zawiera lokalny serwer MCP, który steruje uruchomioną instancją EPLAN. Trzy zdalne
RAG z dokumentacją znajdują się w osobnym repozytorium
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags).

> Pracujesz tu z LLM? Przeczytaj [`llm.md`](llm.md) — opisuje, językiem przeznaczonym dla LLM,
> wszystko, co zestaw potrafi i co można w nim skonfigurować.

## Struktura repozytorium

```
.
└── eplan-p8-mcp-server/          # LOKALNIE: serwer MCP sterujący EPLAN P8
```

| Komponent | Typ | Przeznaczenie | Produkt EPLAN |
|---|---|---|---|
| `eplan-p8-mcp-server/` | Lokalny MCP w Pythonie | Sterowanie uruchomionym EPLAN z poziomu Claude: otwieranie/zamykanie projektów, eksport, raporty, skrypty | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | Zdalne Cloudflare Workers, osobne repozytorium | Udostępnianie dokumentacji P8 2026, P8 2027 i EEC Pro przez MCP i REST | EPLAN Electric P8 i EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Umiejętność Claude Code, osobne repozytorium | Nauczenie Claude pisania poprawnych skryptów EPLAN, kodu API i aplikacji Remote Client | EPLAN Electric P8 |

Każde repozytorium ma własne README ze szczegółami instalacji i użycia.

## Czym jest MCP?

**MCP (Model Context Protocol)** to otwarty standard, który pozwala asystentom AI współpracować z
zewnętrznymi narzędziami i usługami. Zamiast tylko generować kod, Claude może w czasie rzeczywistym
*wykonywać* działania wewnątrz EPLAN i przeszukiwać dokumentację.

## Szybki start

### Lokalna automatyzacja EPLAN (P8)

```bash
pip install pythonnet mcp
claude mcp add eplan -- python TWOJA_SCIEZKA/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # powinien pojawić się "eplan"
```

Następnie uruchom EPLAN, otwórz Claude Code i powiedz `connect to eplan`. Pełny przewodnik znajduje
się w [`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md).

![Skonfigurowane Claude CLI](assets/claude-cli-configured.png)

#### Wymaganie wstępne

Zanim serwer się połączy, w EPLAN musi być włączony dostęp zdalny: włącz **Zezwalaj na dostęp
zdalny przez Remote Client** w **Plik → Ustawienia… → Stanowisko → Interfejsy → Dostęp zdalny**.

![Zezwalaj na dostęp zdalny przez Remote Client](assets/remoting-allow-local-access.png)

#### Co udostępnia serwer

W domyślnym trybie `full` serwer publikuje **199 narzędzi**:

| Grupa | Liczba | Zakres |
|---|---|---|
| Połączenie / narzędzia pomocnicze | 8 | Łączenie, wybór wersji, stan, lista rozszerzeń |
| Typowane akcje EPLAN (`eplan_*`) | 183 | Jedno narzędzie na każdą udokumentowaną lub zweryfikowaną akcję; każda wykonuje się po cichu w skrypcie C# w trybie QuietMode, więc żadne okno dialogowe EPLAN nie zablokuje pracy bez nadzoru |
| Katalog akcji (`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`) | 4 | Daje dostęp do kolejnych ~1050 akcji, które istnieją tylko jako przyciski interfejsu, wydobytych z pliku `MFTools.xml` instalacji, a nie z oficjalnej dokumentacji |
| Asset Administration Shell (`aas_*`) | 4 | Eksport i import cyfrowych bliźniaków AAS/AASX |

~1050 akcji z katalogu celowo *nie* dostało osobnych narzędzi-opakowań: potroiłoby to liczbę
narzędzi i pogorszyło wybór narzędzia dla całej reszty.

Wśród 183 typowanych narzędzi są cztery narzędzia żywego DataModel —
`eplan_live_query_functions`, `eplan_live_query_pages`, `eplan_live_set_function_text`
i `eplan_live_set_connection_designations` — które odczytują i edytują model obiektowy
otwartego projektu za pomocą refleksji w czasie działania, omijając ograniczenie silnika skryptów
dotyczące statycznych dyrektyw `using`.

Poza pojedynczymi akcjami zestaw obejmuje elementy w pełni bezobsługowej pętli
tworzenie → wdrożenie → test:

- **Cykl życia aplikacji** — `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`: zamknięcie EPLAN, podmiana DLL dodatków, ponowne uruchomienie, ponowne
  połączenie, ponowne otwarcie projektu.
- **Projekty jednorazowe** — `eplan_scratch_project_*`: tymczasowe projekty sklonowane z szablonu.
- **Diagnostyka** — `eplan_get_system_messages`: odczyt drzewa komunikatów EPLAN, czyli tych samych
  błędów i ostrzeżeń, które użytkownik widzi w interfejsie.
- **Prywatne moduły rozszerzeń** — zobacz [niżej](#prywatne-moduły-rozszerzeń-eplan_mcp_extensions).

Opis narzędzie po narzędziu, generowany z docstringów tego repozytorium, znajduje się na
[covaga.dev/docs/tools](https://covaga.dev/docs/tools/project-and-workspace-management/).

#### Tryb discovery

`EPLAN_MCP_MODE=discovery` publikuje 13 narzędzi zamiast 199, zamieniając kosztowną w tokenach
listę narzędzi na jedno dodatkowe wyszukiwanie na zadanie. Opłaca się to w klientach MCP, które
przy każdym żądaniu wysyłają pełny schemat wszystkich narzędzi.

**W Claude Code go nie używaj.** Claude Code sam odracza wczytywanie schematów narzędzi — najpierw
lista nazw, schemat dopiero na żądanie — więc lista `full` z 199 narzędziami kosztuje go mniej
więcej tyle samo co 13 narzędzi trybu `discovery`, a dodatkowy krok wyszukaj → opisz → wywołaj
dokłada tylko jeszcze jedno zapytanie. Kompromisy i pomiary są w
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode).

### Zdalne RAG z dokumentacją (P8, EEC Pro, 2027)

Już wdrożone i gotowe do użycia — bez lokalnych danych:

```bash
# Dokumentacja EPLAN Electric P8 (2026, wyszukiwanie semantyczne)
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# Dokumentacja EPLAN EEC Pro 2026
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# Dokumentacja EPLAN Electric P8 (2027, wyszukiwanie po słowach kluczowych / pełnotekstowe)
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027` to celowo osobny serwer, a nie aktualizacja `eplan-rag` z 2026 do 2027: indeksuje
inną wersję dokumentacji *i* używa innego sposobu wyszukiwania (dopasowanie słów kluczowych SQLite
FTS5/bm25 w wiki dołączonej do
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027)
zamiast wyszukiwania semantycznego Vectorize + bge). Porównane na prawdziwych zapytaniach mylą się
w różnych miejscach: FTS5 wygrywa przy dokładnych nazwach („jaka jest sygnatura X”), a wyszukiwanie
semantyczne, gdy zapytanie nie ma wspólnego słownictwa z dokumentacją. Zainstaluj oba.

Oba udostępniają też prosty interfejs REST, przydatny do sprawdzania nazw i parametrów akcji EPLAN
podczas pracy:

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

Narzędzia, punkty końcowe REST i architekturę opisują
[`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) i
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md).

### Wizualny RAG symboli (nowość)

Rozpoznawanie symboli elektrycznych EPLAN na obrazach: na wejściu symbol wycięty z PDF, schematu lub
zrzutu ekranu, na wyjściu prawdziwy `short_name`:

- Indeks: 33 502 obrazy symboli EPLAN (IEC/NFPA) osadzone modelem CLIP ViT-B/32 (512 wymiarów,
  kosinus) w Cloudflare Vectorize, na podstawie
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset).
- Publiczny punkt końcowy `https://symbols.covaga.xyz` (tak samo otwarty jak pozostałe RAG — bez
  danych logowania):

```bash
# vector = znormalizowane L2 osadzenie CLIP ViT-B/32 obrazu symbolu
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

Każde dopasowanie zawiera `short_name`, katalogowy `number`, `description` i `variant_id` oraz
wynik kosinusowy; `short_name` to identyfikator, którego oczekują wywołania API EPLAN. Ponowne
indeksowanie i wdrożenie odbywa się przez GitHub Actions w
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols).

#### Użycie z tego serwera MCP

Gotowe rozszerzenie znajduje się w
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py).
Po jego włączeniu agent dostaje narzędzie `eplan_symbol_search`:

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

Następnie, mając wycięty obraz symbolu, Claude wywołuje
`eplan_symbol_search(image_path="C:\\...\\crop.png")` → obraz jest lokalnie osadzany przez CLIP →
`symbols.covaga.xyz` zwraca kandydatów takich jak `F1 (no. 50, variant B) — Fuse, single-pole` →
najlepszy `short_name` trafia do wywołań API EPLAN. Token Cloudflare nie jest potrzebny: powiązanie
z indeksem ma Worker.

### Umiejętność Claude Code do programowania EPLAN

Serwery MCP pozwalają Claude *działać* w EPLAN. Umiejętność
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) uczy go *pisać
poprawny kod EPLAN*: punkty wejścia skryptów, zweryfikowane parametry akcji, dostęp do bazy części,
automatyzacja przez Remote Client (dynamiczne porty, EPLAN bez interfejsu, Cogineer) oraz pułapki
z produkcji — pseudoasynchroniczne blokowanie poleceń, wątek monitorujący pętlę komunikatów,
dyscyplina dispose, zmiany w zdalnym dostępie w EPLAN 2025.

Umiejętność ma własne repozytorium i jest celowo **niezależna od środowiska**: nie zakłada żadnego
serwera MCP, konkretnego uruchamiacza skryptów ani konkretnego indeksu dokumentacji, więc przydaje
się sama, niezależnie od tego, czy używasz czegoś innego stąd.

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # router + wszystkie umiejętności + RAG z dokumentacją
/plugin install eplan-scripting@eplan-tools  # tylko Electric P8
/plugin install eec-pro@eplan-tools          # tylko EEC Pro
```

Instalacja ręczna i szczegóły:
[README umiejętności](https://github.com/Canary-ECAD/eplan-scripting-skill#readme).

## Dodawanie nowych akcji EPLAN

Lokalny serwer MCP rejestruje narzędzia **dynamicznie** z listy `__all__` każdego pakietu akcji,
więc dodanie akcji to dwa kroki bez szablonowego kodu dla każdego narzędzia.

### 1. Zaimplementuj akcję

W `eplan-p8-mcp-server/mcp_server/api/actions/<twoj_modul>.py`:

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

### 2. Wyeksportuj ją

Dodaj funkcję do importów **i** do `__all__` w
`eplan-p8-mcp-server/mcp_server/api/actions/__init__.py`. Zostanie wtedy automatycznie
zarejestrowana jako `eplan_open_project`.

### 3. Uruchom ponownie serwer MCP

Nowe narzędzie będzie dostępne po ponownym uruchomieniu Claude lub serwera.

### 4. Sprawdź z oficjalną dokumentacją (opcjonalnie)

`eplan-p8-mcp-server/tools/validate_actions.py` porównuje każdą nazwę akcji i każdy parametr
zadeklarowany w opakowaniach z RAG oficjalnej dokumentacji EPLAN i zapisuje raport w markdown:

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![Test EPLAN](assets/eplan-test.png)

### Wskazówki

1. **Sprawdzaj w dokumentacji.** Użyj zdalnego RAG dla P8 (`https://rag2026.covaga.xyz`), aby
   potwierdzić dokładną nazwę akcji EPLAN i jej parametry.
2. **Pisz sensowne docstringi i adnotacje typów.** Stają się opisem narzędzia i schematem wejścia,
   które LLM widzi i na których polega.
3. **Uważaj na ścieżki.** Ścieżki Windows wymagają escape'owania (`\\`) lub ukośników (`/`).

## Prywatne moduły rozszerzeń (`EPLAN_MCP_EXTENSIONS`)

Serwer może wczytywać **dodatkowe moduły narzędzi spoza tego repozytorium** — narzędzia firmowe lub
prywatne (stanowiska testowe dla własnych dodatków, wewnętrzne procesy), które nie powinny trafić do
publicznego repozytorium.

Ustaw zmienną środowiskową `EPLAN_MCP_EXTENSIONS` na jeden lub kilka katalogów (w Windows
rozdzielonych `;`). Każdy plik `*.py` najwyższego poziomu, którego nazwa nie zaczyna się od `_`, jest
importowany przy starcie, a funkcje z jego `__all__` są rejestrowane jako narzędzia MCP dokładnie
tak jak wbudowane akcje:

```python
# my_company_tools.py  (w prywatnym repozytorium, NIE w eplan-mcp)
TOOL_PREFIX = "acme_"          # opcjonalnie, domyślnie "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # folder api/ serwera jest w sys.path
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

Zasady i działanie:

- `TOOL_PREFIX` nadaje narzędziom przestrzeń nazw (`acme_run_smoke_test` powyżej).
- Rozszerzenia mogą importować wszystko, czego używają wbudowane akcje: `actions`, `actions._base`,
  `actions.scripted._execute_script` (uruchamianie C# w EPLAN), `eplan_connection`.
- Uszkodzone rozszerzenie jest zgłaszane na stderr i pomijane; nigdy nie blokuje startu serwera.
- `eplan_list_extensions` pokazuje, co zostało wczytane.

W połączeniu z narzędziami cyklu życia i projektów jednorazowych daje to w pełni bezobsługową pętlę
tworzenia prywatnych dodatków EPLAN: zbuduj DLL → wdróż → `eplan_app_restart` → sprawdź, czy akcje
dodatku się zarejestrowały (np. skryptem `FindAction`) → uruchom je na projekcie jednorazowym →
`eplan_get_system_messages`, aby wychwycić wszystko, na co poskarżył się EPLAN.

## Wybór wersji EPLAN (automatyczny)

**Nie trzeba nic konfigurować.** Przy starcie serwer przeszukuje `C:\Program Files\EPLAN\Platform`
w poszukiwaniu zainstalowanych wersji i:

- **Tryb automatyczny (domyślny):** `eplan_connect` łączy się z **najnowszą zainstalowaną wersją** i
  sam wybiera odpowiednie środowisko .NET — coreclr dla EPLAN 2027+, .NET Framework dla 2026 i
  starszych.
- **Tryb jawny:** LLM może wywołać `eplan_versions`, aby wyświetlić zainstalowane wersje, a potem
  połączyć się z wybraną przez `eplan_connect(version="2026")` — np. „connect to eplan 2026”.

Uwagi:

- EPLAN zainstalowany w niestandardowym miejscu? Ustaw `EPLAN_PLATFORM_ROOT` na jego folder `Platform`.
- Gdy DLL jednej wersji zostaną wczytane do procesu, zmiana wersji wymaga ponownego uruchomienia
  serwera MCP — środowiska .NET nie da się podmienić w trakcie działania.
- `eplan_connect` przyjmuje też `host` (oraz `"host:port"`), aby połączyć się z EPLAN na innym
  komputerze; automatyczne wykrywanie portu działa tylko na localhost.

## Powiązane repozytoria

| Repozytorium | Co to jest |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Opisana wyżej umiejętność Claude Code, samodzielna i niezależna od środowiska. Instalacja: `/plugin marketplace add Canary-ECAD/eplan-mcp`. |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | Dodawanie własnych pozycji do menu kontekstowych EPLAN i odczyt wiersza klikniętego przez użytkownika. Narzędzie do eksploracji i kompletny przykład. |

## Zasoby

- [Dokumentacja API EPLAN](https://www.eplan.help/)
- [Specyfikacja protokołu MCP](https://modelcontextprotocol.io/)
- [Dokumentacja Claude Code](https://docs.anthropic.com/claude-code)

## Licencja

MIT — zobacz [`LICENSE`](LICENSE).

> **Zastrzeżenie:** to niezależny projekt społecznościowy [Canary E-cad](https://github.com/Canary-ECAD). Nie jest powiązany z EPLAN GmbH & Co. KG ani przez nią zatwierdzony czy wspierany. EPLAN, EPLAN Electric P8 i EPLAN EEC Pro są znakami towarowymi ich właściciela.
