# Kit de automatización de EPLAN con IA

[English](README.md) · **Español** · [Deutsch](README.de.md) · [中文](README.zh-CN.md) · [한국어](README.ko.md) · [Türkçe](README.tr.md) · [Polski](README.pl.md) · [Русский](README.ru.md)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

Automatización asistida por IA para **EPLAN Electric P8** y **EPLAN EEC Pro 2026**, basada en
el Model Context Protocol (MCP).

📖 **Documentación, guía de instalación y referencia completa de herramientas: [covaga.dev](https://covaga.dev/es/)**

Este repositorio contiene el servidor MCP local que controla una instancia de EPLAN en
ejecución. Los tres RAG remotos de documentación están en el repositorio independiente
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags).

> ¿Trabajas aquí con un LLM? Lee [`llm.md`](llm.md): describe, en términos pensados para un
> LLM, todo lo que el kit puede hacer y configurar.

## Estructura del repositorio

```
.
└── eplan-p8-mcp-server/          # LOCAL: servidor MCP que controla EPLAN P8
```

| Componente | Tipo | Función | Producto EPLAN |
|---|---|---|---|
| `eplan-p8-mcp-server/` | MCP local en Python | Controlar una instancia de EPLAN desde Claude: abrir/cerrar proyectos, exportaciones, informes, scripts | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | Cloudflare Workers remotos, repositorio independiente | Servir la documentación de P8 2026, P8 2027 y EEC Pro por MCP y REST | EPLAN Electric P8 y EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Skill de Claude Code, repositorio independiente | Enseñar a Claude a escribir scripts de EPLAN, código de la API y apps Remote Client correctos | EPLAN Electric P8 |

Cada repositorio tiene su propio README con los detalles de instalación y uso.

## ¿Qué es MCP?

**MCP (Model Context Protocol)** es un estándar abierto que permite a los asistentes de IA
interactuar con herramientas y servicios externos. En lugar de limitarse a generar código,
Claude puede *ejecutar* acciones dentro de EPLAN en tiempo real y consultar la documentación
mediante búsqueda.

## Inicio rápido

### Automatización local de EPLAN (P8)

```bash
pip install pythonnet "mcp<2"
claude mcp add eplan -- python TU_RUTA/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # debería aparecer "eplan"
```

Después abre EPLAN, abre Claude Code y di `connect to eplan`. La guía completa está en
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md).

![Claude CLI configurado](assets/claude-cli-configured.png)

#### Requisito previo

El acceso remoto debe estar activado en EPLAN para que el servidor pueda conectarse: activa
**Permitir acceso remoto mediante Remote Client** en **Archivo → Ajustes… → Puesto de
trabajo → Interfaces → Acceso remoto**.

![Permitir acceso remoto mediante Remote Client](assets/remoting-allow-local-access.png)

#### Qué expone el servidor

En su modo `full` por defecto, el servidor publica **199 herramientas**:

| Grupo | Cantidad | Qué cubre |
|---|---|---|
| Conexión / utilidades | 8 | Conectar, elegir versión, estado, listar extensiones |
| Acciones tipadas de EPLAN (`eplan_*`) | 183 | Una herramienta por cada acción documentada o verificada; cada una se ejecuta en silencio dentro de un script C# en QuietMode, así que ningún diálogo de EPLAN puede bloquear una ejecución desatendida |
| Catálogo de acciones (`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`) | 4 | Da acceso a otras ~1.050 acciones que solo existen como botones de la interfaz, extraídas del `MFTools.xml` de la instalación y no de la documentación oficial |
| Asset Administration Shell (`aas_*`) | 4 | Exportación e importación de gemelos digitales AAS/AASX |

Las ~1.050 acciones del catálogo *no* tienen a propósito una herramienta propia cada una:
eso habría triplicado el número de herramientas y empeorado la elección de herramienta para
todo lo demás.

Entre las 183 herramientas tipadas hay cuatro del DataModel en vivo —
`eplan_live_query_functions`, `eplan_live_query_pages`, `eplan_live_set_function_text`
y `eplan_live_set_connection_designations`— que leen y editan el modelo de objetos del
proyecto abierto mediante reflexión en tiempo de ejecución, sorteando la limitación del motor
de scripts con las directivas `using` estáticas.

Además de las acciones individuales, el conjunto cubre las piezas de un ciclo
desarrollar → desplegar → probar totalmente desatendido:

- **Ciclo de vida de la aplicación** — `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`: cerrar EPLAN, cambiar DLL de add-ins, relanzar, reconectar y reabrir el proyecto.
- **Proyectos desechables** — `eplan_scratch_project_*`: proyectos de prueba clonados de una plantilla.
- **Diagnóstico** — `eplan_get_system_messages`: leer el árbol de mensajes de EPLAN y ver los
  mismos errores y avisos que ve el usuario en la interfaz.
