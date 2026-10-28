# EPLAN AI Automation Toolkit

[English](README.md) · [Español](README.es.md) · [Deutsch](README.de.md) · [中文](README.zh-CN.md) · [한국어](README.ko.md) · [Türkçe](README.tr.md) · [Polski](README.pl.md) · **Русский**

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

Автоматизация **EPLAN Electric P8** и **EPLAN EEC Pro 2026** с помощью ИИ на основе Model
Context Protocol (MCP).

📖 **Документация, руководство по установке и полный справочник инструментов: [covaga.dev](https://covaga.dev/ru/)**

В этом репозитории находится локальный MCP-сервер, который управляет запущенным экземпляром
EPLAN. Три удалённых RAG по документации находятся в отдельном репозитории
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags).

> Работаете здесь с LLM? Прочитайте [`llm.md`](llm.md) — там на языке, понятном LLM, описано
> всё, что умеет и что позволяет настроить этот набор инструментов.

## Структура репозитория

```
.
└── eplan-p8-mcp-server/          # ЛОКАЛЬНО: MCP-сервер, управляющий EPLAN P8
```

| Компонент | Тип | Назначение | Продукт EPLAN |
|---|---|---|---|
| `eplan-p8-mcp-server/` | Локальный MCP на Python | Управлять запущенным EPLAN из Claude: открывать/закрывать проекты, экспорт, отчёты, скрипты | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | Удалённые Cloudflare Workers, отдельный репозиторий | Предоставлять документацию P8 2026, P8 2027 и EEC Pro через MCP и REST | EPLAN Electric P8 и EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Навык Claude Code, отдельный репозиторий | Научить Claude писать корректные скрипты EPLAN, код API и приложения Remote Client | EPLAN Electric P8 |

В каждом репозитории есть свой README с инструкциями по установке и использованию.

## Что такое MCP?

**MCP (Model Context Protocol)** — открытый стандарт, позволяющий ИИ-ассистентам работать с
внешними инструментами и сервисами. Claude не просто генерирует код, а может *выполнять* действия
внутри EPLAN в реальном времени и обращаться к документации через поиск.

## Быстрый старт

### Локальная автоматизация EPLAN (P8)

```bash
pip install pythonnet "mcp<2"
claude mcp add eplan -- python ВАШ_ПУТЬ/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # в списке должен быть "eplan"
```

Затем запустите EPLAN, откройте Claude Code и скажите `connect to eplan`. Полное руководство —
в [`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md).

![Настроенный Claude CLI](assets/claude-cli-configured.png)

#### Предварительное условие

Чтобы сервер мог подключиться, в EPLAN нужно включить удалённый доступ: включите **Разрешить
удалённый доступ через Remote Client** в **Файл → Настройки… → Рабочее место → Интерфейсы →
Удалённый доступ**.

![Разрешить удалённый доступ через Remote Client](assets/remoting-allow-local-access.png)

#### Что предоставляет сервер

В режиме по умолчанию `full` сервер публикует **199 инструментов**:

| Группа | Количество | Что охватывает |
|---|---|---|
| Подключение / служебные | 8 | Подключение, выбор версии, статус, список расширений |
| Типизированные действия EPLAN (`eplan_*`) | 183 | По инструменту на каждое документированное или проверенное действие; каждое выполняется без вывода окон внутри скрипта C# в QuietMode, поэтому ни один диалог EPLAN не заблокирует автоматический запуск |
| Каталог действий (`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`) | 4 | Даёт доступ ещё к ~1050 действиям, которые существуют только как кнопки интерфейса; они извлечены из `MFTools.xml` установки, а не из официальной документации |
| Asset Administration Shell (`aas_*`) | 4 | Экспорт и импорт цифровых двойников AAS/AASX |

~1050 действий каталога намеренно *не* получили по отдельному инструменту-обёртке: это утроило бы
число инструментов и ухудшило бы выбор инструмента для всего остального.

Среди 183 типизированных инструментов есть четыре для живой DataModel —
`eplan_live_query_functions`, `eplan_live_query_pages`, `eplan_live_set_function_text`
и `eplan_live_set_connection_designations`. Они читают и изменяют объектную модель открытого
проекта через рефлексию во время выполнения, обходя ограничение движка скриптов на статические
директивы `using`.

Помимо отдельных действий, набор покрывает составные части полностью автоматического цикла
разработка → развёртывание → тестирование:

- **Жизненный цикл приложения** — `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`: закрыть EPLAN, заменить DLL надстроек, перезапустить, переподключиться и
  заново открыть проект.
- **Одноразовые проекты** — `eplan_scratch_project_*`: временные проекты, клонированные из шаблона.
- **Диагностика** — `eplan_get_system_messages`: читать дерево сообщений EPLAN и видеть те же
  ошибки и предупреждения, что пользователь видит в интерфейсе.
- **Приватные модули расширений** — см. [ниже](#приватные-модули-расширений-eplan_mcp_extensions).

Справочник по каждому инструменту, сгенерированный из docstring этого репозитория, находится на
[covaga.dev/docs/tools](https://covaga.dev/ru/docs/tools/project-and-workspace-management/).

#### Режим discovery

`EPLAN_MCP_MODE=discovery` публикует 13 инструментов вместо 199, меняя затратный по токенам
список инструментов на один дополнительный поисковый запрос на задачу. Это оправдано для
MCP-клиентов, которые в каждом запросе отправляют полную схему всех инструментов.

**В Claude Code он не нужен.** Claude Code уже сам откладывает загрузку схем: сначала список
имён, схема — по требованию. Поэтому полный список из 199 инструментов обходится ему почти так
же дёшево, как 13 инструментов `discovery`, а дополнительная цепочка поиск → описание → вызов
лишь добавляет ещё один запрос. Компромиссы и замеры — в
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode).

### Удалённые RAG по документации (P8, EEC Pro, 2027)

Уже развёрнуты и готовы к работе — локальные данные не нужны:

```bash
# Документация EPLAN Electric P8 (2026, семантический поиск)
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# Документация EPLAN EEC Pro 2026
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# Документация EPLAN Electric P8 (2027, поиск по ключевым словам / полнотекстовый)
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027` намеренно сделан отдельным сервером, а не обновлением `eplan-rag` с 2026 до
2027: он индексирует другую версию документации *и* использует другой способ поиска
(поиск по ключевым словам SQLite FTS5/bm25 по вики из
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027)
вместо семантического поиска Vectorize + bge). При прямом сравнении на реальных запросах они
ошибаются по-разному: FTS5 лучше находит точные имена («какая сигнатура у X»), а семантический
поиск выигрывает, когда в запросе нет общих слов с документацией. Установите оба.

Оба также предоставляют простой REST API — удобно для проверки имён и параметров действий EPLAN
во время разработки:

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

Инструменты, REST-эндпоинты и архитектура описаны в
[`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) и
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md).

