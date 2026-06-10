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

    def test_roocode_import_contains_openai_compatible_neurogate_profile(self):
        payload = setup.build_roocode_import("sk-test", model="gpt-5.5")

        profile = payload["providerProfiles"]["apiConfigs"]["NeuroGate API"]

        self.assertEqual(payload["providerProfiles"]["currentApiConfigName"], "NeuroGate API")
        self.assertEqual(profile["apiProvider"], "openai")
        self.assertEqual(profile["openAiBaseUrl"], setup.NEUROGATE_BASE_URL)
        self.assertEqual(profile["openAiApiKey"], "sk-test")
        self.assertEqual(profile["openAiModelId"], "gpt-5.5")
        self.assertEqual(profile["openAiCustomModelInfo"]["contextWindow"], 1_050_000)

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

    def test_kilo_config_writes_openai_compatible_provider_and_active_model(self):
        config = setup.merge_kilo_config(
            {"$schema": "https://app.kilo.ai/config.json"},
            api_key="sk-test",
            model="gpt-5.5",
        )

        provider = config["provider"]["openai-compatible"]

        self.assertEqual(config["model"], "openai-compatible/gpt-5.5")
        self.assertEqual(provider["options"]["baseURL"], setup.NEUROGATE_BASE_URL)
        self.assertEqual(provider["options"]["apiKey"], "sk-test")
        self.assertEqual(provider["models"]["gpt-5.5"]["name"], "gpt-5.5")

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
        self.assertEqual(settings["kilo-code.new.model.providerID"], "openai-compatible")
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
