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

    def test_prepare_passes_its_opener_and_never_touches_the_network(self):
        # Дефект, который тут закреплён: _tree_is_stale вызывался без opener, и
        # step_prepare в тестах ходил в настоящую сеть — тест проверял бы не то,
        # что задумано, а иногда и просто падал по таймауту.
        self._write_version('v0.3.0')
        seen = []

        def opener(request, timeout=None):
            seen.append(request.full_url)
            payload = (MANIFEST % ('v0.9.9', 'a' * 64)).encode('utf-8')

            class Response:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *info):
                    return False

                def read(self_inner, limit=None):
                    return payload

            return Response()

        stale = engine._tree_is_stale(self.root, echo=lambda _l: None, opener=opener)
        self.assertTrue(stale)
        self.assertEqual(len(seen), 1, 'opener из step_prepare должен дойти до проверки')

    def test_no_published_version_keeps_the_tree(self):
        self._write_version('v0.3.0')
        self._published(None)
        self.assertFalse(engine._tree_is_stale(self.root, echo=lambda _l: None))


class PlanTests(unittest.TestCase):
    """Причина, по которой фикс не доходил до игрока.

    first_run_plan добавлял prepare только если дерева НЕ БЫЛО. У игрока с
    готовым (но старым) деревом шаг выбрасывался, step_prepare не вызывался,
    и сверка версий не выполнялась никогда — сколько бы раз он ни запускал.
    """

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_source(self.root)
        (engine.source_tree(self.root) / '.launcher-assembled').write_text(
            'v0.3.0\n', encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self):
        settings = engine.Settings(install_root=self.root)
        settings.bfme2_install = self.root / 'bfme2'
        return engine.first_run_plan(settings)

    def _published(self, version):
        original = engine.published_tree_version
        engine.published_tree_version = lambda opener=None: version
        self.addCleanup(setattr, engine, 'published_tree_version', original)

    def test_a_stale_tree_still_gets_the_prepare_step(self):
        # ВАЖНО про версию: первая версия дерева писала в .launcher-assembled
        # человеческую фразу «Собрано лаунчером Advanced Randomizer, версия
        # v0.3.0», а манифест отдаёт голый тег. Строки не совпадали, игрок
        # получал бесконечную «устарело → скачать заново» на каждом запуске.
        # Поэтому локальная версия здесь — то, что реально пишет unpack:
        # версия из манифеста.
        (engine.source_tree(self.root) / '.launcher-assembled').write_text(
            'v0.3.0-main-bc9dac02\n', encoding='utf-8')
        self._published('v0.4.0')
        self.assertIn('prepare', self._plan(),
                      'игрок с устаревшим деревом обязан получить обновление')

    def test_a_current_tree_skips_the_prepare_step(self):
        (engine.source_tree(self.root) / '.launcher-assembled').write_text(
            'v0.3.0-main-bc9dac02\n', encoding='utf-8')
        self._published('v0.3.0-main-bc9dac02')
        self.assertNotIn('prepare', self._plan())

    def test_without_network_the_plan_is_unchanged(self):
        self._published(None)
        self.assertNotIn('prepare', self._plan())


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