### Визуальный RAG символов (новое)

Распознавание электрических символов EPLAN по изображениям: на входе — символ, вырезанный из PDF,
схемы или скриншота, на выходе — настоящий `short_name`:

- Индекс: 33 502 изображения символов EPLAN (IEC/NFPA), встроенные с помощью CLIP ViT-B/32
  (512 измерений, косинус) в Cloudflare Vectorize, из
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset).
- Публичный эндпоинт `https://symbols.covaga.xyz` (такой же открытый, как другие RAG, — без
  учётных данных):

```bash
# vector = L2-нормализованный эмбеддинг CLIP ViT-B/32 изображения символа
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

Каждое совпадение содержит `short_name`, `number` из каталога, `description` и `variant_id`, а
также косинусную оценку; `short_name` — это идентификатор, который ожидают вызовы API EPLAN.
Переиндексация и повторное развёртывание выполняются через GitHub Actions в
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols).

#### Использование из этого MCP-сервера

Готовое расширение лежит в
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py).
Включите его, и у агента появится инструмент `eplan_symbol_search`:

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

Затем, получив вырезанное изображение символа, Claude вызывает
`eplan_symbol_search(image_path="C:\\...\\crop.png")` → изображение локально превращается в
эмбеддинг с помощью CLIP → `symbols.covaga.xyz` возвращает кандидатов вроде
`F1 (no. 50, variant B) — Fuse, single-pole` → лучший `short_name` используется в вызовах API
EPLAN. Токен Cloudflare не нужен: привязка к индексу хранится в Worker.

### Навык Claude Code для разработки под EPLAN

MCP-серверы позволяют Claude *действовать* в EPLAN. Навык
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) учит его *писать
правильный код для EPLAN*: точки входа скриптов, проверенные параметры действий, доступ к базе
изделий, автоматизация через Remote Client (динамические порты, EPLAN без интерфейса, Cogineer) и
подводные камни реальной работы — псевдоасинхронная блокировка команд, поток-монитор цикла
сообщений, дисциплина dispose, изменения remoting в EPLAN 2025.

Навык живёт в отдельном репозитории и намеренно **не привязан к окружению**: он не предполагает
ни MCP-сервера, ни конкретного исполнителя скриптов, ни конкретного индекса документации, поэтому
полезен сам по себе, независимо от того, используете ли вы что-то ещё отсюда.

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # роутер + навык P8 + RAG документации P8
/plugin install eplan-scripting@eplan-tools  # только Electric P8
/plugin install eec-pro@eplan-tools          # только EEC Pro
```

