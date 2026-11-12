# Security Policy

**License**：BSD-3-Clause（详见 [LICENSE](LICENSE)；代码许可与云端数据服务约束分离，见 CONTRIBUTING.md「许可政策」）。

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.19.x  | ✅（当前 minor 线） |
| 1.18.x  | ✅（上一 minor 线，仅高危修复） |
| < 1.18  | ❌（不接收安全修复，请升级） |

Last reviewed: 2026-11-12（as_of `1.19.0`）。策略为「仅当前 minor 线 +
上一 minor 线」，发版时必须同步本表；`tools/check_version.py --check` 会把
六处版本声明（pyproject / `__version__` / `server.json`×2 / `openapi.info.version` /
CHANGELOG 顶部 release 段）与表头、`as_of` 一并互校，防止再次腐化。

**Response target**：确认后 5 个工作日内给出初步判断，高危问题优先；修复
随最近一次 minor 发布，必要时单独发 patch。

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them privately via [GitHub Security Advisories]
(https://github.com/open-winmale/wmshare/security/advisories/new)
("Report a vulnerability"), or contact the maintainers directly.

Please include:

- A description of the issue and its impact;
- Steps to reproduce or a proof of concept;
- Affected version(s) and environment, including the SDK version and the values
  of `WMSHARE_HOST_POLICY`, `WMSHARE_ALLOW_CUSTOM_HOST`,
  `WMSHARE_ALLOW_CUSTOM_CATALOG`, `WMSHARE_MCP_MAX_EC` (state "default" when unset).

## Scope notes

- **Endpoint policy**: by default the SDK only sends credentials to
  `api.winmale.com` / `test-api.winmale.com` (plus loopback HTTP for a local
  gateway). This is enforced in `src/wmshare/_endpoints.py`; a non-allowlisted
  HTTPS host is rejected even though HTTPS itself is valid. Loosening requires
  an explicit `allow_custom_host=True`, `WMSHARE_ALLOW_CUSTOM_HOST=1`, or the
  emergency `WMSHARE_HOST_POLICY=legacy` fallback. OAuth token calls disable
  automatic redirects, because 307/308 would replay the POST body containing
  `client_secret` to a new host.
- **Catalog policy**: `WMSHARE_CATALOG_DIR` alone is no longer enough — it also
  requires `WMSHARE_ALLOW_CUSTOM_CATALOG=1` and a complete `generated/` tree.
  Domain YAML contributes `normalize_with` / `xs.require` to server-side XS
  scripts, so replacing the catalog root is a script-injection surface, not a
  configuration toggle.
- **Low-level escape hatch**: `Client.eval()` sends its string to the server
  unchanged. It is not exposed through the MCP gateway; never pass LLM-produced
  or otherwise untrusted text to it. Report any path that lets an Agent reach it.
- **MCP gateway**: `cbond.figures` / `cbond.article` can write to arbitrary
  paths and are refused at the gateway (the local Python SDK still supports
  them). Per-call EC is capped by `WMSHARE_MCP_MAX_EC`; error envelopes carry
  `demo` / `as_of` / `data_freshness` so a frozen demo snapshot cannot be
  mistaken for live data.
- **Credentials** (`client_id` / `client_secret`) are read from environment
  variables, `~/.wmshare/credentials.env`, or explicit constructor arguments.
  A credential file readable by group/other triggers a warning; set
  `WMSHARE_STRICT_CRED_MODE=1` to refuse it. Never commit credentials to this
  repository — `tools/check_leak.py` and CI scan for secret-looking literals,
  but you are responsible for your own keys. Error messages redact known
  credential values and Bearer tokens before truncation.

## What is in scope

- Credential leakage or unintended network endpoints in the SDK, including
  redirect-based replay of the OAuth body.
- Injection/unsafe deserialization in catalog or response handling; arbitrary
  XS execution paths.
- MCP gateway side effects (filesystem writes, unbounded EC spend) and
  misleading data provenance.
- The leak gate / drift gates themselves failing to catch an obvious violation.
- Supply-chain issues: unpinned Actions, release artifacts without provenance,
  malicious dependencies.
