#!/usr/bin/env python3
"""Maintain a complete UTF-8 master from reviewed translation parts (stdlib only)."""
import argparse
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
import tempfile


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def atomic(path, text):
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def lock(root):
    path = root / '.assembly.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('Assembly locked. Check the running process before removing a stale lock.')
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink()


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Order must be a finite number; identifiers can use original chapter numbering.')
    if not result.is_finite():
        raise ValueError('Order must be finite.')
    return result


def render_fb2(state):
    ns = 'http://www.gribuser.ru/xml/fictionbook/2.0'
    ET.register_namespace('', ns)
    def element(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, '{' + ns + '}' + tag, attrs)
        node.text = text
        return node
    book = ET.Element('{' + ns + '}FictionBook')
    description = element(book, 'description')
    info = element(description, 'title-info')
    element(info, 'genre', state.get('genre', 'unrecognised'))
    author = element(info, 'author')
    element(author, 'nickname', state.get('author', 'Автор не указан'))
    element(info, 'book-title', state['title'])
    element(info, 'lang', state['language'])
    document = element(description, 'document-info')
    element(element(document, 'author'), 'nickname', 'simple-editor')
    element(document, 'program-used', 'assemble.py (Python 3 standard library)')
    element(document, 'date', state.get('date', 'Дата не указана'))
    element(document, 'id', 'simple-editor-' + digest(state['title'] + '\n' + state['language']))
    element(document, 'version', '1.0')
    body = element(book, 'body')
    parts = sorted(state['parts'], key=lambda p: number(p['order']))
    for part in parts:
        section = element(body, 'section', id='part-' + digest(part['id'])[:16])
        blocks = re.split(r'\n\s*\n', part['text'].strip())
        heading = blocks.pop(0) if blocks[0].startswith('# ') else part['id']
        element(element(section, 'title'), 'p', heading.removeprefix('# '))
        quote = None
        for block in blocks:
            if block.startswith('#'):
                raise ValueError('FB2 supports one leading chapter heading; nested headings require explicit conversion.')
            if block.startswith('> '):
                if quote is None:
                    quote = element(section, 'cite')
                text = '\n'.join(line.removeprefix('> ') for line in block.splitlines())
                element(quote, 'p', text)
            else:
                quote = None
                element(section, 'p', block)
    if not parts:
        element(element(body, 'section'), 'empty-line')
    ET.indent(book, space='  ')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(book, encoding='unicode') + '\n'


def render(state):
    if state['output'].endswith('.fb2'):
        return render_fb2(state)
    return '# ' + state['title'] + '\n\n' + '\n\n'.join(
        part['text'].strip() for part in sorted(state['parts'], key=lambda p: number(p['order']))
    ) + '\n'


def output_path(root, name):
    if Path(name).name != name or not name.endswith(('.md', '.fb2')):
        raise ValueError('Output must be an .md or .fb2 filename inside the project directory.')
    return root / name


def read_state(root):
    state = json.loads((root / 'assembly.json').read_text(encoding='utf-8'))
    if state.get('version') != 1:
        raise ValueError('Unsupported assembly state.')
    ids, orders = set(), set()
    for part in state['parts']:
        order = number(part['order'])
        if part['id'] in ids or order in orders:
            raise ValueError('Duplicate part identifier or order in state.')
        if not part['text'].strip() or digest(part['text']) != part['sha256']:
            raise ValueError('Canonical part damaged: ' + part['id'])
        ids.add(part['id'])
        orders.add(order)
    output_path(root, state['output'])
    return state


def check_master(root, state):
    master = output_path(root, state['output'])
    if not master.exists():
        raise ValueError('Master is missing. Refusing a partial replacement; restore with rebuild from complete canonical state.')
    if master.read_text(encoding='utf-8') != render(state):
        raise ValueError('Master differs from canonical state. Reconcile external edits before an explicit rebuild.')


def save(root, state):
    # State contains every complete part. If interrupted between writes, check_master
    # refuses further updates; explicit rebuild restores the complete master from state.
    rendered = render(state)
    atomic(root / 'assembly.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    atomic(output_path(root, state['output']), rendered)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('project', type=Path)
    init.add_argument('--title', required=True)
    init.add_argument('--language', required=True)
    init.add_argument('--output', default='edited.fb2')
    convert = sub.add_parser('convert')
    convert.add_argument('project', type=Path)
    convert.add_argument('--output', required=True)
    put = sub.add_parser('put')
    put.add_argument('project', type=Path)
    put.add_argument('--id', required=True)
    put.add_argument('--order', required=True)
    put.add_argument('--file', type=Path, required=True)
    put.add_argument('--reviewed', action='store_true', required=True)
    for command in ['verify', 'rebuild']:
        cmd = sub.add_parser(command)
        cmd.add_argument('project', type=Path)
        if command == 'rebuild':
            cmd.add_argument('--confirm', action='store_true', required=True)
    args = parser.parse_args()
    root = args.project.resolve()
    if args.command == 'init':
        root.mkdir(parents=True, exist_ok=True)
        with lock(root):
            master = output_path(root, args.output)
            if (root / 'assembly.json').exists() or master.exists():
                raise ValueError('Project already exists; refusing to overwrite.')
            if not args.title.strip():
                raise ValueError('Title is empty.')
            state = {'version': 1, 'title': args.title, 'language': args.language,
                     'output': args.output, 'parts': []}
            save(root, state)
    else:
        with lock(root):
            state = read_state(root)
            if args.command == 'convert':
                check_master(root, state)
                target = output_path(root, args.output)
                if target.exists():
                    raise ValueError('Conversion target already exists; refusing to overwrite.')
                state['output'] = args.output
                save(root, state)
            elif args.command == 'put':
                check_master(root, state)
                order = number(args.order)
                if any(p['id'] != args.id and number(p['order']) == order for p in state['parts']):
                    raise ValueError('Order is already assigned to a different part.')
                text = args.file.read_text(encoding='utf-8')
                if not text.strip() or not args.id.strip():
                    raise ValueError('Part identifier and reviewed text must be nonempty.')
                state['parts'] = [p for p in state['parts'] if p['id'] != args.id]
                state['parts'].append({'id': args.id, 'order': str(order), 'text': text,
                                       'sha256': digest(text)})
                save(root, state)
            elif args.command == 'rebuild':
                # Never rebuild from a supplied fragment: read_state validated all canonical parts.
                atomic(output_path(root, state['output']), render(state))
            check_master(root, state)
    ordered = sorted(state['parts'], key=lambda p: number(p['order']))
    print(json.dumps({'file': str(output_path(root, state['output'])), 'count': len(ordered),
                      'ids': [p['id'] for p in ordered],
                      'updated': args.id if args.command == 'put' else None}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc))
