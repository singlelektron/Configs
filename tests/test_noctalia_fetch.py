import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/fetch-noctalia-preview.py'
SPEC = importlib.util.spec_from_file_location('noctalia_fetch', SCRIPT)
FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)


class NoctaliaFetchTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'downloads'
        source.mkdir()
        package = source / 'preview.pkg.tar'
        with tarfile.open(package, 'w') as archive:
            info = tarfile.TarInfo('usr/bin/noctalia')
            info.size = 4
            archive.addfile(info, io.BytesIO(b'test'))
        Path(str(package) + '.sig').write_text('signature')
        entry = {'name': 'noctalia', 'file': package.name, 'sha256': FETCH.digest(package),
                 'url': 'https://archive.archlinux.org/packages/n/noctalia/test',
                 'signature_url': 'https://archive.archlinux.org/packages/n/noctalia/test.sig'}
        return source, {'packages': [entry]}

    def test_unrelated_destination_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'keep').write_text('user content')
            with self.assertRaisesRegex(ValueError, 'unrelated'):
                FETCH.destination(root, create=True)
            self.assertFalse((root / FETCH.MARKER).exists())
            self.assertEqual((root / 'keep').read_text(), 'user content')

    def test_wrong_hash_never_verifies_or_extracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, manifest = self.fixture(root)
            manifest['packages'][0]['sha256'] = '0' * 64
            with patch.object(FETCH.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    FETCH.prepare(root / 'runtime', manifest, source)
                run.assert_not_called()
            self.assertFalse((root / 'runtime/prefix').exists())

    def test_invalid_signature_never_extracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, manifest = self.fixture(root)
            with patch.object(FETCH.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['pacman-key'])) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    FETCH.prepare(root / 'runtime', manifest, source)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][0], 'pacman-key')
            self.assertFalse((root / 'runtime/prefix').exists())

    def test_unsafe_archive_paths_and_links_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'unsafe.tar'
            for name, target in [('usr/../../outside', None), ('/usr/bin/x', None), ('usr/lib/link', '/etc'), ('usr/lib/link', '../../../etc')]:
                with self.subTest(name=name, target=target):
                    with tarfile.open(package, 'w') as archive:
                        info = tarfile.TarInfo(name)
                        if target:
                            info.type, info.linkname = tarfile.SYMTYPE, target
                        archive.addfile(info)
                    with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
                        FETCH.inspect_archive(package)

    def test_only_usr_is_extracted_and_downloads_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, manifest = self.fixture(root)
            with patch.object(FETCH.subprocess, 'run') as run:
                FETCH.prepare(root / 'runtime', manifest, source)
            extract = run.call_args_list[-1].args[0]
            self.assertEqual(extract[0], 'bsdtar')
            self.assertEqual(extract[-1], 'usr')
            self.assertIn('--no-same-owner', extract)
            self.assertTrue((root / 'runtime/packages/preview.pkg.tar.sig').exists())
            self.assertEqual(json.loads((root / 'runtime/runtime.json').read_text()), manifest)


if __name__ == '__main__':
    unittest.main()
