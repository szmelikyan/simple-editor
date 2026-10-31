#!/usr/bin/env python3
"""Maintain a complete UTF-8 master from reviewed translation parts (stdlib only)."""
import argparse
import hashlib
import json
import os
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


def render(state):
    return '# ' + state['title'] + '\n\n' + '\n\n'.join(
        part['text'].strip() for part in sorted(state['parts'], key=lambda p: number(p['order']))
    ) + '\n'


def output_path(root, name):
    if Path(name).name != name or not name.endswith('.md'):
        raise ValueError('Output must be a Markdown filename inside the project directory.')
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
    atomic(root / 'assembly.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    atomic(output_path(root, state['output']), render(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('project', type=Path)
    init.add_argument('--title', required=True)
    init.add_argument('--language', required=True)
    init.add_argument('--output', default='edited.md')
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
            if args.command == 'put':
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
