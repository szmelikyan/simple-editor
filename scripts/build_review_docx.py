#!/usr/bin/env python3
"""Build a Word document with tracked changes from paired Markdown chapters.

Python 3.9+, standard library only. See README.ru.md for the command and limits.
The source and edited Markdown files remain authoritative; no Word automation.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import zip_longest
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED


W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
XML = 'http://www.w3.org/XML/1998/namespace'
ET.register_namespace('w', W)
ET.register_namespace('r', R)
INLINE = re.compile(r'(?<![\\*])(\*{1,3})(?!\*)((?:\\.|[^*\\])+?)\1(?!\*)')
TOKEN = re.compile(r'\s+|\w+|[^\w\s]', re.UNICODE)


def w(tag):
    return '{' + W + '}' + tag


def node(parent, tag, text=None, **attrs):
    child = ET.SubElement(parent, w(tag), {w(k): str(v) for k, v in attrs.items()})
    child.text = text
    return child


def xml_bytes(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def unescape(text):
    return re.sub(r'\\([\\*])', r'\1', text)


@dataclass
class Paragraph:
    style: str
    tokens: list

    @property
    def text(self):
        return ''.join(t[0] for t in self.tokens)


def parse_markdown(text):
    """The same flat emphasis/escape subset as the project's FB2 renderer."""
    result = []
    for block in re.split(r'\n\s*\n', text.strip()):
        if not block.strip():
            continue
        style = 'Normal'
        if block.startswith('# '):
            style, block = 'Heading1', block[2:]
        elif block.startswith('#'):
            raise ValueError('Only one-level chapter headings are supported.')
        elif block.startswith('> '):
            style = 'Quote'
            block = '\n'.join(line.removeprefix('> ') for line in block.splitlines())
        tokens = []

        def add(value, bold=False, italic=False):
            tokens.extend((t, bold, italic) for t in TOKEN.findall(unescape(value)))

        position = 0
        for match in INLINE.finditer(block):
            add(block[position:match.start()])
            marker, payload = match.groups()
            add(payload, len(marker) in (2, 3), len(marker) in (1, 3))
            position = match.end()
        add(block[position:])
        result.append(Paragraph(style, tokens))
    if not result:
        raise ValueError('Empty chapter.')
    return result


def align(before, after):
    """Anchor identical paragraphs, then pair changed blocks in source order.

    Unmatched paragraphs become tracked whole-paragraph insertions/deletions.
    Their paragraph marks are tracked as well as their text.
    """
    matcher = SequenceMatcher(None, [p.text for p in before],
                              [p.text for p in after], autojunk=False)
    for op, a, b, c, d in matcher.get_opcodes():
        if op == 'equal':
            yield from zip(before[a:b], after[c:d])
        else:
            yield from zip_longest(before[a:b], after[c:d])


class ReviewDocument:
    def __init__(self, author, date):
        self.author, self.date = author, date
        self.next_id = 0
        self.document = ET.Element(w('document'))
        self.body = node(self.document, 'body')
        self.before, self.after = [], []

    def revision(self, parent, kind):
        self.next_id += 1
        return node(parent, kind, id=self.next_id, author=self.author, date=self.date)

    def runs(self, parent, tokens, deleted=False):
        # Combine adjacent tokens with identical inline formatting.
        groups = []
        for text, bold, italic in tokens:
            if groups and groups[-1][1:] == (bold, italic):
                groups[-1] = (groups[-1][0] + text, bold, italic)
            else:
                groups.append((text, bold, italic))
        for text, bold, italic in groups:
            run = node(parent, 'r')
            if bold or italic:
                props = node(run, 'rPr')
                if bold:
                    node(props, 'b')
                if italic:
                    node(props, 'i')
            for index, line in enumerate(text.split('\n')):
                if index:
                    node(run, 'br')
                if line:
                    content = node(run, 'delText' if deleted else 't', line)
                    content.set('{' + XML + '}space', 'preserve')

    def paragraph(self, old, new):
        paragraph = node(self.body, 'p')
        props = node(paragraph, 'pPr')
        node(props, 'pStyle', val=(new or old).style)
        if old is None or new is None:
            kind = 'ins' if old is None else 'del'
            self.revision(node(props, 'rPr'), kind)
            self.runs(self.revision(paragraph, kind), (new or old).tokens,
                      deleted=(kind == 'del'))
            return
        if old.style != new.style:
            previous = node(self.revision(props, 'pPrChange'), 'pPr')
            node(previous, 'pStyle', val=old.style)
        for op, a, b, c, d in SequenceMatcher(None, old.tokens, new.tokens,
                                              autojunk=False).get_opcodes():
            if op == 'equal':
                self.runs(paragraph, new.tokens[c:d])
            else:
                if a != b:
                    self.runs(self.revision(paragraph, 'del'), old.tokens[a:b], deleted=True)
                if c != d:
                    self.runs(self.revision(paragraph, 'ins'), new.tokens[c:d])

    def chapter(self, before, after):
        old, new = parse_markdown(before), parse_markdown(after)
        self.before.extend(old)
        self.after.extend(new)
        for pair in align(old, new):
            self.paragraph(*pair)

    def finish(self):
        section = node(self.body, 'sectPr')
        footer = node(section, 'footerReference', type='default')
        footer.set('{' + R + '}id', 'rIdFooter')
        node(section, 'pgSz', w=11906, h=16838)
        node(section, 'pgMar', top=1134, right=1134, bottom=1134,
             left=1134, header=567, footer=567, gutter=0)
        return self.document


