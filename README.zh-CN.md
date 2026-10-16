# EPLAN AI 自动化工具包

[English](README.md) · [Español](README.es.md) · [Deutsch](README.de.md) · **中文** · [한국어](README.ko.md) · [Türkçe](README.tr.md) · [Polski](README.pl.md) · [Русский](README.ru.md)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

基于模型上下文协议（MCP）的 **EPLAN Electric P8** 与 **EPLAN EEC Pro 2026** AI 辅助自动化。

📖 **文档、安装指南和完整的工具参考：[covaga.dev](https://covaga.dev/zh-cn/)**

本仓库包含用于控制正在运行的 EPLAN 实例的本地 MCP 服务器。三个远程文档 RAG 位于独立仓库
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags)。

> 正在用 LLM 处理这个仓库？请阅读 [`llm.md`](llm.md)——它以面向 LLM 的方式说明了本工具包能做
> 和能配置的一切。

## 仓库结构

```
.
└── eplan-p8-mcp-server/          # 本地：控制 EPLAN P8 的 MCP 服务器
```

| 组件 | 类型 | 用途 | EPLAN 产品 |
|---|---|---|---|
| `eplan-p8-mcp-server/` | 本地 Python MCP | 从 Claude 操控正在运行的 EPLAN：打开/关闭项目、导出、报表、脚本 | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | 远程 Cloudflare Workers，独立仓库 | 通过 MCP 和 REST 提供 P8 2026、P8 2027 与 EEC Pro 文档 | EPLAN Electric P8 与 EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Claude Code Skill，独立仓库 | 教 Claude 写出正确的 EPLAN 脚本、API 代码和 Remote Client 应用 | EPLAN Electric P8 |

每个仓库都有各自的 README，包含安装与使用说明。

## 什么是 MCP？

**MCP（Model Context Protocol，模型上下文协议）** 是一项开放标准，让 AI 助手能够与外部工具和
服务交互。Claude 不只是生成代码，还能在 EPLAN 中实时*执行*操作，并通过搜索查阅文档。

## 快速开始

### 本地 EPLAN 自动化（P8）

```bash
pip install pythonnet mcp
claude mcp add eplan -- python 你的路径/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # 应列出 "eplan"
```

然后启动 EPLAN，打开 Claude Code，说 `connect to eplan`。完整指南见
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md)。

![已配置的 Claude CLI](assets/claude-cli-configured.png)

#### 使用前提

服务器连接前，必须先在 EPLAN 中启用远程访问：在 **文件 → 设置… → 工作站 → 接口 → 远程访问**
中打开 **允许通过 Remote Client 远程访问**。

![允许通过 Remote Client 远程访问](assets/remoting-allow-local-access.png)

#### 服务器提供哪些工具

在默认的 `full` 模式下，服务器发布 **199 个工具**：

| 分组 | 数量 | 覆盖内容 |
|---|---|---|
| 连接 / 实用工具 | 8 | 连接、版本选择、状态、列出扩展 |
| 带类型的 EPLAN 操作（`eplan_*`） | 183 | 每个已文档化或已验证的操作对应一个工具，均在 QuietMode 下的 C# 脚本中静默执行，因此任何 EPLAN 对话框都无法阻塞无人值守的运行 |
| 操作目录（`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`） | 4 | 可调用另外约 1,050 个只以界面按钮形式存在的操作，这些操作取自安装目录中的 `MFTools.xml`，而非官方文档 |
| 资产管理壳（`aas_*`） | 4 | AAS/AASX 数字孪生的导出与导入 |

约 1,050 个目录操作被刻意*没有*各自封装成工具：那样会让工具数量翻三倍，并降低其他所有工具的
选择准确度。

183 个带类型的工具中包含四个实时 DataModel 工具——
`eplan_live_query_functions`、`eplan_live_query_pages`、`eplan_live_set_function_text`
和 `eplan_live_set_connection_designations`——它们通过运行时反射读取和编辑当前打开项目的
对象模型，绕开了脚本引擎对静态 `using` 指令的限制。

除了单个操作，这套工具还覆盖了完全无人值守的"开发 → 部署 → 测试"循环所需的组件：

