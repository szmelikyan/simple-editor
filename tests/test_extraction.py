"""Check text and source styling without executing saved page scripts."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/extract_saved_chapter.py'
spec = importlib.util.spec_from_file_location('extract_saved_chapter', SCRIPT)
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


class ExtractionTests(unittest.TestCase):
    def test_reader_only_mixed_styles_and_empty_spacers(self):
        parser = extractor.ChapterParser()
        parser.feed('''<h1>Chapter title</h1><p>Navigation</p>
<script>not_executable()</script><main data-reader-content="">
<p><span class="node-text mark-bold"> </span></p>
<blockquote><p><span class="node-text mark-bold">Category:</span> Main</p></blockquote>
<p><span class="node-text mark-bold mark-italic">A &amp; B</span></p>
<p>***</p><p>Line 1<br>Line 2</p></main><p>Advertisement</p>''')
        self.assertEqual(parser.title, 'Chapter title')
        self.assertEqual(parser.paragraphs, ['> **Category:** Main', '***A & B***', '***', 'Line 1\nLine 2'])

    def test_unknown_content_stops_extraction(self):
        parser = extractor.ChapterParser()
        with self.assertRaises(ValueError):
            parser.feed('<main data-reader-content=""><p><img src="unknown"></p></main>')


if __name__ == '__main__':
    unittest.main()
