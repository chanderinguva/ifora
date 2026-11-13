import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'review-stack.py'
spec = importlib.util.spec_from_file_location('review_stack', PATH)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewStackTests(unittest.TestCase):
    def test_private_stable_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'private'
            with patch.object(review, 'DIRECTORY', directory), patch.object(review, 'ENV_FILE', directory / 'review.env'):
                first = review.environment_file()
                self.assertEqual(first, review.environment_file())
                self.assertEqual(len(set(first.values())), len(first))
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                self.assertEqual(review.ENV_FILE.stat().st_mode & 0o777, 0o600)

    def test_ambient_compose_and_secrets_not_forwarded(self):
        with patch.object(review, 'environment_file', return_value={}), patch('sys.argv', ['review-stack.py', 'status']), patch.dict('os.environ', {'COMPOSE_FILE': 'live.yml', 'POSTGRES_PASSWORD': 'live'}), patch.object(review.subprocess, 'run') as run:
            review.main()
            args, kwargs = run.call_args
            self.assertNotIn('COMPOSE_FILE', kwargs['env'])
            self.assertNotIn('POSTGRES_PASSWORD', kwargs['env'])
            self.assertIn('ifora-pr138-review', args[0])
            self.assertIn(str(review.ROOT / 'docker/docker-compose.review.yml'), args[0])

    def test_destroy_requires_exact_review_name(self):
        with patch.object(review, 'environment_file', return_value={}), patch('sys.argv', ['review-stack.py', 'destroy', '--confirm', 'ifora']), patch.object(review.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                review.main()
            run.assert_not_called()


    def test_purge_only_review_keys_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / 'review.env'; key.write_text('review-only')
            unrelated = Path(temp) / 'unrelated'; unrelated.write_text('keep')
            with patch.object(review, 'ENV_FILE', key), patch.object(review, 'environment_file', return_value={}), patch('sys.argv', ['review-stack.py', 'destroy', '--confirm', review.PROJECT, '--purge-keys']), patch.object(review.subprocess, 'run'):
                review.main()
            self.assertFalse(key.exists())
            self.assertTrue(unrelated.exists())
