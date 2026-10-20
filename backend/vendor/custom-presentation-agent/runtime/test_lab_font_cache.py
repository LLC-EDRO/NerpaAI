"""Exercise cache preparation without a converter, font service or Docker."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from lxml import etree
from runtime.font_cache import build_font_cache

class FontCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fonts = self.root / 'installed-fonts'
        self.fonts.mkdir()
        self.font = self.fonts / 'regular.ttf'
        self.font.write_bytes(b'font metadata is supplied by the fixture')
        self.missing = self.root / 'missing-fonts'
        self.output = self.root / 'output'
        self.cache_name = 'a' * 32 + '-le64.cache-8'

        resolver = types.SimpleNamespace(
            FONT_ROOTS=(self.fonts, self.missing),
            _build_index=lambda: {'fixture': (self.font,), 'fixture regular': (self.font,)},
        )
        fonts_module = types.ModuleType('runtime.fonts')
        fonts_module.TemplateFontResolver = resolver
        fonts_module.font_metadata = lambda path: {
            'family': 'Fixture', 'names': {'fixture', 'fixture regular'},
            'base_names': {'fixture'}, 'weight': 400, 'width': 5, 'italic': False,
        }
        self.font_module = patch.dict(sys.modules, {'runtime.fonts': fonts_module})
        self.font_module.start()
        self.addCleanup(self.font_module.stop)

    def cache_command(self, args, **options):
        self.assertEqual(args, ['fc-cache', '--force', str(self.fonts)])
        config_path = Path(options['env']['FONTCONFIG_FILE'])
        self.assertEqual(config_path, self.output / 'fonts.conf')
        config = etree.fromstring(config_path.read_bytes())
        self.assertEqual(config.tag, 'fontconfig')
        self.assertEqual(config.xpath('cachedir/text()'), [str(self.output / 'fontconfig')])
        self.assertEqual(config.xpath('dir/text()'), [str(self.fonts)])
        self.assertEqual(config.xpath('include/text()'), ['/etc/fonts/conf.d'])
        self.assertEqual(config.find('include').get('ignore_missing'), 'yes')
        self.assertNotIn('/etc/fonts/fonts.conf', config_path.read_text())
        self.assertFalse(options['check'])
        self.assertEqual(options['timeout'], 90)
        return types.SimpleNamespace(returncode=0)

    def write_cache(self):
        (self.output / 'fontconfig' / self.cache_name).write_bytes(b'cache fixture')

    def test_preparation_keeps_matching_rules_and_uses_only_its_private_cache(self):
        def run(args, **options):
            result = self.cache_command(args, **options)
            self.write_cache()
            return result

        with patch('runtime.font_cache.subprocess.run', side_effect=run) as command:
            result = build_font_cache(self.output, [str(self.fonts), str(self.missing)])
        self.assertEqual(command.call_count, 1)
        self.assertEqual(result, {'fonts': 1, 'cachedDirectories': 1})
        self.assertFalse((self.output / 'fonts.conf').exists())
        index = json.loads((self.output / 'font-index.json').read_text())
        self.assertEqual(list(index['records']), [str(self.font)])
        self.assertEqual(index['index']['fixture'], [str(self.font)])
        self.assertEqual(index['records'][str(self.font)]['names'], ['fixture', 'fixture regular'])

    def test_failed_command_rejects_partial_cache(self):
        def run(args, **options):
            self.cache_command(args, **options)
            self.write_cache()
            return types.SimpleNamespace(returncode=7)

        with patch('runtime.font_cache.subprocess.run', side_effect=run):
            with self.assertRaisesRegex(ValueError, '^pptx_font_cache_unavailable$'):
                build_font_cache(self.output, [str(self.fonts)])

    def test_successful_command_without_cache_is_not_ready(self):
        with patch('runtime.font_cache.subprocess.run', side_effect=self.cache_command):
            with self.assertRaisesRegex(ValueError, '^pptx_font_cache_unavailable$'):
                build_font_cache(self.output, [str(self.fonts)])

if __name__ == '__main__':
    unittest.main()
