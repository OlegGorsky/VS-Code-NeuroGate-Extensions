# NeuroGate VS Code setup

Installs and configures these VS Code extensions:

- RooCode: `rooveterinaryinc.roo-cline`
- Kilo Code: `kilocode.kilo-code`
- Cline: `saoudrizwan.claude-dev`

The script configures NeuroGate as an OpenAI-compatible API:

- Base URL: `https://api.neurogate.space/v1`
- Default model: `gpt-5.5`

## Run

```bash
python3 setup_neurogate_vscode.py
```

Non-interactive mode:

```bash
NEUROGATE_API_KEY='sk-...' python3 setup_neurogate_vscode.py --non-interactive
```

Dry-run without touching files:

```bash
NEUROGATE_API_KEY='sk-test' python3 setup_neurogate_vscode.py --dry-run --skip-api-check --non-interactive
```

On Windows, the script also checks WSL and runs the same setup inside the default WSL distro when `python3` and `code` are available there. Use `--skip-wsl` to disable that or `--wsl-distro NAME` to target a distro.

## Files written

- VS Code settings: platform-specific `Code/User/settings.json`
- RooCode auto-import profile: user config dir `neurogate-vscode/roocode-settings.json`
- Kilo Code config: `~/.config/kilo/kilo.jsonc`
- Cline provider settings: `~/.cline/data/settings/providers.json`

Existing files are backed up as `*.bak-YYYYmmdd-HHMMSS` before changes.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
