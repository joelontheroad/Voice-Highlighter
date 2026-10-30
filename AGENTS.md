# AI Agent Engineering Directive: Open Source Standards Compliance

> **CRITICAL DIRECTIVE FOR AI CODING AGENTS**: When generating or modifying code, configuration, or documentation in this repository or any derived project, you **MUST** strictly adhere to the following 13 non-negotiable standards. Do not deviate without explicit user instructions.

---

## 1. Privacy & Data Residency
- **Zero Telemetry**: NEVER write code that calls external analytics, telemetry, or remote telemetry endpoints. No phone-home update checks on startup.
- **Local Data Only**: All presets, caches, and user settings MUST reside strictly on the local filesystem using Freedesktop XDG base directories (`basedir-spec` v0.8).
- **Log Sanitization**: When logging paths or errors, scrub user directory usernames (e.g., replace `/home/username` or `C:\Users\username` with `~<USER>`). NEVER log environment variables or auth tokens.
- **Deterministic Data Erasure (No Desktop Trash)**: Always provide a CLI option/command to reset or purge local state (`--reset-config` or `config reset`). State resets MUST permanently delete (unlink) files. Applications MUST NEVER move state to the Desktop Trash Can (`trash-spec`), which preserves unencrypted path metadata, usernames, and timestamps in `.trashinfo` files.
- **Zero Unsolicited Autostart**: NEVER configure or install background autostart entries (`autostart-spec`) by default. Services run strictly on-demand upon explicit user command. Autostart triggers on removable media are strictly prohibited.

## 2. Licensing, Lifecycle & Functional Preservation (GNU AGPL-3.0)
- **SPDX Headers**: Every new source file MUST begin with the REUSE/SPDX header:
  ```python
  # SPDX-FileCopyrightText: 2026 [Author/Organization]
  # SPDX-License-Identifier: AGPL-3.0-or-later
  ```
- **Single Source of Version**: NEVER hardcode version numbers in source file headers. Maintain version in a single place (`pyproject.toml`, `package.json`, or `__version__ = "1.0.0"`).
- **AGPL-3.0 Section 13 Source Notice**:
  - Web UI header/footer MUST display: `<a href="https://github.com/..." target="_blank" rel="noopener noreferrer">Source Code (GNU AGPLv3)</a>`.
  - CLI `--version` output MUST mention `GNU AGPLv3` and the repository URL.
