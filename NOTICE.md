# Third-party references and attributions

This project reuses ideas, and in some places patterns, from the repositories below. No
code was copied from repositories whose license does not permit it.

| Repository | License | How it is used here |
|------------|---------|---------------------|
| delancy827/solidworks-skills | MIT | Pattern for a single-owner SOLIDWORKS COM connection, a verified-API allowlist, and a circuit breaker that trips after consecutive COM failures. Reimplemented in `extractor/SwReview.Extractor/Guard/`. |
| earthtojake/text-to-cad | MIT | Reference for STEP-based inspection and its interference-threshold semantics (volume, not clearance). Not linked; a possible optional input later. |
| Pan-Chera/Multi-Agent-CAD | MIT | Design ideas only: evidence contracts, bounded retries, explicit verification states. No code reused. |
| alisamsam/Solidworks-MCP | MIT | Studied as a counter-example: its `execute_python` tool is the kind of general code execution this project forbids. No code reused. |
| arthurle3210/SwpilotCLI | Custom (internal organizational use only; no redistribution) | API call sequences consulted as a reference only. No code copied. Its drawing reader is not used because of documented unit and precision defects. |
| arthurle3210/swapi-pilot-solidworks-mcp | No license file | Documents a hosted MCP server for searching the SOLIDWORKS API reference. Not connected by default; see the research notes before enabling. |
| Adam-CAD/CADAM | GPL-3.0 | Not linked. |

SOLIDWORKS API interop assemblies are Dassault Systèmes property, referenced from the local
SOLIDWORKS installation and never redistributed with this project.