- **应用生命周期** —— `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`：退出 EPLAN、替换插件 DLL、重新启动、重新连接并重新打开项目。
- **一次性测试项目** —— `eplan_scratch_project_*`：从模板克隆出的临时项目。
- **诊断** —— `eplan_get_system_messages`：读取 EPLAN 的消息树，看到与用户在界面中相同的错误和警告。
- **私有扩展模块** —— 见[下文](#私有扩展模块eplan_mcp_extensions)。

根据本仓库 docstring 生成的逐个工具参考位于
[covaga.dev/docs/tools](https://covaga.dev/zh-cn/docs/tools/project-and-workspace-management/)。

#### Discovery 模式

`EPLAN_MCP_MODE=discovery` 只发布 13 个工具而非 199 个，用每个任务多一次搜索往返，换取更省
token 的工具列表。对于每次请求都发送全部工具完整 schema 的 MCP 客户端，这很划算。

**在 Claude Code 中不要使用。** Claude Code 本身已经会延迟加载工具 schema——先给出名称列表，
需要时再获取 schema——因此 `full` 模式的 199 个工具在其中的开销与 `discovery` 的 13 个相差无几，
再叠加"搜索 → 描述 → 调用"的间接层只会多一次往返。取舍分析和测量数据见
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode)。

### 远程文档 RAG（P8、EEC Pro、2027）

已经部署，开箱即用——无需本地数据：

```bash
# EPLAN Electric P8 文档（2026，语义搜索）
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# EPLAN EEC Pro 2026 文档
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# EPLAN Electric P8 文档（2027，关键词/全文搜索）
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027` 被刻意做成独立服务器，而不是把 `eplan-rag` 从 2026 升级到 2027：它索引的是
另一个文档版本，*并且*使用另一种搜索方式（在
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027)
自带的 wiki 上做 SQLite FTS5/bm25 关键词匹配，而不是 Vectorize + bge 语义搜索）。用真实查询
正面对比，两者的短板不同：FTS5 擅长精确名称查找（"X 的签名是什么"），语义搜索则在查询与文档
没有共同词汇时胜出。两个都装上。

两者还提供简单的 REST API，开发时可方便地核对 EPLAN 操作名称和参数：

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

