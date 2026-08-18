from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


class GoldMOperatorLauncherTests(unittest.TestCase):
    def test_clickable_worker_launchers_delegate_to_reviewed_controller(self) -> None:
        expected_actions = {
            "disable-goldm-worker.bat": "Disable",
            "enable-goldm-worker.bat": "Enable",
            "status-goldm-worker.bat": "Status",
        }
        for filename, action in expected_actions.items():
            source = (SCRIPTS / filename).read_text(encoding="utf-8")
            self.assertIn("%~dp0control-goldm-worker.ps1", source)
            self.assertIn(f"-Action {action}", source)
            self.assertIn("pause", source.lower())
            self.assertNotIn("ScheduledTask", source)

    def test_worker_controller_uses_verified_module_barriers(self) -> None:
        source = (SCRIPTS / "control-goldm-worker.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Disable-GoldMScheduledTaskAndWait", source)
        self.assertIn("Start-GoldMScheduledTaskAndVerify", source)
        self.assertIn("Assert-GoldMScheduledTaskRunning", source)
        self.assertIn("Get-GoldMExactWorkerProcesses", source)
        self.assertIn("-ExpectedArguments $contract.Arguments", source)
        self.assertIn("Get-LegacyWorkerProcesses", source)
        self.assertIn("Stop-LegacyWorkerProcessesAndWait", source)
        self.assertIn('"Legacy PID :', source)
        self.assertIn("-Verb RunAs", source)

    def test_worker_identity_includes_the_scheduled_action_arguments(self) -> None:
        common = (SCRIPTS / "goldm-deployment-common.psm1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[string]$ExpectedArguments", common)
        self.assertIn("$candidate.CommandLine", common)
        self.assertIn("$ExpectedArguments.Trim()", common)
        self.assertIn("-ExpectedArguments $expectedArguments", common)

    def test_clickable_update_preserves_safe_update_pipeline(self) -> None:
        batch = (SCRIPTS / "update-goldm-bot.bat").read_text(encoding="utf-8")
        controller = (SCRIPTS / "update-goldm-bot.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("%~dp0update-goldm-bot.ps1", batch)
        self.assertIn("update-goldm-windows-vm.ps1", controller)
        self.assertIn("ExpectedCommit $expectedCommit", controller)
        self.assertIn('Read-Host "Type UPDATE', controller)
        self.assertIn("source-metadata.json", controller)
        self.assertIn("sealed-inputs", controller)
        self.assertIn('[string]$RemoteBranch = "main"', controller)
        self.assertIn("-Verb RunAs", controller)
        self.assertNotIn("git pull", controller.lower())


if __name__ == "__main__":
    unittest.main()