- **Conventional Commits**: Format commit suggestions as `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- **Preservation of User-Facing Functionality**: NEVER delete, remove, rename, or disable any functionality with which the user interacts (including CLI commands, subcommands, short/long flags, configuration options, YAML preset keys, or Web UI controls) unless specifically and explicitly requested by the user.
- **Internal Implementation Freedom**: You HAVE FULL FREEDOM to refactor, clean up, optimize, or rewrite behind-the-scenes code (private helper functions, internal classes, algorithms, data structures, or file layouts), PROVIDED that all external user-facing behaviors are strictly preserved and existing tests pass without regression.
- **Proposed Deletions**: If you believe an existing user-facing feature or parameter is redundant, obsolete, or insecure, you MUST explicitly propose its deletion to the user and await explicit approval. Silent deletion of user-facing functionality is STRICTLY PROHIBITED.

## 3. UI Guidelines (CLI & Web UI)
- **CLI Standards**:
  - Implement standard flags: `-h/--help`, `-v/--version`, `-q/--quiet`, `--verbose`, `--config <path>`, `--json`.
  - Subcommands must be lowercase kebab-case (`tool preset list`).
  - Separation of streams: Write machine data to `stdout`. Write logs, progress bars, and diagnostics to `stderr`.
  - Terminal styling: Check `stdout.isatty()` before emitting ANSI colors; respect `NO_COLOR` environment variable.
  - Clickable URLs: Any URL printed to the terminal MUST be formatted as an OSC 8 clickable link (`\033]8;;<URL>\033\\<URL>\033]8;;\033\\`) when connected to an interactive TTY and `NO_COLOR` is absent, falling back to clean plain-text URLs when redirected or when `NO_COLOR` is active.
  - Automatic Browser Launch: Commands that start a local web interface or server MUST automatically launch the URL in the user's default browser window. Such commands MUST provide a `--no-browser` flag to suppress auto-launch, and MUST detect headless environments (`CI=true` or missing `DISPLAY`/`WAYLAND_DISPLAY`) and handle launch errors without crashing.
- **Web UI & Desktop Standards**:
  - Zero External CDNs: ALL CSS, JS, and font assets MUST be bundled and served locally. NO external `<link>`/`<script>` tags to Google Fonts, unpkg, cdnjs.
  - WCAG 2.1 AA: Text contrast ratio >= 4.5:1. Accessible focus rings. Support full keyboard navigation (Tab/Shift+Tab, Escape closes modals). Inputs must have explicit `<label for="...">`.
  - Show unsaved preset modifications visually (e.g. `Default *`).
  - Safe Desktop Entries (`desktop-entry-spec`): For tools with browser interfaces, generate `.desktop` launchers that invoke binaries directly without shell wrappers (`Exec=sh -c` is STRICTLY PROHIBITED). Double-quote parameters (`"%u"`) and terminate options with `--`.
  - Clipboard Security: NEVER silently write to the system clipboard. Writes MUST require an explicit user gesture (`--copy` CLI flag or UI button click). NEVER copy ephemeral launch tokens, secrets, or passwords to the clipboard. Prioritize Wayland tools (`wl-copy`) over legacy X11 tools (`xclip`).
  - Global Error Boundary (Zero Silent Crashes): Every Web UI MUST include top-level unhandled error listeners (`window.addEventListener('error')` and `window.addEventListener('unhandledrejection')`) that render a high-visibility, dismissible error banner at the top of the viewport. Uncaught errors MUST NEVER silently terminate script execution without user-visible feedback.
  - Transparent Control State: When an action button or UI control is disabled or inactive, the UI MUST provide a visible explanation (via tooltip, sub-label, or title) detailing the missing prerequisite or path (e.g. "Subtitles not detected at `<path>`").
  - Unique Operation & Task IDs: Frontend asynchronous job triggers and polling routines MUST generate cryptographically random or timestamp-unique IDs per invocation (e.g. `'task_' + Date.now() + '_' + crypto.randomUUID()`). Reusing dirty or retained task IDs from prior executions is strictly prohibited.

## 4. Configuration & Preset Management
- **Freedesktop XDG Base Directory (`basedir-spec` v0.8)**:
  - Config/Presets: `$XDG_CONFIG_HOME/<app-name>/` (Linux/macOS default: `~/.config/<app-name>/`, Windows: `%APPDATA%\<app-name>\`).
  - Data: `$XDG_DATA_HOME/<app-name>/` (`~/.local/share/<app-name>/`).
  - State (Logs/History): `$XDG_STATE_HOME/<app-name>/` (`~/.local/state/<app-name>/`).
  - Cache: `$XDG_CACHE_HOME/<app-name>/` (`~/.cache/<app-name>/`).
  - Runtime: `$XDG_RUNTIME_DIR/<app-name>/` (`/run/user/$UID/<app-name>/`, mode `0700`).
- **YAML Presets**: Presets MUST be saved as readable YAML (`.yaml`) with explanatory comments.
- **5-Tier Precedence**: CLI flags > Env vars (`APP_PARAM`) > Local config (`./.app.yaml`) > Global user config (`~/.config/app/config.yaml`) > Built-in defaults.
- **Strict Validation**: Always validate configuration via Pydantic (Python) or Zod (Node). Fail fast with line numbers and human-readable field errors on syntax errors.

## 5. Secure Programming & Cybersecurity
- **Localhost Only**: Local web servers MUST bind by default to `127.0.0.1` (or `::1`). NEVER bind by default to `0.0.0.0`. External binding requires an explicit `--host 0.0.0.0` flag.
- **Ephemeral Launch Token**: On web server startup, generate a cryptographically random token (`secrets.token_hex(32)`), print the URL to `stderr` as an OSC 8 clickable link (`http://127.0.0.1:8080/?token=...`), and automatically open the user's default browser (unless `--no-browser` is passed or running headless). Validate this token via `SameSite=Strict; HttpOnly` session cookie on all mutation endpoints.
- **W3C CSP & Security Headers**: Include on every HTTP response:
  ```http
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none';
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: no-referrer
  ```
