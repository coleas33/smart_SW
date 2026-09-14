# Third-party references and attributions

## Repositories studied or reimplemented

This project reuses ideas, and in some places patterns, from the repositories below. No
code was copied from repositories whose license does not permit it.

| Repository | License | How it is used here |
|------------|---------|---------------------|
| delancy827/solidworks-skills | MIT | Pattern for a single-owner SOLIDWORKS COM connection, a verified-API allowlist, and a circuit breaker that trips after consecutive COM failures. Reimplemented in `extractor/SwReview.Extractor/Guard/`. |
| earthtojake/text-to-cad | MIT | Reference for STEP-based inspection and its interference-threshold semantics (volume, not clearance). Not linked; a possible optional input later. |
| Pan-Chera/Multi-Agent-CAD | MIT | Design ideas only: evidence contracts, bounded retries, explicit verification states. No code reused. |
| alisamsam/Solidworks-MCP | MIT | Studied as a counter-example: its `execute_python` tool is the kind of general code execution this project forbids. No code reused. |
| arthurle3210/SwpilotCLI | Custom (internal organizational use only; no redistribution) | API call sequences consulted as a reference only. **No code copied**, and none may be: the license permits internal use but forbids redistribution and derivative shipping. Its Task Pane hosts a CLI by spawning a console window and reparenting it with `SetParent`; the pseudo-console mechanism here was written from the Windows API documentation instead (research.md R1, R5) and shares no source with it. Its drawing reader is not used because of documented unit and precision defects. |
| arthurle3210/swapi-pilot-solidworks-mcp | No license file | Documents a hosted MCP server for searching the SOLIDWORKS API reference. Not connected by default; see the research notes before enabling. |
| microsoft/terminal (`samples/ConPTY/MiniTerm`) | MIT | Reference for the ConPTY sequence a host must follow - `CreatePseudoConsole`, the `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` startup attribute, `ResizePseudoConsole`, and closing the console to end the client. Reimplemented in `extractor/SwReview.AddIn/Terminal/ConPty.cs` against the Win32 documentation; the sample's source is not vendored. |
| Adam-CAD/CADAM | GPL-3.0 | Not linked. |

## Vendored files

| File | Package | Version | License |
|------|---------|---------|---------|
| `extractor/SwReview.AddIn/Terminal/TerminalPage/vendor/xterm.js`, `xterm.css` | `@xterm/xterm` | 6.0.0 | MIT |
| `extractor/SwReview.AddIn/Terminal/TerminalPage/vendor/addon-fit.js` | `@xterm/addon-fit` | 0.11.0 | MIT |

These three files are the published npm artifacts, taken byte-for-byte with no build step
and no local edits, and are loaded from disk - there is no CDN reference anywhere. Their
SHA-256 digests, the refresh procedure, and the full MIT texts are in
`extractor/SwReview.AddIn/Terminal/TerminalPage/vendor/LICENSES.md`.

## Python runtime dependencies

Declared in `reviewer/pyproject.toml`; installed, not vendored.

| Package | License | Used for |
|---------|---------|----------|
| `openai` | Apache-2.0 | The default provider adapter (Responses API). |
| `google-genai` | Apache-2.0 | The Gemini provider adapter. |
| `mcp` | MIT | The stdio MCP server that exposes the read-only toolset to an external CLI. |
| `starlette` | BSD-3-Clause | The loopback HTTP app behind the Task Pane chat backend. |
| `sse-starlette` | BSD-3-Clause | Server-sent events for that backend's event stream. |
| `uvicorn` | BSD-3-Clause | The ASGI server that runs it on 127.0.0.1. |
| `httpx` | BSD-3-Clause | HTTP client, including the bridge client and the test client. |
| `pydantic` | MIT | IR, session and settings models; tool schema generation via `TypeAdapter`. |
| `pint` | BSD-3-Clause | The unit registry every `Quantity` crosses. |
| `trimesh` | MIT | Mesh loading for envelope and bounding-box tools. |
| `numpy` | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 components) | Geometry arithmetic. |
| `pymupdf` | AGPL-3.0-or-later, or a commercial license from Artifex | Drawing-PDF text extraction. Copyleft, so worth flagging: a build distributed outside the organization would need the commercial license or a replacement reader. |
| `pdfplumber` | MIT | Drawing-PDF layout and table extraction. |
| `typer` | MIT | The `swreview` command line. |
| `pyyaml` | MIT | Checklist files. |
| `embreex` (optional `raycast` extra) | BSD-2-Clause; bundles Intel Embree, Apache-2.0 | Accelerated ray casting for the tool-envelope check. |

There is no Anthropic dependency: the reviewer runs on OpenAI or Gemini through its own
provider layer (`reviewer/src/swreview/agent/providers/`).

## .NET runtime dependencies

| Package | License | Used for |
|---------|---------|----------|
| `Microsoft.Web.WebView2` | Microsoft Software License Terms (WebView2 SDK); the runtime is installed on the workstation, not redistributed here | The Task Pane's Review page and terminal page host. |
| `System.Text.Json` | MIT | Message and settings serialization in the add-in and the extractor. |

SOLIDWORKS API interop assemblies are Dassault Systèmes property, referenced from the local
SOLIDWORKS installation and never redistributed with this project.
