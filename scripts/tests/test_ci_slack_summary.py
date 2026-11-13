import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('ci_slack_summary', Path(__file__).resolve().parents[1] / 'ci-slack.py')
slack = importlib.util.module_from_spec(spec); spec.loader.exec_module(slack)


class SummaryTests(unittest.TestCase):
    def test_merge_title_and_pr_link(self):
        env = {'DRONE_COMMIT_MESSAGE': 'Merge pull request #138 from chanderinguva/feature\n\nAdd connection workspaces and secure HTTP authentication', 'DRONE_REPO': 'chanderinguva/ifora'}
        summary = slack.change_summary(env)
        self.assertEqual(summary['text'], 'Add connection workspaces and secure HTTP authentication')
        self.assertEqual(summary['url'], 'https://github.com/chanderinguva/ifora/pull/138')

    def test_summary_is_plain_text_and_bounded(self):
        env = {'DRONE_COMMIT_MESSAGE': '<!channel> <https://evil.example|click>' + 'x' * 400}
        card = slack.blocks('start', env, {})
        summary = next(b for b in card if b.get('text', {}).get('text', '').startswith('📝'))
        self.assertEqual(summary['text']['type'], 'plain_text')
        self.assertLess(len(summary['text']['text']), 310)
        self.assertFalse(slack.change_summary({**env, 'DRONE_REPO': 'evil/x|bad', 'DRONE_PULL_REQUEST': '123'})['url'])

    def test_git_unavailable_is_nonblocking(self):
        with patch.object(slack.subprocess, 'run', side_effect=OSError):
            self.assertEqual(slack.change_summary({'DRONE_COMMIT_SHA': 'a' * 40})['text'], '')

    def test_squash_and_explicit_title(self):
        result = slack.change_summary({'DRONE_COMMIT_MESSAGE': 'Improve recipes (#139)', 'DRONE_REPO': 'chanderinguva/ifora'})
        self.assertEqual(result['number'], '139')
        self.assertEqual(slack.change_summary({'DRONE_PULL_REQUEST_TITLE': 'Chosen title', 'DRONE_COMMIT_MESSAGE': 'Other'})['text'], 'Chosen title')


    def test_merge_only_environment_uses_commit_body(self):
        from types import SimpleNamespace
        result = SimpleNamespace(returncode=0, stdout='Merge pull request #140 from owner/branch\n\nBuild Slack message layouts')
        with patch.object(slack.subprocess, 'run', return_value=result) as run:
            summary = slack.change_summary({'DRONE_COMMIT_SHA': 'a' * 40, 'DRONE_COMMIT_MESSAGE': 'Merge pull request #140 from owner/branch'})
            self.assertEqual(summary['text'], 'Build Slack message layouts')
            run.assert_called_once()
        with patch.object(slack.subprocess, 'run') as run:
            summary = slack.change_summary({'IFORA_BUILD_SUMMARY': 'Cached title', 'DRONE_COMMIT_SHA': 'a' * 40})
            self.assertEqual(summary['text'], 'Cached title')
            run.assert_not_called()
