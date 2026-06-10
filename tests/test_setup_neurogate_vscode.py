import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import setup_neurogate_vscode as setup


class NeuroGateConfigTests(unittest.TestCase):
    def test_detect_platform_marks_nixos_from_os_release(self):
        env = setup.PlatformProbe(
            system="Linux",
            release="6.12",
            os_release='ID="nixos"\nNAME="NixOS"\n',
            is_wsl=False,
        )

        info = setup.detect_platform(env)

        self.assertEqual(info.kind, "nixos")
        self.assertFalse(info.is_wsl)

    def test_extension_ids_are_the_current_marketplace_ids(self):
        self.assertEqual(
            [extension.extension_id for extension in setup.EXTENSIONS],
            [
                "rooveterinaryinc.roo-cline",
                "kilocode.kilo-code",
                "saoudrizwan.claude-dev",
            ],
        )

    def test_install_missing_deps_flag_is_available(self):
        args = setup.parse_args(["--install-missing-deps", "--non-interactive"])

        self.assertTrue(args.install_missing_deps)
        self.assertTrue(args.non_interactive)

    def test_wsl_bootstrap_installs_python_and_code_cli(self):
        script = setup.wsl_dependency_bootstrap_script()

        self.assertIn("install_python", script)
        self.assertIn("install_code", script)
        self.assertIn("command -v python3", script)
        self.assertIn("command -v code", script)

    def test_roocode_ripgrep_patch_adds_universal_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension_js = Path(tmp) / "extension.js"
            extension_js.write_text(
                'return await e("node_modules/@vscode/ripgrep/bin/")||'
                'await e("node_modules/vscode-ripgrep/bin")',
                encoding="utf-8",
            )

            result = setup.patch_roocode_ripgrep_file(extension_js, dry_run=False)
            patched = extension_js.read_text(encoding="utf-8")

            self.assertEqual(result, "patched")
            self.assertIn("node_modules/@vscode/ripgrep-universal/bin/", patched)
            self.assertTrue(list(Path(tmp).glob("extension.js.bak-neurogate-*")))

    def test_roocode_ripgrep_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension_js = Path(tmp) / "extension.js"
            extension_js.write_text(
                'await e("node_modules/@vscode/ripgrep-universal/bin/linux-x64/")',
                encoding="utf-8",
            )

            result = setup.patch_roocode_ripgrep_file(extension_js, dry_run=False)

            self.assertEqual(result, "already compatible")
            self.assertFalse(list(Path(tmp).glob("extension.js.bak-neurogate-*")))

    def test_webview_cache_cleanup_moves_cache_paths_to_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_data_dir = Path(tmp) / "Code"
            cache_dirs = [
                user_data_dir / "Service Worker",
                user_data_dir / "Code Cache",
                user_data_dir / "WebStorage" / "1" / "CacheStorage",
            ]
            for cache_dir in cache_dirs:
                cache_dir.mkdir(parents=True)
                (cache_dir / "marker").write_text("cache", encoding="utf-8")

            result = setup.move_vscode_webview_cache(user_data_dir, dry_run=False)

            self.assertIn("moved 3 cache path(s)", result)
            for cache_dir in cache_dirs:
                self.assertFalse(cache_dir.exists())

            backups = list((user_data_dir / "neurogate-webview-cache-backups").glob("*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "Service Worker" / "marker").exists())
            self.assertTrue((backups[0] / "Code Cache" / "marker").exists())
            self.assertTrue((backups[0] / "WebStorage" / "1" / "CacheStorage" / "marker").exists())

    def test_roocode_model_registry_patch_adds_neurogate_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension_js = Path(tmp) / "extension.js"
            extension_js.write_text(
                '$jt="gpt-5.1-codex-max",see={"gpt-5.4":{maxTokens:128e3}};'
                'getModel(){let e=this.options.apiModelId,r=e&&e in see?e:$jt}',
                encoding="utf-8",
            )

            result = setup.patch_roocode_model_registry_file(extension_js, model="gpt-5.5", dry_run=False)
            patched = extension_js.read_text(encoding="utf-8")

            self.assertEqual(result, "patched")
            self.assertIn('"gpt-5.5":', patched)
            self.assertIn('"reasoningEffort":"disable"', patched)
            self.assertIn('"supportsReasoningEffort":["disable"]', patched)
            self.assertTrue(list(Path(tmp).glob("extension.js.bak-neurogate-model-*")))

    def test_roocode_model_registry_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension_js = Path(tmp) / "extension.js"
            entry = setup.roocode_model_registry_entry("gpt-5.5")
            extension_js.write_text(
                f'$jt="gpt-5.1-codex-max",see={{{entry}}};',
                encoding="utf-8",
            )

            result = setup.patch_roocode_model_registry_file(extension_js, model="gpt-5.5", dry_run=False)

            self.assertEqual(result, "already compatible")
            self.assertFalse(list(Path(tmp).glob("extension.js.bak-neurogate-model-*")))

    def test_roocode_model_registry_patch_replaces_unsafe_existing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension_js = Path(tmp) / "extension.js"
            extension_js.write_text(
                '$jt="gpt-5.1-codex-max",see={"gpt-5.5":{maxTokens:128e3,'
                'supportsReasoningEffort:["none","low"],reasoningEffort:"none"}};',
                encoding="utf-8",
            )

            result = setup.patch_roocode_model_registry_file(extension_js, model="gpt-5.5", dry_run=False)
            patched = extension_js.read_text(encoding="utf-8")

            self.assertEqual(result, "patched")
            self.assertIn('"reasoningEffort":"disable"', patched)
            self.assertNotIn('reasoningEffort:"none"', patched)
            self.assertTrue(list(Path(tmp).glob("extension.js.bak-neurogate-model-*")))

    def test_roocode_import_contains_openai_native_neurogate_profile(self):
        payload = setup.build_roocode_import("sk-test", model="gpt-5.5")

        profile = payload["providerProfiles"]["apiConfigs"]["NeuroGate API"]

        self.assertEqual(payload["providerProfiles"]["currentApiConfigName"], "NeuroGate API")
        self.assertEqual(profile["apiProvider"], "openai-native")
        self.assertEqual(profile["openAiNativeBaseUrl"], setup.NEUROGATE_ROOCODE_BASE_URL)
        self.assertEqual(profile["openAiNativeApiKey"], "sk-test")
        self.assertEqual(profile["apiModelId"], "gpt-5.5")
        self.assertEqual(profile["reasoningEffort"], "disable")
        self.assertFalse(profile["enableResponsesReasoningSummary"])

    def test_cline_provider_settings_select_openai_compatible_provider(self):
        providers = setup.build_cline_providers(
            {
                "version": 1,
                "lastUsedProvider": "anthropic",
                "providers": {
                    "anthropic": {
                        "settings": {"provider": "anthropic", "model": "claude-sonnet-4-5"},
                        "updatedAt": "2026-01-01T00:00:00Z",
                        "tokenSource": "manual",
                    },
                },
            },
            api_key="sk-test",
            model="gpt-5.5",
        )

        entry = providers["providers"]["openai-compatible"]
        settings = entry["settings"]

        self.assertEqual(providers["version"], 1)
        self.assertEqual(providers["lastUsedProvider"], "openai-compatible")
        self.assertIn("anthropic", providers["providers"])
        self.assertEqual(settings["provider"], "openai-compatible")
        self.assertEqual(settings["baseUrl"], setup.NEUROGATE_BASE_URL)
        self.assertEqual(settings["apiKey"], "sk-test")
        self.assertEqual(settings["model"], "gpt-5.5")
        self.assertEqual(settings["protocol"], "openai-responses")
        self.assertEqual(settings["contextWindow"], 1_050_000)
        self.assertIn("tools", settings["capabilities"])
        self.assertEqual(entry["tokenSource"], "manual")

    def test_kilo_config_writes_openai_responses_provider_and_active_model(self):
        config = setup.merge_kilo_config(
            {"$schema": "https://app.kilo.ai/config.json"},
            api_key="sk-test",
            model="gpt-5.5",
        )

        provider = config["provider"]["openai"]
        model_config = provider["models"]["gpt-5.5"]

        self.assertEqual(config["model"], "openai/gpt-5.5")
        self.assertEqual(config["small_model"], "openai/gpt-5.5")
        self.assertEqual(config["subagent_model"], "openai/gpt-5.5")
        self.assertEqual(provider["npm"], "@ai-sdk/openai")
        self.assertEqual(provider["options"]["baseURL"], setup.NEUROGATE_BASE_URL)
        self.assertEqual(provider["options"]["apiKey"], "sk-test")
        self.assertEqual(model_config["name"], "gpt-5.5")
        self.assertEqual(model_config["ai_sdk_provider"], "openai")
        self.assertEqual(model_config["prompt"], "gpt55")
        self.assertTrue(model_config["tool_call"])

    def test_vscode_settings_wire_roo_auto_import_and_kilo_active_model(self):
        settings = setup.merge_vscode_settings(
            {"editor.fontSize": 14},
            roocode_import_path=Path("/tmp/neurogate/roocode.json"),
            model="gpt-5.5",
        )

        self.assertEqual(settings["editor.fontSize"], 14)
        self.assertEqual(
            settings["roo-cline.autoImportSettingsPath"],
            "/tmp/neurogate/roocode.json",
        )
        self.assertEqual(settings["kilo-code.new.model.providerID"], "openai")
        self.assertEqual(settings["kilo-code.new.model.modelID"], "gpt-5.5")

    def test_jsonc_reader_accepts_comments_and_trailing_commas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.jsonc"
            path.write_text(
                '{\n  // keep this readable\n  "editor.fontSize": 14,\n}\n',
                encoding="utf-8",
            )

            self.assertEqual(setup.read_jsonc_file(path), {"editor.fontSize": 14})


if __name__ == "__main__":
    unittest.main()
