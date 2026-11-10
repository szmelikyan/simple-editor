"""Verify real tracked edits, including both text and formatting review states."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from scripts.build_review_docx import build, parse_markdown, projection, w


def texts(state):
    return [''.join(char for char, _, _ in chars) for _, chars in state]


class ReviewDocxTests(unittest.TestCase):
    def export(self, source, edited):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for folder, text in [('sources', source), ('drafts', edited)]:
            (root / folder).mkdir()
            (root / folder / '1.md').write_text(text, encoding='utf-8')
        output = root / 'review.docx'
        build(root, ['1'], output)
        with ZipFile(output) as archive:
            return (ET.fromstring(archive.read('word/document.xml')),
                    ET.fromstring(archive.read('word/settings.xml')))

    def test_accept_and_reject_recover_content_and_paragraph_boundaries(self):
        old = '# Глава\n\nНачало.\n\nНенужный абзац.\n\nКонец.'
        new = '# Глава\n\nНачало!\n\nКонец.\n\nНовый абзац.'
        document, settings = self.export(old, new)
        self.assertEqual(texts(projection(document, False)),
                         ['Глава', 'Начало.', 'Ненужный абзац.', 'Конец.'])
        self.assertEqual(texts(projection(document, True)),
                         ['Глава', 'Начало!', 'Конец.', 'Новый абзац.'])
        self.assertIsNotNone(settings.find(w('trackRevisions')))
        self.assertTrue(document.findall('.//' + w('delText')))
        paragraphs = document.find(w('body')).findall(w('p'))
        self.assertTrue(any(p.find('./' + w('pPr') + '/' + w('rPr') + '/' + w('del')) is not None
                            for p in paragraphs))
        self.assertTrue(any(p.find('./' + w('pPr') + '/' + w('rPr') + '/' + w('ins')) is not None
                            for p in paragraphs))

    def test_style_changes_escape_literals_and_line_breaks(self):
        old = '# Глава\n\n> *текст* & <знак>\\*\nвторая строка\n\n***'
        new = '# Глава\n\n**текст** & <знак>\\*\nвторая строка\n\n***'
        document, _ = self.export(old, new)
        rejected, accepted = projection(document, False), projection(document, True)
        self.assertEqual(texts(accepted), ['Глава', 'текст & <знак>*\nвторая строка', '***'])
        self.assertEqual(texts(rejected), texts(accepted))
        self.assertEqual(rejected[1][0], 'Quote')
        self.assertEqual(accepted[1][0], 'Normal')
        self.assertEqual(rejected[1][1][0], ('т', False, True))
        self.assertEqual(accepted[1][1][0], ('т', True, False))
        self.assertTrue(document.findall('.//' + w('pPrChange')))

    def test_split_paragraph_and_formatting_of_unchanged_words(self):
        document, _ = self.export('# Глава\n\n*А. Б.*', '# Глава\n\n*А.*\n\n*Б.*')
        self.assertEqual(texts(projection(document, False)), ['Глава', 'А. Б.'])
        self.assertEqual(texts(projection(document, True)), ['Глава', 'А.', 'Б.'])
        for _, chars in projection(document, True)[1:]:
            self.assertTrue(all(italic for _, _, italic in chars))

    def test_unchanged_document_has_no_spurious_revisions(self):
        document, _ = self.export('# Глава\n\nБез правок.', '# Глава\n\nБез правок.')
        self.assertFalse(document.findall('.//' + w('ins')))
        self.assertFalse(document.findall('.//' + w('del')))

    def test_unicode_and_numbers_stay_literal(self):
        paragraphs = parse_markdown('# Глава\n\n「 50 000 и 5000; ■ □; 李鶴翾 」\n\n\\*')
        self.assertEqual([p.text for p in paragraphs],
                         ['Глава', '「 50 000 и 5000; ■ □; 李鶴翾 」', '*'])


if __name__ == '__main__':
    unittest.main()
