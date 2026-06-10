# VS Code - NeuroGate Extensions

Installs and configures these VS Code extensions:

- RooCode: `rooveterinaryinc.roo-cline`
- Kilo Code: `kilocode.kilo-code`
- Cline: `saoudrizwan.claude-dev`

The script configures NeuroGate through the OpenAI Responses API for GPT models:

- OpenAI-compatible base URL: `https://api.neurogate.space/v1`
- RooCode native base URL: `https://api.neurogate.space`
- Default model: `gpt-5.5`
- RooCode provider: `openai-native`
- Kilo Code provider: `openai` with `@ai-sdk/openai`
- Cline protocol: `openai-responses`

RooCode and Kilo Code must not use the generic Chat Completions/OpenAI-compatible route for this NeuroGate GPT provider; that route can fail with `upstream_rejected`.

The setup also patches RooCode's bundled compatibility gaps:

- ripgrep lookup for newer VS Code builds that ship `@vscode/ripgrep-universal` instead of the older `@vscode/ripgrep` package. This prevents RooCode from failing before the first API request with `Could not find ripgrep binary`, which is common with immutable VS Code installs such as NixOS.
- OpenAI native model registry, so RooCode accepts the NeuroGate default `gpt-5.5` instead of falling back to its bundled default model. Without this, RooCode can send `gpt-5.1-codex-max` and NeuroGate returns `Unknown model`.

## Quick install

Linux, NixOS, Ubuntu, WSL, macOS:

```bash
curl -fsSL https://github.com/OlegGorsky/VS-Code-NeuroGate-Extensions/raw/main/i | sh
```

Windows PowerShell:

```powershell
irm https://github.com/OlegGorsky/VS-Code-NeuroGate-Extensions/raw/main/w | iex
```

The bootstrap installers download `setup_neurogate_vscode.py`, install Python 3 when it is missing, then run the setup with `--install-missing-deps`.

## Manual run

```bash
python3 setup_neurogate_vscode.py --install-missing-deps
```

Non-interactive mode:

```bash
NEUROGATE_API_KEY='sk-...' python3 setup_neurogate_vscode.py --install-missing-deps --non-interactive
```

Dry-run without touching files:

```bash
NEUROGATE_API_KEY='sk-test' python3 setup_neurogate_vscode.py --install-missing-deps --dry-run --skip-api-check --non-interactive
```

On Windows, the script also checks WSL and runs the same setup inside the default WSL distro. With `--install-missing-deps`, it tries to install `python3` and the VS Code CLI inside WSL first. Use `--skip-wsl` to disable that or `--wsl-distro NAME` to target a distro.

## Dependency install

- Python 3: installed by `i`/`w` when missing.
- VS Code CLI: installed by `setup_neurogate_vscode.py --install-missing-deps` when missing.
- NixOS: uses transient `nix-shell` for Python when needed and tries `nix profile install --impure nixpkgs#vscode` for VS Code.
- Ubuntu/Debian: uses Microsoft apt repository for VS Code.
- macOS: uses Homebrew.
- Windows: uses `winget`, then `choco` fallback.

## Files written

- VS Code settings: platform-specific `Code/User/settings.json`
- RooCode auto-import profile: user config dir `neurogate-vscode/roocode-settings.json`
- Kilo Code config: `~/.config/kilo/kilo.jsonc`
- Cline provider settings: `~/.cline/data/settings/providers.json`

Existing files are backed up as `*.bak-YYYYmmdd-HHMMSS` before changes.

The API check calls both `/v1/models` and a minimal streaming `/v1/responses` request, so a bad key or unsupported wire protocol is caught during setup.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