- **Módulos de extensión privados** — ver [más abajo](#módulos-de-extensión-privados-eplan_mcp_extensions).

La referencia herramienta por herramienta, generada a partir de los docstrings de este
repositorio, está en [covaga.dev/docs/tools](https://covaga.dev/es/docs/tools/project-and-workspace-management/).

#### Modo discovery

`EPLAN_MCP_MODE=discovery` publica 13 herramientas en lugar de 199: cambia una lista de
herramientas que consume muchos tokens por una búsqueda extra en cada tarea. Compensa en
clientes MCP que envían el esquema completo de todas las herramientas en cada petición.

**En Claude Code no lo uses.** Claude Code ya aplaza los esquemas de herramientas por su
cuenta (primero una lista de nombres y el esquema solo cuando hace falta), así que la lista
`full` de 199 herramientas ya le cuesta casi lo mismo que las 13 de `discovery`, y añadir la
indirección buscar → describir → llamar solo suma un viaje de ida y vuelta. El análisis y las
mediciones están en
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode).

### RAG remotos de documentación (P8, EEC Pro, 2027)

Ya desplegados y listos para usar, sin datos locales:

```bash
# Documentación de EPLAN Electric P8 (2026, búsqueda semántica)
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# Documentación de EPLAN EEC Pro 2026
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# Documentación de EPLAN Electric P8 (2027, búsqueda por palabras clave / texto completo)
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027` es a propósito un servidor aparte y no una actualización 2026 → 2027 de
`eplan-rag`: indexa otra versión de la documentación *y* usa otro modo de búsqueda (coincidencia
por palabras clave con SQLite FTS5/bm25 sobre la wiki incluida en
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027),
frente a la búsqueda semántica con Vectorize + bge). Comparados con consultas reales fallan de
forma distinta: FTS5 gana al buscar nombres exactos ("¿cuál es la firma de X?") y la búsqueda
semántica gana cuando la consulta no comparte vocabulario con la documentación. Instala los dos.

Ambos ofrecen también una API REST sencilla, útil para verificar nombres y parámetros de
acciones de EPLAN mientras desarrollas:

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

Consulta [`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) y
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md) para ver las herramientas,
los endpoints REST y la arquitectura.

### RAG visual de símbolos (nuevo)

Identifica símbolos eléctricos de EPLAN a partir de imágenes: entra un glifo recortado de un
PDF, esquema o captura de pantalla y sale el `short_name` real:

- Índice: 33.502 imágenes de símbolos de EPLAN (IEC/NFPA) con embeddings CLIP ViT-B/32
  (512 dimensiones, coseno) en Cloudflare Vectorize, a partir de
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset).
- Endpoint público `https://symbols.covaga.xyz` (mismo modelo abierto que los demás RAG, sin
  credenciales):

```bash
# vector = embedding CLIP ViT-B/32 normalizado L2 de la imagen del símbolo
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

Cada resultado incluye `short_name`, el `number` del catálogo, `description` y `variant_id`,
además de una puntuación de coseno; el `short_name` es el identificador que esperan las
llamadas a la API de EPLAN. La reindexación y el redespliegue se hacen con GitHub Actions en
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols).

#### Usarlo desde este servidor MCP

Hay una extensión lista para usar en
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py).
Actívala y el agente tendrá la herramienta `eplan_symbol_search`:

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

Después, con una imagen recortada de un símbolo, Claude llama a
`eplan_symbol_search(image_path="C:\\...\\crop.png")` → la imagen se convierte en embedding
localmente con CLIP → `symbols.covaga.xyz` devuelve candidatos como
`F1 (no. 50, variant B) — Fuse, single-pole` → usa el mejor `short_name` en las llamadas a la
API de EPLAN. No hace falta token de Cloudflare: el Worker tiene el binding del índice.

### Skill de Claude Code para desarrollar en EPLAN

Los servidores MCP permiten a Claude *actuar* sobre EPLAN. La skill
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) le enseña a
*escribir código de EPLAN correcto*: puntos de entrada de scripts, parámetros de acciones
verificados, acceso a la base de datos de artículos, automatización con Remote Client (puertos
dinámicos, EPLAN sin interfaz, Cogineer) y las trampas de producción: bloqueo de comandos
pseudoasíncronos, el hilo monitor del bucle de mensajes, la disciplina de dispose y los cambios
de remoting de EPLAN 2025.

La skill vive en su propio repositorio y es a propósito **independiente del entorno**: no da por
hecho ningún servidor MCP, ningún ejecutor de scripts concreto ni ningún índice de documentación,
así que es útil por sí sola, uses o no lo demás de aquí.

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # router + skill de P8 + RAGs de docs de P8
/plugin install eplan-scripting@eplan-tools  # solo Electric P8
/plugin install eec-pro@eplan-tools          # solo EEC Pro
```