- **Shared MIME-info Database (`shared-mime-info-spec`)**: Local web servers and file parsers MUST determine MIME types using standard MIME databases and emit verified `Content-Type` headers alongside `X-Content-Type-Options: nosniff`.
- **MITRE CWE Top 25**:
  - In Python: **NEVER USE `yaml.load()`**. Always use `yaml.safe_load()`.
  - Prevent Path Traversal (CWE-22) & Safe File URIs (`file-uri-spec` / RFC 8089): Always resolve paths with `os.path.realpath` / `fs.realpathSync` and verify they reside within the allowed directory jail. When parsing `file://` URIs, reject remote hostnames (must be empty or localhost). Web APIs MUST NOT accept arbitrary `file://` URIs to read filesystem files.
  - Prevent Command Injection (CWE-78): NEVER use `shell=True` or `exec()`. Pass arguments as discrete arrays (`subprocess.run(["cmd", "arg"])`).
- **POSIX Permissions**: Set mode `0700` (`rwx------`) on config directories and mode `0600` (`rw-------`) on config/preset files.
- **CSPRNG**: Use `secrets` (Python) or `node:crypto.randomBytes` (Node). NEVER use `random.random()` or `Math.random()` for security tokens. Use SHA-256 (never MD5/SHA-1).

## 6. Supply Chain Security & Packaging
- **OpenSSF Scorecard**: Pin all third-party GitHub Actions in `.github/workflows/` to full 40-character commit SHAs. Run dependency audits (`pip-audit` / `npm audit`) and secret scans (`gitleaks`) in CI.
- **SLSA Provenance & SBOM**: Generate SHA-256 `checksums.txt` and CycloneDX `sbom.json` on release.
- **Packaging**: Support `pipx run <tool>` via `pyproject.toml` (Python) or `npx <tool>` via `"bin"` in `package.json` (Node).

## 7. Testing & Quality Assurance
- **CLI Subprocess Tests**: Write tests that invoke the CLI entry point as a subprocess, verifying return codes (`0` vs `1`/`2`) and separation of `stdout` vs `stderr`.
- **Environment Isolation**: NEVER touch the developer's real `~/.config`. Redirect `XDG_CONFIG_HOME` to a temporary directory (`tmp_path` in pytest or `node:os.tmpdir()`).
- **Deterministic**: Mock all network calls and system clocks.

## 8. Observability & Error Handling
- **Exit Codes**: `0` = Success, `1` = Operational failure (e.g. invalid preset), `2` = CLI syntax/argument error, `130` = Interrupted by `Ctrl+C`.
- **Clean Errors**: By default, output concise, single-line error messages to `stderr`. NEVER display full stack traces unless `--debug` or `--verbose` is passed.

