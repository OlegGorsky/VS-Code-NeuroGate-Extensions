#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROVIDER_NAME = "NeuroGate API"
NEUROGATE_BASE_URL = "https://api.neurogate.space/v1"
DEFAULT_MODEL = "gpt-5.5"
MODEL_CONTEXT_WINDOW = 1_050_000
MODEL_MAX_TOKENS = 128_000


@dataclass(frozen=True)
class Extension:
    name: str
    extension_id: str


EXTENSIONS = [
    Extension("RooCode", "rooveterinaryinc.roo-cline"),
    Extension("Kilo Code", "kilocode.kilo-code"),
    Extension("Cline", "saoudrizwan.claude-dev"),
]


@dataclass(frozen=True)
class PlatformProbe:
    system: str
    release: str
    os_release: str
    is_wsl: bool


@dataclass(frozen=True)
class PlatformInfo:
    kind: str
    system: str
    release: str
    is_wsl: bool


@dataclass(frozen=True)
class CodeCli:
    command: str
    flavor: str


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    platform_info = detect_platform(current_platform_probe())
    print(f"System: {platform_info.kind} ({platform_info.system} {platform_info.release})")

    code_cli = find_code_cli(args.code_bin)
    if not code_cli and args.install_missing_deps:
        install_missing_system_dependencies(platform_info, dry_run=args.dry_run)
        code_cli = find_code_cli(args.code_bin)
    if not code_cli:
        print("ERROR: VS Code CLI was not found. Install VS Code or add 'code' to PATH.", file=sys.stderr)
        return 2

    print(f"VS Code CLI: {code_cli.command}")
    install_missing_extensions(code_cli, EXTENSIONS, dry_run=args.dry_run)

    api_key = read_api_key(args)
    if not args.skip_api_check:
        models = verify_api_key(api_key, model=args.model, timeout=args.api_timeout)
        print("NeuroGate Responses API check: OK")
        if models:
            preview = ", ".join(models[:10])
            suffix = "" if len(models) <= 10 else f" (+{len(models) - 10} more)"
            print(f"Models: {preview}{suffix}")
    else:
        print("NeuroGate API check: skipped")

    paths = resolve_paths(code_cli.flavor)
    configure_extensions(paths, api_key=api_key, model=args.model, dry_run=args.dry_run)

    if platform_info.kind == "windows" and not args.skip_wsl:
        configure_wsl(args, api_key=api_key, install_missing_deps=args.install_missing_deps)

    print("Finished. Restart VS Code to let the extensions reload their settings.")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install RooCode, Kilo Code, and Cline VS Code extensions and configure NeuroGate API.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id to configure. Default: {DEFAULT_MODEL}")
    parser.add_argument("--api-key", help="NeuroGate API key. Prefer NEUROGATE_API_KEY for scripts.")
    parser.add_argument("--api-key-stdin", action="store_true", help="Read the API key from stdin.")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt for the API key.")
    parser.add_argument("--skip-api-check", action="store_true", help="Do not call /v1/models and /v1/responses.")
    parser.add_argument("--api-timeout", type=int, default=60, help="API check timeout in seconds.")
    parser.add_argument("--code-bin", help="Path or command name for VS Code CLI.")
    parser.add_argument("--install-missing-deps", action="store_true", help="Install missing system dependencies when possible.")
    parser.add_argument("--skip-wsl", action="store_true", help="On Windows, do not configure WSL.")
    parser.add_argument("--wsl-distro", help="On Windows, configure this WSL distribution.")
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without writing files.")
    return parser.parse_args(argv)


def current_platform_probe() -> PlatformProbe:
    os_release = ""
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        try:
            os_release = os_release_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            os_release = ""

    is_wsl = False
    proc_release = Path("/proc/sys/kernel/osrelease")
    if proc_release.exists():
        try:
            is_wsl = "microsoft" in proc_release.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            is_wsl = False

    return PlatformProbe(
        system=platform.system(),
        release=platform.release(),
        os_release=os_release,
        is_wsl=is_wsl,
    )