Instalación manual y detalles:
[el README de la skill](https://github.com/Canary-ECAD/eplan-scripting-skill#readme).

## Añadir nuevas acciones de EPLAN

El servidor MCP local registra las herramientas **dinámicamente** a partir de la lista
`__all__` de cada paquete de acciones, así que añadir una acción son dos pasos y nada de código
repetitivo por herramienta.

### 1. Implementa la acción

En `eplan-p8-mcp-server/mcp_server/api/actions/<tu_modulo>.py`:

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

### 2. Expórtala

Añade la función a los imports **y** a `__all__` en
`eplan-p8-mcp-server/mcp_server/api/actions/__init__.py`. Se registrará automáticamente como
`eplan_open_project`.

### 3. Reinicia el servidor MCP

La nueva herramienta estará disponible cuando se reinicie Claude o el servidor.

### 4. Valida con la documentación oficial (opcional)

`eplan-p8-mcp-server/tools/validate_actions.py` compara cada nombre de acción y cada
parámetro declarados en los wrappers con el RAG de la documentación oficial de EPLAN y genera
un informe en markdown:

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![Prueba en EPLAN](assets/eplan-test.png)

### Consejos

1. **Verifica con la documentación.** Usa el RAG remoto de P8 (`https://rag2026.covaga.xyz`)
   para confirmar el nombre exacto de la acción de EPLAN y sus parámetros.
2. **Escribe docstrings y anotaciones de tipo útiles.** Se convierten en la descripción de la
   herramienta y en el esquema de entrada que el LLM ve y en el que confía.
3. **Cuidado con las rutas.** Las rutas de Windows necesitan escapar (`\\`) o barras normales (`/`).

## Módulos de extensión privados (`EPLAN_MCP_EXTENSIONS`)

El servidor puede cargar **módulos de herramientas adicionales desde fuera de este
repositorio**: herramientas propias de una empresa o privadas (bancos de pruebas de add-ins,
flujos internos) que no deben estar en un repositorio público.

Apunta la variable de entorno `EPLAN_MCP_EXTENSIONS` a una o varias carpetas (separadas por
`;` en Windows). Cada fichero `*.py` de primer nivel que no empiece por `_` se importa al
arrancar, y sus funciones de `__all__` se registran como herramientas MCP igual que las
acciones incluidas:

```python
# my_company_tools.py  (en un repositorio privado, NO en eplan-mcp)
TOOL_PREFIX = "acme_"          # opcional, por defecto "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # la carpeta api/ del servidor está en sys.path
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

Reglas y comportamiento:

- `TOOL_PREFIX` da un espacio de nombres a las herramientas (`acme_run_smoke_test` arriba).
- Las extensiones pueden importar todo lo que usan las acciones incluidas: `actions`,
  `actions._base`, `actions.scripted._execute_script` (ejecutar C# dentro de EPLAN),
  `eplan_connection`.
- Una extensión rota se notifica por stderr y se omite; nunca impide que arranque el servidor.
- `eplan_list_extensions` muestra lo que se ha cargado.

Junto con las herramientas de ciclo de vida y de proyectos desechables, esto permite un ciclo
totalmente desatendido para desarrollar add-ins privados de EPLAN: compilar la DLL → desplegar →
`eplan_app_restart` → comprobar que se registraron las acciones del add-in (por ejemplo con un
script `FindAction`) → ejecutarlas contra un proyecto desechable →
`eplan_get_system_messages` para detectar cualquier queja de EPLAN.

## Selección de la versión de EPLAN (automática)

**No hay nada que configurar.** Al arrancar, el servidor busca las versiones instaladas en
`C:\Program Files\EPLAN\Platform` y:

- **Modo automático (por defecto):** `eplan_connect` usa la **versión instalada más reciente**
  y elige automáticamente el runtime de .NET correspondiente: coreclr para EPLAN 2027+ y
  .NET Framework para 2026 y anteriores.
- **Modo explícito:** el LLM puede llamar a `eplan_versions` para ver lo instalado y conectarse
  a una versión concreta con `eplan_connect(version="2026")`, por ejemplo "connect to eplan 2026".

Notas:

- ¿EPLAN instalado en una ruta no estándar? Define `EPLAN_PLATFORM_ROOT` con su carpeta `Platform`.
- Una vez cargadas en el proceso las DLL de una versión, cambiar de versión requiere reiniciar
  el servidor MCP: un runtime de .NET no se puede cambiar en caliente.
- `eplan_connect` también acepta un `host` (y `"host:puerto"`) para llegar a un EPLAN en otro
  equipo; la detección automática del puerto solo funciona en localhost.

## Repositorios relacionados

| Repositorio | Qué es |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | La skill de Claude Code de arriba, independiente y sin depender del entorno. Instálala con `/plugin marketplace add Canary-ECAD/eplan-mcp`. |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | Añade entradas propias a los menús contextuales de EPLAN y lee la fila en la que hizo clic el usuario. Una herramienta de exploración y un ejemplo completo. |

## Recursos

- [Documentación de la API de EPLAN](https://www.eplan.help/)
- [Especificación del protocolo MCP](https://modelcontextprotocol.io/)
- [Documentación de Claude Code](https://docs.anthropic.com/claude-code)

## Licencia

MIT: consulta [`LICENSE`](LICENSE).

> **Aviso:** este es un proyecto comunitario independiente de [Canary E-cad](https://github.com/Canary-ECAD). No está afiliado, respaldado ni soportado por EPLAN GmbH & Co. KG. EPLAN, EPLAN Electric P8 y EPLAN EEC Pro son marcas de su respectivo propietario.
