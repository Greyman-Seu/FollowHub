import importlib.util
import subprocess
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "publish_source.py"
SPEC = importlib.util.spec_from_file_location("publish_source", MODULE_PATH)
publish_source = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(publish_source)


class PublishSourceTests(unittest.TestCase):
    def test_public_url_verification_follows_permanent_redirect(self):
        headers = Message()
        headers["Location"] = "/wiki/source/paper-slug/"
        redirect = HTTPError("https://tenstep.top/wiki/source/paper-slug", 308, "redirect", headers, None)

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch.object(publish_source, "urlopen", side_effect=[redirect, Response()]) as urlopen:
            publish_source.wait_for_public_url("https://tenstep.top/wiki/source/paper-slug", 1)

        redirected_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(redirected_request.full_url, "https://tenstep.top/wiki/source/paper-slug/")

    def test_parser_defaults_to_online_page_publish(self):
        parser = publish_source.build_parser()
        args = parser.parse_args([
            "--slug",
            "paper-slug",
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
        with patch.object(publish_source, "git_run", return_value=completed) as git_run:
            publish_source.publish_page_repo(Path("/tmp/page"), "Publish source paper-slug")
        calls = [call.args[1:] for call in git_run.call_args_list]
        self.assertEqual(
            calls,
            [
                ("status", "--short", "--", "src/data/generated/wiki-sync"),
                ("add", "src/data/generated/wiki-sync"),
                ("commit", "-m", "Publish source paper-slug"),
                ("push", "origin", "main"),
                ("rev-parse", "HEAD"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
