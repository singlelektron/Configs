# Repository guidance

- Keep shared settings in `config/`; add platform differences only when needed.
- Prefer Neovim built-ins and small, maintained plugins. Preserve normal Vim keys.
- Read existing configuration before migrating; use `scripts/deploy.py` so originals remain recoverable.
- Keep local overrides, credentials, SSH settings, AI authentication/history and editor state outside Git.
- Never copy a complete home configuration directory into this repository.
- Run `bash scripts/check.sh` after config/deployment changes. Test changed LSP or plugin behavior with real tools when available.
- Report macOS and Linux validation separately; headless tests do not verify fonts, clipboard transport or GUI behavior.
- Do not enable or replace desktop sessions when adding future Niri files.