Ручная установка и подробности:
[README навыка](https://github.com/Canary-ECAD/eplan-scripting-skill#readme).

## Добавление новых действий EPLAN

Локальный MCP-сервер регистрирует инструменты **динамически** из списка `__all__` каждого пакета
действий, поэтому добавление действия занимает два шага и не требует шаблонного кода для каждого
инструмента.

### 1. Реализуйте действие

В `eplan-p8-mcp-server/mcp_server/api/actions/<ваш_модуль>.py`:

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

### 2. Экспортируйте её

Добавьте функцию в импорты **и** в `__all__` в
`eplan-p8-mcp-server/mcp_server/api/actions/__init__.py`. После этого она автоматически
зарегистрируется как `eplan_open_project`.

### 3. Перезапустите MCP-сервер

Новый инструмент станет доступен после перезапуска Claude или сервера.

### 4. Сверьтесь с официальной документацией (необязательно)

`eplan-p8-mcp-server/tools/validate_actions.py` сверяет каждое имя действия и параметр,
объявленные в обёртках, с RAG официальной документации EPLAN и формирует отчёт в markdown:

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![Тест EPLAN](assets/eplan-test.png)

### Советы

1. **Сверяйтесь с документацией.** Используйте удалённый RAG по P8 (`https://rag2026.covaga.xyz`),
   чтобы уточнить точное имя действия EPLAN и его параметры.
2. **Пишите содержательные docstring и аннотации типов.** Они становятся описанием инструмента и
   схемой входных данных, которые видит LLM и на которые опирается.
3. **Аккуратно с путями.** Пути Windows нужно экранировать (`\\`) или писать через `/`.

## Приватные модули расширений (`EPLAN_MCP_EXTENSIONS`)

Сервер может загружать **дополнительные модули инструментов извне этого репозитория** —
корпоративные или приватные инструменты (тестовые стенды для собственных надстроек, внутренние
процессы), которым не место в публичном репозитории.

Укажите в переменной окружения `EPLAN_MCP_EXTENSIONS` один или несколько каталогов (в Windows —
через `;`). Каждый `*.py`-файл верхнего уровня, имя которого не начинается с `_`, импортируется при
запуске, а функции из его `__all__` регистрируются как MCP-инструменты так же, как встроенные
действия:

```python
# my_company_tools.py  (в приватном репозитории, НЕ в eplan-mcp)
TOOL_PREFIX = "acme_"          # необязательно, по умолчанию "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # папка api/ сервера находится в sys.path
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

Правила и поведение:

- `TOOL_PREFIX` задаёт пространство имён инструментов (`acme_run_smoke_test` выше).
- Расширения могут импортировать всё, что используют встроенные действия: `actions`,
  `actions._base`, `actions.scripted._execute_script` (выполнение C# внутри EPLAN),
  `eplan_connection`.
- Неисправное расширение выводит сообщение в stderr и пропускается; оно никогда не мешает
  запуску сервера.
- `eplan_list_extensions` показывает, что было загружено.

Вместе с инструментами жизненного цикла и одноразовых проектов это даёт полностью автоматический
цикл разработки приватных надстроек EPLAN: собрать DLL → развернуть → `eplan_app_restart` →
проверить, что действия надстройки зарегистрированы (например, скриптом `FindAction`) → запустить
их на одноразовом проекте → `eplan_get_system_messages`, чтобы поймать всё, на что пожаловался EPLAN.

## Выбор версии EPLAN (автоматически)

**Ничего настраивать не нужно.** При запуске сервер ищет установленные версии в
`C:\Program Files\EPLAN\Platform` и:

- **Автоматический режим (по умолчанию):** `eplan_connect` подключается к **самой новой
  установленной версии** и сам выбирает подходящую среду .NET — coreclr для EPLAN 2027+ и
  .NET Framework для 2026 и старше.
- **Явный режим:** LLM может вызвать `eplan_versions`, чтобы получить список установленных
  версий, и подключиться к нужной через `eplan_connect(version="2026")` — например, «connect to
  eplan 2026».

Примечания:

- EPLAN установлен в нестандартное место? Укажите в `EPLAN_PLATFORM_ROOT` его папку `Platform`.
- После загрузки в процесс DLL одной версии для смены версии нужен перезапуск MCP-сервера: среду
  .NET нельзя заменить во время работы.
- `eplan_connect` также принимает `host` (и `"host:port"`) для подключения к EPLAN на другом
  компьютере; автоопределение порта работает только на localhost.

## Связанные репозитории

| Репозиторий | Что это |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Навык Claude Code, описанный выше, — самостоятельный и не привязанный к окружению. Установка: `/plugin marketplace add Canary-ECAD/eplan-mcp`. |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | Добавление собственных пунктов в контекстные меню EPLAN и чтение строки, по которой щёлкнул пользователь. Инструмент исследования и готовый пример. |

## Ресурсы

- [Документация EPLAN API](https://www.eplan.help/)
- [Спецификация протокола MCP](https://modelcontextprotocol.io/)
- [Документация Claude Code](https://docs.anthropic.com/claude-code)

## Лицензия

MIT — см. [`LICENSE`](LICENSE).

> **Примечание:** это независимый проект сообщества [Canary E-cad](https://github.com/Canary-ECAD). Он не связан с EPLAN GmbH & Co. KG и не одобрен и не поддерживается ею. EPLAN, EPLAN Electric P8 и EPLAN EEC Pro — товарные знаки соответствующего владельца.
