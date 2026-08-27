import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class DefaultPublishContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.workflow_text = (SKILL_ROOT / "references" / "workflow.md").read_text(
            encoding="utf-8"
        )

    def test_skill_declares_publish_as_opt_out_default(self):
        self.assertIn("Publishing is opt-out, not opt-in", self.skill_text)
        self.assertIn("Publish the R2 package and refresh the website by default", self.skill_text)
        self.assertIn("不发布", self.skill_text)

    def test_default_pipeline_includes_public_verification(self):
        self.assertIn("-> publish package to R2", self.skill_text)
        self.assertIn("-> verify the package and public source URLs", self.skill_text)
        self.assertIn("/wiki/source/<slug>", self.skill_text)

    def test_workflow_does_not_require_publish_keyword(self):
        self.assertIn("Do not infer an opt-out from the absence of the word “发布”", self.workflow_text)
        self.assertNotIn("then publishes if requested", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