def styles_xml(language):
    root = ET.Element(w('styles'))
    defaults = node(root, 'docDefaults')
    props = node(node(defaults, 'rPrDefault'), 'rPr')
    node(props, 'rFonts', ascii='Times New Roman', hAnsi='Times New Roman',
         eastAsia='Times New Roman', cs='Times New Roman')
    node(props, 'sz', val=24)
    node(props, 'lang', val=language)
    for name in ('Normal', 'Heading1', 'Quote'):
        style = node(root, 'style', type='paragraph', styleId=name)
        if name == 'Normal':
            style.set(w('default'), '1')
        node(style, 'name', val={'Normal': 'Normal', 'Heading1': 'heading 1',
                                 'Quote': 'Quote'}[name])
        if name != 'Normal':
            node(style, 'basedOn', val='Normal')
        node(style, 'next', val='Normal')
        pp = node(style, 'pPr')
        if name == 'Heading1':
            node(pp, 'keepNext')
            node(pp, 'pageBreakBefore')
            node(pp, 'spacing', before=0, after=240)
            node(pp, 'outlineLvl', val=0)
            rp = node(style, 'rPr')
            node(rp, 'b')
            node(rp, 'sz', val=30)
        else:
            node(pp, 'spacing', after=120, line=276, lineRule='auto')
            node(pp, 'ind', left=360 if name == 'Quote' else 0,
                 firstLine=0 if name == 'Quote' else 360)
    return root


def settings_xml():
    root = ET.Element(w('settings'))
    node(root, 'view', val='print')
    node(root, 'zoom', percent=100)
    node(root, 'revisionView', markup='1', insDel='1', formatting='1')
    node(root, 'trackRevisions')
    node(root, 'doNotTrackMoves')
    compatibility = node(root, 'compat')
    node(compatibility, 'compatSetting', name='compatibilityMode',
         uri='http://schemas.microsoft.com/office/word', val=15)
    return root


def relationships(items):
    root = ET.Element('{' + PKG + '}Relationships')
    for identifier, kind, target in items:
        ET.SubElement(root, '{' + PKG + '}Relationship',
                      Id=identifier, Type=kind, Target=target)
    return root


def projection(document, accepted):
    """Return visible paragraph styles and formatted tokens in either review state."""
    result = []
    for p in document.find(w('body')).findall(w('p')):
        props = p.find(w('pPr'))
        mark = props.find(w('rPr'))
        if mark is not None and mark.find(w('del' if accepted else 'ins')) is not None:
            continue
        if not accepted:
            change = props.find(w('pPrChange'))
            if change is not None:
                props = change.find(w('pPr'))
        style = props.find(w('pStyle')).get(w('val'))
        spans = []

        def walk(parent):
            for child in parent:
                if child.tag == w('pPr'):
                    continue
                if child.tag == w('del') and accepted:
                    continue
                if child.tag == w('ins') and not accepted:
                    continue
                if child.tag == w('r'):
                    rp = child.find(w('rPr'))
                    bold = rp is not None and rp.find(w('b')) is not None
                    italic = rp is not None and rp.find(w('i')) is not None
                    text = ''.join('\n' if t.tag == w('br') else (t.text or '')
                                   for t in child if t.tag in (w('t'), w('delText'), w('br')))
                    spans.extend((t, bold, italic) for t in TOKEN.findall(text))
                else:
                    walk(child)
        walk(p)
        # Runs may split a word at a revision boundary: compare formatted characters.
        result.append((style, [(char, b, i) for text, b, i in spans for char in text]))
    return result