工具、REST 端点和架构说明见
[`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) 和
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md)。

### 符号图像 RAG（新）

从图像识别 EPLAN 电气符号：输入从 PDF、原理图或截图中裁剪出的符号，输出真实的 `short_name`：

- 索引：33,502 张 EPLAN 符号图像（IEC/NFPA），用 CLIP ViT-B/32（512 维，余弦）嵌入到
  Cloudflare Vectorize，数据来自
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset)。
- 公共端点 `https://symbols.covaga.xyz`（与其他 RAG 一样开放，无需凭据）：

```bash
# vector = 符号图像经 L2 归一化的 CLIP ViT-B/32 嵌入
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

每个匹配项都包含 `short_name`、目录 `number`、`description` 和 `variant_id`，以及余弦得分——
`short_name` 就是 EPLAN API 调用所需的标识符。重新索引和重新部署通过
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols)
中的 GitHub Actions 完成。

#### 在本 MCP 服务器中使用

现成的扩展位于
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py)。
启用后，智能体会获得 `eplan_symbol_search` 工具：

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

之后给出一张裁剪好的符号图像，Claude 会调用
`eplan_symbol_search(image_path="C:\\...\\crop.png")` → 图像在本地用 CLIP 生成嵌入 →
`symbols.covaga.xyz` 返回诸如 `F1 (no. 50, variant B) — Fuse, single-pole` 的候选 →
在 EPLAN API 调用中使用排名第一的 `short_name`。无需 Cloudflare 令牌：索引绑定由 Worker 持有。

### 用于 EPLAN 开发的 Claude Code Skill

MCP 服务器让 Claude 能在 EPLAN 中*执行操作*。
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) Skill 则教它
*写出正确的 EPLAN 代码*：脚本入口点、经过验证的操作参数、部件数据库访问、Remote Client 自动化
（动态端口、无界面 EPLAN、Cogineer），以及生产环境中的陷阱——伪异步命令阻塞、消息循环监视线程、
dispose 规范、EPLAN 2025 的远程访问变更。

该 Skill 位于独立仓库，并刻意设计为**与宿主无关**：它不假设任何 MCP 服务器、特定脚本运行器或
特定文档索引，因此无论你是否使用这里的其他组件，它都能单独发挥作用。

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # 路由器 + 全部 Skill + 文档 RAG
/plugin install eplan-scripting@eplan-tools  # 仅 Electric P8
/plugin install eec-pro@eplan-tools          # 仅 EEC Pro
```

手动安装及详情：
[该 Skill 的 README](https://github.com/Canary-ECAD/eplan-scripting-skill#readme)。

## 添加新的 EPLAN 操作

本地 MCP 服务器会根据每个操作包的 `__all__` 列表**动态**注册工具，因此添加一个操作只需两步，
无需为每个工具编写样板代码。

### 1. 实现该操作

在 `eplan-p8-mcp-server/mcp_server/api/actions/<你的模块>.py` 中：

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

### 2. 导出它

把函数加入 `eplan-p8-mcp-server/mcp_server/api/actions/__init__.py` 的 import **和** `__all__`。
它随后会自动注册为 `eplan_open_project`。

### 3. 重启 MCP 服务器

Claude 或服务器重启后，新工具即可使用。

### 4. 对照官方文档校验（可选）

`eplan-p8-mcp-server/tools/validate_actions.py` 会将封装中声明的每个操作名称和参数与官方 EPLAN
文档 RAG 进行比对，并生成 markdown 报告：

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![EPLAN 测试](assets/eplan-test.png)

### 小贴士

1. **对照文档核实。** 使用远程 P8 RAG（`https://rag2026.covaga.xyz`）确认 EPLAN 操作的准确名称
   及其参数。
2. **编写有意义的 docstring 和类型注解。** 它们会成为 LLM 看到并依赖的工具描述和输入 schema。
3. **谨慎处理路径。** Windows 路径需要转义（`\\`）或使用正斜杠（`/`）。

## 私有扩展模块（`EPLAN_MCP_EXTENSIONS`）

服务器可以**从本仓库之外加载额外的工具模块**——公司专用或私有的工具（自定义插件测试框架、
内部流程），这些不应放在公开仓库中。

将环境变量 `EPLAN_MCP_EXTENSIONS` 指向一个或多个目录（Windows 下用 `;` 分隔）。其中所有不以
`_` 开头的顶层 `*.py` 文件都会在启动时导入，其 `__all__` 中的函数会像内置操作一样注册为 MCP 工具：

```python
# my_company_tools.py  （位于私有仓库，而非 eplan-mcp 中）
TOOL_PREFIX = "acme_"          # 可选，默认为 "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # 服务器的 api/ 目录已在 sys.path 中
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

规则与行为：

- `TOOL_PREFIX` 为工具设置命名空间（上例中为 `acme_run_smoke_test`）。
- 扩展可以导入内置操作所使用的一切：`actions`、`actions._base`、
  `actions.scripted._execute_script`（在 EPLAN 内运行 C#）、`eplan_connection`。
- 出错的扩展会在 stderr 中报告并被跳过，绝不会阻止服务器启动。
- `eplan_list_extensions` 会显示已加载的内容。

结合生命周期工具和一次性测试项目工具，即可实现完全无人值守的私有 EPLAN 插件开发循环：
构建 DLL → 部署 → `eplan_app_restart` → 验证插件的操作已注册（例如通过 `FindAction` 脚本）→
在一次性测试项目上运行它们 → 用 `eplan_get_system_messages` 捕获 EPLAN 报告的任何问题。

## EPLAN 版本选择（自动）

**无需任何配置。** 启动时，服务器会扫描 `C:\Program Files\EPLAN\Platform` 中已安装的版本，并且：

- **自动模式（默认）：** `eplan_connect` 连接**最新安装的版本**，并自动选择匹配的 .NET 运行时
  ——EPLAN 2027 及以上使用 coreclr，2026 及更早版本使用 .NET Framework。
- **显式模式：** LLM 可以调用 `eplan_versions` 列出已安装的版本，再用
  `eplan_connect(version="2026")` 连接指定版本——例如说"connect to eplan 2026"。

注意：

- EPLAN 安装在非标准位置？将 `EPLAN_PLATFORM_ROOT` 设置为其 `Platform` 文件夹。
- 某个版本的 DLL 一旦加载到进程中，切换版本就需要重启 MCP 服务器——.NET 运行时无法在运行中替换。
- `eplan_connect` 也接受 `host`（以及 `"host:port"`），用于连接另一台机器上的 EPLAN 实例；
  端口自动检测仅在 localhost 上有效。

## 相关仓库

| 仓库 | 简介 |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | 上文介绍的 Claude Code Skill，独立且与宿主无关。用 `/plugin marketplace add Canary-ECAD/eplan-mcp` 安装。 |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | 向 EPLAN 的右键菜单添加自己的条目，并读取用户点击的那一行。包含一个探测工具和一个完整示例。 |

## 相关资源

- [EPLAN API 文档](https://www.eplan.help/)
- [MCP 协议规范](https://modelcontextprotocol.io/)
- [Claude Code 文档](https://docs.anthropic.com/claude-code)

## 许可证

MIT —— 见 [`LICENSE`](LICENSE)。

> **声明：** 本项目是 [Canary E-cad](https://github.com/Canary-ECAD) 的独立社区项目，与 EPLAN GmbH & Co. KG 无任何关联，也未获其认可或支持。EPLAN、EPLAN Electric P8 和 EPLAN EEC Pro 是其各自所有者的商标。