def detect_platform(probe: PlatformProbe) -> PlatformInfo:
    system = probe.system.lower()
    os_release = probe.os_release.lower()
    if system == "windows":
        kind = "windows"
    elif system == "darwin":
        kind = "macos"
    elif system == "linux" and probe.is_wsl:
        kind = "wsl"
    elif system == "linux" and re.search(r'^id="?nixos"?$', os_release, flags=re.MULTILINE):
        kind = "nixos"
    elif system == "linux" and re.search(r'^id="?ubuntu"?$', os_release, flags=re.MULTILINE):
        kind = "ubuntu"
    elif system == "linux":
        kind = "linux"
    else:
        kind = system or "unknown"
    return PlatformInfo(kind=kind, system=probe.system, release=probe.release, is_wsl=probe.is_wsl)


def find_code_cli(explicit: str | None = None) -> CodeCli | None:
    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.append((explicit, guess_code_flavor(explicit)))
    candidates.extend(
        [
            ("code", "code"),
            ("code-insiders", "code-insiders"),
            ("codium", "codium"),
            ("vscodium", "codium"),
        ],
    )

    if platform.system().lower() == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        if local_app_data:
            candidates.extend(
                [
                    (str(Path(local_app_data) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"), "code"),
                    (
                        str(Path(local_app_data) / "Programs" / "Microsoft VS Code Insiders" / "bin" / "code-insiders.cmd"),
                        "code-insiders",
                    ),
                ],
            )
        if program_files:
            candidates.append((str(Path(program_files) / "Microsoft VS Code" / "bin" / "code.cmd"), "code"))

    for command, flavor in candidates:
        if Path(command).exists() or shutil.which(command):
            return CodeCli(command=command, flavor=flavor)
    return None


def install_missing_system_dependencies(platform_info: PlatformInfo, *, dry_run: bool) -> None:
    commands = vscode_install_commands(platform_info)
    if not commands:
        raise RuntimeError(f"Automatic VS Code installation is not supported for {platform_info.kind}.")

    print("VS Code CLI was not found. Installing VS Code for this system.")
    for command in commands:
        print(f"Dependency command: {format_command(command)}")
        if not dry_run:
            run_checked(command, timeout=1800)


def vscode_install_commands(platform_info: PlatformInfo) -> list[list[str]]:
    if platform_info.kind == "windows":
        if shutil.which("winget"):
            return [
                [
                    "winget",
                    "install",
                    "-e",
                    "--id",
                    "Microsoft.VisualStudioCode",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
            ]
        if shutil.which("choco"):
            return [["choco", "install", "vscode", "-y"]]
        return []

    if platform_info.kind == "macos":
        if shutil.which("brew"):
            return [["brew", "install", "--cask", "visual-studio-code"]]
        return []

    if platform_info.kind == "nixos":
        if shutil.which("nix"):
            return [
                [
                    "env",
                    "NIXPKGS_ALLOW_UNFREE=1",
                    "nix",
                    "--extra-experimental-features",
                    "nix-command",
                    "--extra-experimental-features",
                    "flakes",
                    "profile",
                    "install",
                    "--impure",
                    "nixpkgs#vscode",
                ],
            ]
        if shutil.which("nix-env"):
            return [["env", "NIXPKGS_ALLOW_UNFREE=1", "nix-env", "-iA", "nixpkgs.vscode"]]
        return []

    if shutil.which("apt-get"):
        return [
            ["sh", "-lc", "sudo apt-get update && sudo apt-get install -y wget gpg ca-certificates"],
            [
                "sh",
                "-lc",
                "wget -qO- https://packages.microsoft.com/keys/microsoft.asc | "
                "gpg --dearmor > /tmp/packages.microsoft.gpg && "
                "sudo install -D -o root -g root -m 644 /tmp/packages.microsoft.gpg /usr/share/keyrings/packages.microsoft.gpg",
            ],
            [
                "sh",
                "-lc",
                'printf "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/packages.microsoft.gpg] '
                'https://packages.microsoft.com/repos/code stable main\\n" | '
                "sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null",
            ],
            ["sh", "-lc", "sudo apt-get update && sudo apt-get install -y code"],
        ]

    if shutil.which("dnf"):
        return [
            ["sh", "-lc", "sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc"],
            [
                "sh",
                "-lc",
                "printf '[code]\\nname=Visual Studio Code\\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\\n"
                "enabled=1\\nautorefresh=1\\ntype=rpm-md\\ngpgcheck=1\\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\\n' | "
                "sudo tee /etc/yum.repos.d/vscode.repo >/dev/null",
            ],
            ["sudo", "dnf", "install", "-y", "code"],
        ]

    if shutil.which("yum"):
        return [
            ["sh", "-lc", "sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc"],
            [
                "sh",
                "-lc",
                "printf '[code]\\nname=Visual Studio Code\\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\\n"
                "enabled=1\\nautorefresh=1\\ntype=rpm-md\\ngpgcheck=1\\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\\n' | "
                "sudo tee /etc/yum.repos.d/vscode.repo >/dev/null",
            ],
            ["sudo", "yum", "install", "-y", "code"],
        ]

    if shutil.which("zypper"):
        return [
            ["sh", "-lc", "sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc"],
            [
                "sudo",
                "zypper",
                "--non-interactive",
                "addrepo",
                "https://packages.microsoft.com/yumrepos/vscode",
                "vscode",
            ],
            ["sudo", "zypper", "--non-interactive", "install", "code"],
        ]

    if shutil.which("pacman"):
        return [["sudo", "pacman", "-Sy", "--needed", "--noconfirm", "code"]]

    return []


def format_command(command: list[str]) -> str:
    return " ".join(quote_command_part(part) for part in command)


def quote_command_part(part: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./#-]+", part):
        return part
    return "'" + part.replace("'", "'\"'\"'") + "'"


def guess_code_flavor(command: str) -> str:
    lower = command.lower()
    if "insider" in lower:
        return "code-insiders"
    if "codium" in lower:
        return "codium"
    return "code"


def run_checked(command: list[str], *, input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def install_missing_extensions(code_cli: CodeCli, extensions: Iterable[Extension], *, dry_run: bool) -> None:
    installed = list_installed_extensions(code_cli)
    for extension in extensions:
        if extension.extension_id.lower() in installed:
            print(f"Extension already installed: {extension.name} ({extension.extension_id})")
            continue

        print(f"Installing extension: {extension.name} ({extension.extension_id})")
        if dry_run:
            continue
        try:
            run_checked([code_cli.command, "--install-extension", extension.extension_id], timeout=600)
        except subprocess.CalledProcessError as exc:
            message = sanitize_secret((exc.stderr or exc.stdout or "").strip(), "")
            raise RuntimeError(f"Failed to install {extension.extension_id}: {message}") from exc


def list_installed_extensions(code_cli: CodeCli) -> set[str]:
    try:
        result = run_checked([code_cli.command, "--list-extensions"], timeout=120)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"Failed to list VS Code extensions with {code_cli.command}") from exc
    return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}


def read_api_key(args: argparse.Namespace) -> str:
    candidates = [
        args.api_key,
        os.environ.get("NEUROGATE_API_KEY"),
        os.environ.get("OPENAI_API_KEY"),
    ]
    if args.api_key_stdin:
        candidates.insert(0, sys.stdin.readline())

    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()

    if args.non_interactive:
        raise RuntimeError("API key is missing. Set NEUROGATE_API_KEY or pass --api-key.")

    api_key = getpass.getpass("NeuroGate API key: ").strip()
    if not api_key:
        raise RuntimeError("API key is empty.")
    return api_key


def verify_api_key(api_key: str, *, model: str, timeout: int) -> list[str]:
    request = urllib.request.Request(
        f"{NEUROGATE_BASE_URL}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        detail = sanitize_secret(detail, api_key)
        raise RuntimeError(f"NeuroGate API check failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        detail = sanitize_secret(str(exc), api_key)
        raise RuntimeError(f"NeuroGate API check failed: {detail}") from exc

    models = []
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                models.append(item["id"])
    if not models:
        raise RuntimeError("NeuroGate API responded, but no models were found.")
    verify_responses_api(api_key, model=model, timeout=timeout)
    return sorted(set(models))


def verify_responses_api(api_key: str, *, model: str, timeout: int) -> None:
    body = json.dumps(
        {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "ping"}],
                },
            ],
            "max_output_tokens": 16,
            "stream": True,
            "store": False,
        },
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{NEUROGATE_BASE_URL}/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        detail = sanitize_secret(detail, api_key)
        raise RuntimeError(f"NeuroGate Responses API check failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        detail = sanitize_secret(str(exc), api_key)
        raise RuntimeError(f"NeuroGate Responses API check failed: {detail}") from exc


def sanitize_secret(text: str, api_key: str) -> str:
    clean = text.replace(api_key, "[redacted]") if api_key else text
    clean = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", clean)
    clean = re.sub(r"sk-[A-Za-z0-9_*.-]{8,}", "sk-[redacted]", clean)
    return clean


def resolve_paths(code_flavor: str) -> dict[str, Path]:
    home = Path.home()
    config_root = user_config_root()
    return {
        "vscode_settings": vscode_user_settings_path(code_flavor),
        "roocode_import": config_root / "neurogate-vscode" / "roocode-settings.json",
        "kilo_config": kilo_config_path(home),
        "cline_providers": cline_provider_settings_path(home),
    }


def user_config_root() -> Path:
    if platform.system().lower() == "windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    if platform.system().lower() == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def vscode_user_settings_path(code_flavor: str) -> Path:
    system = platform.system().lower()
    if code_flavor == "code-insiders":
        app_name = "Code - Insiders"
    elif code_flavor == "codium":
        app_name = "VSCodium"
    else:
        app_name = "Code"

    if system == "windows":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / app_name / "User" / "settings.json"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name / "User" / "settings.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / app_name / "User" / "settings.json"


def kilo_config_path(home: Path) -> Path:
    if os.environ.get("KILO_CONFIG"):
        return Path(os.environ["KILO_CONFIG"])
    if os.environ.get("KILO_CONFIG_DIR"):
        return Path(os.environ["KILO_CONFIG_DIR"]) / "kilo.jsonc"
    return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "kilo" / "kilo.jsonc"


def cline_dir(home: Path) -> Path:
    return Path(os.environ.get("CLINE_DIR", home / ".cline"))


def cline_data_dir(home: Path) -> Path:
    return Path(os.environ.get("CLINE_DATA_DIR", cline_dir(home) / "data"))


def cline_provider_settings_path(home: Path) -> Path:
    if os.environ.get("CLINE_PROVIDER_SETTINGS_PATH"):
        return Path(os.environ["CLINE_PROVIDER_SETTINGS_PATH"])
    return cline_data_dir(home) / "settings" / "providers.json"


def configure_extensions(paths: dict[str, Path], *, api_key: str, model: str, dry_run: bool) -> None:
    roocode_payload = build_roocode_import(api_key, model=model)
    vscode_settings = merge_vscode_settings(
        read_jsonc_file(paths["vscode_settings"]),
        roocode_import_path=paths["roocode_import"],
        model=model,
    )
    kilo_config = merge_kilo_config(read_jsonc_file(paths["kilo_config"]), api_key=api_key, model=model)
    cline_providers = build_cline_providers(
        read_jsonc_file(paths["cline_providers"]),
        api_key=api_key,
        model=model,
    )

    writes = [
        (paths["roocode_import"], roocode_payload, 0o600),
        (paths["vscode_settings"], vscode_settings, 0o644),
        (paths["kilo_config"], kilo_config, 0o600),
        (paths["cline_providers"], cline_providers, 0o600),
    ]
    for path, payload, mode in writes:
        if dry_run:
            print(f"Would write: {path}")
        else:
            write_json_file(path, payload, mode=mode)
            print(f"Wrote: {path}")


def build_model_info() -> dict[str, Any]:
    return {
        "maxTokens": MODEL_MAX_TOKENS,
        "contextWindow": MODEL_CONTEXT_WINDOW,
        "supportsImages": True,
        "supportsPromptCache": True,
        "supportsReasoningEffort": ["none", "minimal", "low", "medium", "high", "xhigh"],
        "supportedParameters": ["max_tokens", "reasoning", "include_reasoning"],
        "inputPrice": 5,
        "outputPrice": 30,
        "cacheReadsPrice": 0.5,
        "description": "NeuroGate GPT model via OpenAI Responses API.",
    }


def build_roocode_import(api_key: str, *, model: str) -> dict[str, Any]:
    profile = {
        "id": "neurogate-api",
        "apiProvider": "openai-native",
        "apiModelId": model,
        "openAiNativeApiKey": api_key,
        "openAiNativeBaseUrl": NEUROGATE_BASE_URL,
    }
    return {
        "providerProfiles": {
            "currentApiConfigName": PROVIDER_NAME,
            "apiConfigs": {PROVIDER_NAME: profile},
        },
        "globalSettings": {
            "welcomeViewCompleted": True,
        },
    }


def build_cline_providers(existing: dict[str, Any], *, api_key: str, model: str) -> dict[str, Any]:
    provider_id = "openai-compatible"
    payload = dict(existing)
    providers = dict(payload.get("providers") or {})
    previous_entry = providers.get(provider_id) if isinstance(providers.get(provider_id), dict) else {}
    previous_settings = previous_entry.get("settings") if isinstance(previous_entry, dict) else {}
    settings = dict(previous_settings) if isinstance(previous_settings, dict) else {}
    settings.update(
        {
            "provider": provider_id,
            "apiKey": api_key,
            "baseUrl": NEUROGATE_BASE_URL,
            "model": model,
            "protocol": "openai-responses",
            "maxTokens": MODEL_MAX_TOKENS,
            "contextWindow": MODEL_CONTEXT_WINDOW,
            "capabilities": ["reasoning", "prompt-cache", "streaming", "tools", "vision"],
        },
    )
    providers[provider_id] = {
        "settings": settings,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokenSource": "manual",
    }
    payload["version"] = 1
    payload["lastUsedProvider"] = provider_id
    payload["providers"] = providers
    return payload


def merge_kilo_config(existing: dict[str, Any], *, api_key: str, model: str) -> dict[str, Any]:
    config = dict(existing)
    config.setdefault("$schema", "https://app.kilo.ai/config.json")

    provider = dict(config.get("provider") or {})
    openai = dict(provider.get("openai") or {})
    options = dict(openai.get("options") or {})
    options.update({"baseURL": NEUROGATE_BASE_URL, "apiKey": api_key})
    models = dict(openai.get("models") or {})
    models[model] = {
        "id": model,
        "name": model,
        "prompt": "gpt55",
        "ai_sdk_provider": "openai",
        "reasoning": True,
        "tool_call": True,
        "limit": {
            "context": MODEL_CONTEXT_WINDOW,
            "output": MODEL_MAX_TOKENS,
        },
        "modalities": {
            "input": ["text", "image"],
            "output": ["text"],
        },
    }
    openai.update(
        {
            "name": PROVIDER_NAME,
            "npm": "@ai-sdk/openai",
            "options": options,
            "models": models,
        },
    )
    provider["openai"] = openai
    config["provider"] = provider
    config["model"] = f"openai/{model}"
    config["small_model"] = f"openai/{model}"
    config["subagent_model"] = f"openai/{model}"
    return config


def merge_vscode_settings(existing: dict[str, Any], *, roocode_import_path: Path, model: str) -> dict[str, Any]:
    settings = dict(existing)
    settings["roo-cline.autoImportSettingsPath"] = str(roocode_import_path)
    settings["kilo-code.new.model.providerID"] = "openai"
    settings["kilo-code.new.model.modelID"] = model
    return settings


def read_jsonc_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    stripped = strip_jsonc(text)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse JSON/JSONC file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return payload


def strip_jsonc(text: str) -> str:
    chars: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            chars.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            chars.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        chars.append(char)
        i += 1

    without_comments = "".join(chars)
    return re.sub(r",\s*([}\]])", r"\1", without_comments)


def write_json_file(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists():
        old_body = path.read_text(encoding="utf-8", errors="ignore")
        if old_body == body:
            set_private_mode(path, mode)
            return
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        set_private_mode(backup, min(mode, 0o600))

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(body)
        os.replace(tmp_name, path)
        set_private_mode(path, mode)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def set_private_mode(path: Path, mode: int) -> None:
    if os.name != "nt":
        try:
            path.chmod(mode)
        except OSError:
            pass


def configure_wsl(args: argparse.Namespace, *, api_key: str, install_missing_deps: bool) -> None:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        print("WSL: not found")
        return

    base_args = [wsl]
    if args.wsl_distro:
        base_args.extend(["--distribution", args.wsl_distro])

    if install_missing_deps:
        ensure_wsl_dependencies(base_args, dry_run=args.dry_run)

    ready_args = base_args + ["--", "sh", "-lc", "command -v python3 >/dev/null && command -v code >/dev/null && printf ready"]
    try:
        ready = run_checked(ready_args, timeout=30)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        print("WSL: found, but python3 or code CLI is not ready in the target distro; skipped")
        return

    if ready.stdout.strip() != "ready":
        print("WSL: target distro is not ready; skipped")
        return

    print("WSL: configuring target distro")
    if args.dry_run:
        return

    script = Path(__file__).read_text(encoding="utf-8")
    payload = {
        "script": base64.b64encode(script.encode("utf-8")).decode("ascii"),
        "api_key": api_key,
        "args": [
            "--non-interactive",
            "--skip-wsl",
            "--model",
            args.model,
            *("--skip-api-check".split() if args.skip_api_check else []),
        ],
    }
    loader = (
        "import base64,json,os,runpy,sys,tempfile;"
        "p=json.load(sys.stdin);"
        "fd,path=tempfile.mkstemp(prefix='neurogate-vscode-',suffix='.py');"
        "os.write(fd,base64.b64decode(p['script']));os.close(fd);"
        "os.environ['NEUROGATE_API_KEY']=p['api_key'];"
        "sys.argv=[path]+p['args'];"
        "runpy.run_path(path,run_name='__main__')"
    )
    run_checked(base_args + ["--", "python3", "-c", loader], input_text=json.dumps(payload), timeout=900)


def ensure_wsl_dependencies(base_args: list[str], *, dry_run: bool) -> None:
    print("WSL: ensuring python3 and code CLI")
    if dry_run:
        print("WSL: would install python3 and VS Code CLI when missing")
        return
    try:
        run_checked(base_args + ["--", "sh", "-lc", wsl_dependency_bootstrap_script()], timeout=1800)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        output = ""
        if isinstance(exc, subprocess.CalledProcessError):
            output = (exc.stderr or exc.stdout or "").strip()
        print(f"WSL: dependency install failed; skipped ({sanitize_secret(output, '')})")


def wsl_dependency_bootstrap_script() -> str:
    return r"""
set -eu
if command -v python3 >/dev/null 2>&1 && command -v code >/dev/null 2>&1; then
  exit 0
fi
as_root() {
  if [ "$(id -u)" = "0" ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "sudo is required inside WSL" >&2
    return 1
  fi
}
install_python() {
  command -v python3 >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y python3 curl ca-certificates gpg
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y python3 curl ca-certificates
  elif command -v yum >/dev/null 2>&1; then
    as_root yum install -y python3 curl ca-certificates
  elif command -v zypper >/dev/null 2>&1; then
    as_root zypper --non-interactive install python3 curl ca-certificates
  elif command -v pacman >/dev/null 2>&1; then
    as_root pacman -Sy --needed --noconfirm python curl ca-certificates
  elif command -v apk >/dev/null 2>&1; then
    as_root apk add python3 curl ca-certificates
  elif command -v nix >/dev/null 2>&1; then
    env NIXPKGS_ALLOW_UNFREE=1 nix --extra-experimental-features nix-command --extra-experimental-features flakes profile install --impure nixpkgs#python3
  fi
}
install_code() {
  command -v code >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y wget gpg ca-certificates
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /tmp/packages.microsoft.gpg
    as_root install -D -o root -g root -m 644 /tmp/packages.microsoft.gpg /usr/share/keyrings/packages.microsoft.gpg
    printf "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main\n" | as_root tee /etc/apt/sources.list.d/vscode.list >/dev/null
    as_root apt-get update
    as_root apt-get install -y code
  elif command -v dnf >/dev/null 2>&1; then
    as_root rpm --import https://packages.microsoft.com/keys/microsoft.asc
    printf "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\nautorefresh=1\ntype=rpm-md\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\n" | as_root tee /etc/yum.repos.d/vscode.repo >/dev/null
    as_root dnf install -y code
  elif command -v yum >/dev/null 2>&1; then
    as_root rpm --import https://packages.microsoft.com/keys/microsoft.asc
    printf "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\nautorefresh=1\ntype=rpm-md\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\n" | as_root tee /etc/yum.repos.d/vscode.repo >/dev/null
    as_root yum install -y code
  elif command -v zypper >/dev/null 2>&1; then
    as_root rpm --import https://packages.microsoft.com/keys/microsoft.asc
    as_root zypper --non-interactive addrepo https://packages.microsoft.com/yumrepos/vscode vscode || true
    as_root zypper --non-interactive install code
  elif command -v pacman >/dev/null 2>&1; then
    as_root pacman -Sy --needed --noconfirm code
  elif command -v nix >/dev/null 2>&1; then
    env NIXPKGS_ALLOW_UNFREE=1 nix --extra-experimental-features nix-command --extra-experimental-features flakes profile install --impure nixpkgs#vscode
  fi
}
install_python
install_code
command -v python3 >/dev/null 2>&1 && command -v code >/dev/null 2>&1
"""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {sanitize_secret(str(exc), os.environ.get('NEUROGATE_API_KEY', ''))}", file=sys.stderr)
        raise SystemExit(1)
