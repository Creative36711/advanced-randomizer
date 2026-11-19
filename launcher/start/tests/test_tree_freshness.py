"""Сверка версии дерева: устаревшее обновляется само, без сети — нет."""
import sys
import unittest
from pathlib import Path

import engine
from test_engine import make_source

MANIFEST = (
    '{"version": "%s", "url": "https://example.com/tree.zip", '
    '"sha256": "%s", "size": 10}'
)


class Opener:
    def __init__(self, payload: bytes = b'', error=None):
        self.payload = payload
        self.error = error

    def __call__(self, request, timeout=None):
        if self.error is not None:
            raise self.error
        payload = self.payload

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *info):
                return False

            def read(self, limit=None):
                return payload

        return Response()


class TreeFreshnessTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_source(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _published(self, version):
        original = engine.published_tree_version
        engine.published_tree_version = lambda opener=None: version
        self.addCleanup(setattr, engine, 'published_tree_version', original)

    def _write_version(self, version):
        (engine.source_tree(self.root) / '.launcher-assembled').write_text(
            version + '\n', encoding='utf-8')

    def test_matching_version_is_fresh(self):
        self._write_version('v0.3.0')
        self._published('v0.3.0')
        self.assertFalse(engine._tree_is_stale(self.root, echo=lambda _l: None))

    def test_older_version_is_stale(self):
        self._write_version('v0.3.0')
        self._published('v0.4.0')
        self.assertTrue(engine._tree_is_stale(self.root, echo=lambda _l: None))

    def test_unversioned_tree_is_stale(self):
        self._write_version('')
        self._published('v0.4.0')
        self.assertTrue(engine._tree_is_stale(self.root, echo=lambda _l: None))

    def test_no_published_version_keeps_the_tree(self):
        self._write_version('v0.3.0')
        self._published(None)
        self.assertFalse(engine._tree_is_stale(self.root, echo=lambda _l: None))


class PublishedVersionTests(unittest.TestCase):
    def test_reads_the_version_from_the_manifest(self):
        self.assertEqual(
            engine.published_tree_version(opener=Opener((MANIFEST % ('v0.4.1', 'a' * 64)).encode('utf-8'))),
            'v0.4.1')

    def test_network_failure_answers_none(self):
        import urllib.error
        self.assertIsNone(engine.published_tree_version(
            opener=Opener(error=urllib.error.URLError('нет сети'))))

    def test_unreadable_manifest_answers_none(self):
        self.assertIsNone(engine.published_tree_version(opener=Opener('не json'.encode('utf-8'))))


if __name__ == '__main__':
    unittest.main()