## 9. Portability & Cross-Platform
- **Universal UTF-8**: Always pass `encoding="utf-8"` on all file open/read/write calls.
- **Universal Timestamps**: Store and log dates in ISO 8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ`).
- **Agnostic Paths**: NEVER hardcode `/` or `\` in path strings. Use `pathlib.Path` (Python) or `node:path` (Node).
- **Line Endings**: Include `.gitattributes` with `* text=auto eol=lf`.

## 10. Process Lifecycle & Performance
- **Fast Startup**: Ensure `--help` and `--version` return in < 200ms. Lazily import heavy web frameworks (FastAPI/Hono) only within the command handlers that need them.
- **Streaming I/O**: Stream file processing in chunks rather than loading entire files into memory.
- **Clean Interruption**: Catch `SIGINT` (`Ctrl+C`) and `SIGTERM` gracefully, flush files, and exit with code `130` without throwing uncaught tracebacks.

## 11. Interoperability & Unix Composability
- **Stdin Support**: When a command takes a file argument, support `-` to read from `stdin` (`cat data.txt | mytool -`).
- **Machine-Readable Output**: Implement `--json` on data-producing commands, printing parseable JSON to `stdout` and diverting logs to `stderr`.
- **File Manager Integration (`org.freedesktop.FileManager1`)**: When offering "Reveal in Folder" (`--reveal`), verify display and session bus presence (`DBUS_SESSION_BUS_ADDRESS`), apply a <= 1000ms timeout guard, and fallback to printing the path if headless or D-Bus is unavailable.

## 12. Documentation & DX
- **README Structure**: Project Title, Badges (AGPLv3), 3-step Quickstart, CLI Flags Reference table, YAML configuration sample, AGPLv3 statement.
- **Security Policy**: Maintain a `SECURITY.md` defining private vulnerability reporting.
- **In-Code Comments & Docstrings**:
  - Every source file MUST have a module docstring immediately following the SPDX header summarizing architectural purpose.
  - Public classes, functions, and CLI commands MUST have structured docstrings (Google Style for Python, JSDoc for Node).
  - Lean typing: Do NOT duplicate type annotations in docstrings when static types are present in the signature.
  - "Why, Not What": Comments MUST explain architectural intent, business rules, edge cases, or security invariants (`# SECURITY:`). NEVER narrate obvious code syntax.
  - Standard tags: `TODO(user|#issue):`, `FIXME:`, `NOTE:`, `SECURITY:`. Commented-out dead code is STRICTLY PROHIBITED.
  - Linter suppressions (`# noqa`, `# shellcheck disable`) MUST include an inline explanation of why it is safe.
- **Comment Preservation & Hygiene**:
  - NEVER delete, truncate, or overwrite existing docstrings, explanatory comments, or license notices during refactoring.
  - NEVER generate conversational narrative filler (`# Now we do...`).
  - Keep docstring parameters and return contracts synchronized when modifying signatures.

## 13. Verification Discipline & "Proof-of-Fix" Protocol
- **Prohibition of Assumptive Completion**: NEVER declare a bug, feature, or refactoring "fixed" or "complete" based solely on reading code diffs or internal code inspection. Every fix claim MUST be validated by running the appropriate test, linter, or live verification script.
- **Dangling Reference Auditing**: Before completing any refactoring, renaming, or deletion of functions, classes, properties, or DOM element IDs, you MUST perform a repository-wide search (`grep_search`) to verify that zero orphaned call sites or dangling references remain.
- **Frontend Static Safety**: All JavaScript/TypeScript files and `<script>` blocks MUST have zero undeclared identifier errors. Web projects must maintain clean static audits (`no-undef`, `no-unused-vars`).
- **Closed-Loop Behavioral Verification**:
  - For UI Bugs: The agent must verify the interaction either via browser execution or simulated DOM event testing, confirming the handler executes completely without throwing unhandled exceptions.
  - For Path / File Discovery Bugs: The agent must verify the discovery logic against realistic filename variants and directory fixtures on disk (e.g. handling `{base}.ass` as well as `{base}_voice_titles.ass`).
  - For CLI / Process Bugs: The agent must invoke the CLI entry point as a subprocess, asserting return codes and stream separation.
- **Autonomous Remediation & Self-Healing Protocol (Zero User Intervention)**:
  - The human developer will NEVER manually edit boilerplate, inject licenses, or prompt the AI agent to fix standards compliance issues. It is the AI agent's sole engineering responsibility to maintain repository hygiene.
  - Whenever invoked on ANY task in this repository, the AI agent MUST autonomously run the compliance validator (`python3 scripts/check-compliance.py . --fix` or `check-standards`) during verification.
  - If any compliance errors, missing SPDX headers, unpinned GitHub Actions, or missing Global UI Error Boundaries are detected, the agent MUST automatically remediate them and verify clean status before declaring the task complete.

