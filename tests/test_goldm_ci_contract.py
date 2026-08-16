from pathlib import Path
import unittest


class GoldMCiContractTests(unittest.TestCase):
    def test_release_workflow_cannot_omit_new_tests(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "goldm-core-v2.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('unittest discover -s tests -p "test_*.py"', workflow)
        self.assertNotIn("productionTestModules", workflow)

    def test_actions_are_immutable_and_mt5_requires_dedicated_runner(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "goldm-core-v2.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("runs-on: [self-hosted, Windows, X64, goldm-mt5]", workflow)
        for action in ("actions/checkout@", "actions/setup-python@", "actions/upload-artifact@"):
            for line in (line.strip() for line in workflow.splitlines()):
                if f"uses: {action}" not in line:
                    continue
                revision = line.split("@", 1)[1].split()[0]
                self.assertRegex(revision, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
