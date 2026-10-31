#!/usr/bin/env python3
"""Extract a saved RanobeLIB chapter as UTF-8 Markdown; Python 3.9+, stdlib.

Usage: python3 scripts/extract_saved_chapter.py INPUT.html OUTPUT.md
Only reader content is extracted. HTML scripts are never executed.
"""
import argparse
from html.parser import HTMLParser
from pathlib import Path


class ChapterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.quote = 0
        self.buffer = None
        self.visible = ''
        self.paragraphs = []
        self.markers = []
        self.heading = None
        self.title = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1':
            self.heading = ''
        if tag == 'main' and 'data-reader-content' in attrs:
            self.active = True
        if not self.active:
            return
        if tag in ('img', 'table', 'ruby'):
            raise ValueError('Unsupported reader content: ' + tag)
        if tag == 'blockquote':
            self.quote += 1
        if tag == 'p':
            self.buffer = ''
            self.visible = ''
        if tag == 'br' and self.buffer is not None:
            self.buffer += '\n'
            self.visible += '\n'
        if tag == 'span' and self.buffer is not None:
            classes = attrs.get('class', '').split()
            marker = ('**' if 'mark-bold' in classes else '') + ('*' if 'mark-italic' in classes else '')
            self.markers.append(marker)
            self.buffer += marker

    def handle_data(self, data):
        if self.heading is not None:
            self.heading += data
        if self.active and self.buffer is not None:
            if data.strip() == '***' and not self.markers and not self.buffer.strip():
                escaped = data
            else:
                escaped = data.replace('\\', '\\\\').replace('*', '\\*')
            self.buffer += escaped
            self.visible += data

    def handle_endtag(self, tag):
        if tag == 'h1' and self.heading is not None:
            self.title = self.heading.strip()
            self.heading = None
        if not self.active:
            return
        if tag == 'span' and self.buffer is not None:
            if not self.markers:
                raise ValueError('Unbalanced formatting span.')
            self.buffer += self.markers.pop()
        if tag == 'p' and self.buffer is not None:
            if self.markers:
                raise ValueError('Unclosed formatting span.')
            value = self.buffer.replace('\u00a0', ' ').strip()
            if self.visible.replace('\u00a0', ' ').strip():
                self.paragraphs.append(('> ' if self.quote else '') + value)
            self.buffer = None
        if tag == 'blockquote':
            self.quote -= 1
        if tag == 'main':
            self.active = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    chapter = ChapterParser()
    chapter.feed(args.input.read_text(encoding='utf-8'))
    if not chapter.paragraphs or chapter.active or chapter.buffer is not None:
        raise ValueError('Incomplete or missing reader content.')
    # Exclusive creation preserves any existing extracted source.
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write('\n\n'.join(chapter.paragraphs) + '\n')
    print(chapter.title)
    print(str(len(chapter.paragraphs)) + ' nonempty paragraphs')


if __name__ == '__main__':
    main()
