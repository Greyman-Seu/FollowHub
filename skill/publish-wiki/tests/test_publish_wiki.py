import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "publish_wiki.py"
SPEC = importlib.util.spec_from_file_location("publish_wiki", MODULE_PATH)
publish_wiki = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(publish_wiki)


class PublishWikiTests(unittest.TestCase):
    def test_parser_defaults_to_online_page_publish(self):
        parser = publish_wiki.build_parser()
        args = parser.parse_args([
            "--wiki-root",
            "/tmp/wiki",
            "--page-root",
            "/tmp/page",
        ])
        self.assertEqual(args.site_base_url, "https://tenstep.top")
        self.assertFalse(args.no_page_push)
        self.assertFalse(args.no_page_verify)

    def test_publish_page_repo_only_stages_generated_wiki_data(self):
        completed = subprocess.CompletedProcess([], 0, stdout=" M generated\n", stderr="")
        with patch.object(publish_wiki, "git_run", return_value=completed) as git_run:
            publish_wiki.publish_page_repo(Path("/tmp/page"), "Update wiki sync data")
        calls = [call.args[1:] for call in git_run.call_args_list]
        self.assertEqual(
            calls,
            [
                ("status", "--short", "--", "src/data/generated/wiki-sync"),
                ("add", "src/data/generated/wiki-sync"),
                ("commit", "-m", "Update wiki sync data"),
                ("push", "origin", "main"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
