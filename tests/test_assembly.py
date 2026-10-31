"""Run from the repository root: python3 -m unittest discover -s tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/translation-edit/scripts/assemble.py'
spec = importlib.util.spec_from_file_location('assemble', SCRIPT)
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)
NS = {'f': 'http://www.gribuser.ru/xml/fictionbook/2.0'}


class AssemblyTests(unittest.TestCase):
    def test_fb2_preserves_text_quotes_and_special_characters(self):
        text = '# Глава 1\n\nТекст & <символы> 「 」.\n\n> Цитата.\n\n> 1. (невысоко) летящий.\n\n***\n\nКонец.'
        state = dict(output='edited.fb2', title='Книга & текст', language='ru', parts=[dict(id='1', order='1', text=text)])
        root = ET.fromstring(assembly.render(state))
        section = root.find('f:body/f:section', NS)
        self.assertEqual([p.text for p in section.findall('.//f:p', NS)],
                         ['Глава 1', 'Текст & <символы> 「 」.', 'Цитата.', '1. (невысоко) летящий.', '***', 'Конец.'])
        self.assertEqual(len(section.findall('f:cite', NS)), 1)

    def test_conversion_replacement_and_corruption_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'project'
            part = root / 'part.md'
            def run(*args, ok=True):
                result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, ok, result.stderr)
                return result
            run('init', project, '--title', 'Книга', '--language', 'ru', '--output', 'edited.md')
            for num in (2, 1):
                part.write_text(f'# Глава {num}\n\nТекст {num}.\n', encoding='utf-8')
                run('put', project, '--id', num, '--order', num, '--file', part, '--reviewed')
            old = (project / 'edited.md').read_bytes()
            run('convert', project, '--output', 'edited.fb2')
            self.assertEqual((project / 'edited.md').read_bytes(), old)
            run('verify', project)
            part.write_text('# Глава 1\n\nИсправлено.\n', encoding='utf-8')
            run('put', project, '--id', 1, '--order', 1, '--file', part, '--reviewed')
            book = ET.parse(project / 'edited.fb2')
            sections = book.findall('f:body/f:section', NS)
            self.assertEqual(len(sections), 2)
            self.assertEqual(sections[0].find('f:p', NS).text, 'Исправлено.')
            state_before = (project / 'assembly.json').read_bytes()
            (project / 'edited.fb2').write_text('повреждено', encoding='utf-8')
            run('put', project, '--id', 1, '--order', 1, '--file', part, '--reviewed', ok=False)
            self.assertEqual((project / 'assembly.json').read_bytes(), state_before)

    def test_unsupported_heading_does_not_write_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = dict(output='edited.fb2', title='Книга', language='ru', parts=[dict(id='1', order='1', text='# Глава\n\n## Подзаголовок')])
            with self.assertRaises(ValueError):
                assembly.save(root, state)
            self.assertFalse((root / 'assembly.json').exists())


if __name__ == '__main__':
    unittest.main()