def expected_projection(paragraphs):
    return [(p.style, [(char, b, i) for text, b, i in p.tokens for char in text])
            for p in paragraphs]


def validate(path, before, after):
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt DOCX ZIP.')
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        document = ET.fromstring(archive.read('word/document.xml'))
        settings = ET.fromstring(archive.read('word/settings.xml'))
        if settings.find(w('trackRevisions')) is None:
            raise ValueError('Track Changes is disabled.')
        for accepted, expected in ((False, before), (True, after)):
            actual = projection(document, accepted)
            if actual != expected_projection(expected):
                raise ValueError('DOCX review projection does not match ' +
                                 ('edited' if accepted else 'source') + ' Markdown.')
        revisions = document.findall('.//' + w('ins')) + document.findall('.//' + w('del'))
        changes = revisions + document.findall('.//' + w('pPrChange'))
        ids = [item.get(w('id')) for item in changes]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate revision identifiers.')
        if expected_projection(before) != expected_projection(after) and not changes:
            raise ValueError('Edits exist but there are no tracked changes.')
        return len(revisions)


def build(project, chapters, output, author='Редактор перевода', language='ru-RU'):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    review = ReviewDocument(author, date)
    for chapter in chapters:
        if not re.fullmatch(r'[\w.-]+', chapter) or chapter in ('.', '..'):
            raise ValueError('Unsafe chapter identifier.')
        review.chapter((project / 'sources' / (chapter + '.md')).read_text(encoding='utf-8'),
                       (project / 'drafts' / (chapter + '.md')).read_text(encoding='utf-8'))
    document = review.finish()
    types = ET.Element('{' + CT + '}Types')
    ET.SubElement(types, '{' + CT + '}Default', Extension='rels',
                  ContentType='application/vnd.openxmlformats-package.relationships+xml')
    ET.SubElement(types, '{' + CT + '}Default', Extension='xml', ContentType='application/xml')
    for name, kind in (('document', 'document.main'), ('styles', 'styles'),
                       ('settings', 'settings'), ('footer1', 'footer')):
        ET.SubElement(types, '{' + CT + '}Override', PartName='/word/' + name + '.xml',
                      ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.' + kind + '+xml')
    footer = ET.Element(w('ftr'))
    paragraph = node(footer, 'p')
    node(node(paragraph, 'pPr'), 'jc', val='center')
    node(node(node(paragraph, 'fldSimple', instr=' PAGE '), 'r'), 't', '1')
    parts = {
        '[Content_Types].xml': types,
        '_rels/.rels': relationships([('rIdDocument', R + '/officeDocument', 'word/document.xml')]),
        'word/document.xml': document,
        'word/styles.xml': styles_xml(language),
        'word/settings.xml': settings_xml(),
        'word/footer1.xml': footer,
        'word/_rels/document.xml.rels': relationships([
            ('rIdStyles', R + '/styles', 'styles.xml'),
            ('rIdSettings', R + '/settings', 'settings.xml'),
            ('rIdFooter', R + '/footer', 'footer1.xml')]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Validate before replacing any existing review document.
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.docx', delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with ZipFile(temp_path, 'w', ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, xml_bytes(content))
        count = validate(temp_path, review.before, review.after)
        temp_path.replace(output)
    finally:
        temp_path.unlink(missing_ok=True)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--chapters', nargs='+', required=True,
                        help='Explicit chapter identifiers in reading order, without .md')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--author', default='Редактор перевода')
    parser.add_argument('--language', default='ru-RU')
    args = parser.parse_args()
    if len(args.chapters) != len(set(args.chapters)):
        parser.error('Duplicate chapter identifiers.')
    if args.output.suffix.lower() != '.docx':
        parser.error('Output must have a .docx extension.')
    count = build(args.project, args.chapters, args.output, args.author, args.language)
    print(f'{args.output}: {len(args.chapters)} chapters, {count} tracked insertion/deletion elements; '
          'source and edited text/formatting projections verified.')


if __name__ == '__main__':
    main()
