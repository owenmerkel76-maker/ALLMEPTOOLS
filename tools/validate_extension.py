"""Validate extension packaging without importing Revit-dependent modules."""
import ast
import pathlib
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension'


def validate(root):
    errors = []
    counts = {'python': 0, 'xaml': 0, 'buttons': 0}
    if not root.is_dir():
        return counts, ['Extension directory is missing: {}'.format(root)]
    for path in sorted(root.rglob('*.py')):
        counts['python'] += 1
        try:
            ast.parse(path.read_bytes(), filename=str(path))
        except (SyntaxError, ValueError) as exc:
            errors.append('{}: {}'.format(path.relative_to(root), exc))
    for path in sorted(root.rglob('*.xaml')):
        counts['xaml'] += 1
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append('{}: {}'.format(path.relative_to(root), exc))
    for path in sorted(root.rglob('*.pushbutton')):
        counts['buttons'] += 1
        for required in ('script.py', 'bundle.yaml', 'icon.png'):
            if not (path / required).is_file():
                errors.append('{} missing {}'.format(path.relative_to(root), required))
    for kind, count in counts.items():
        if not count:
            errors.append('No {} found'.format(kind))
    return counts, errors


if __name__ == '__main__':
    counts, errors = validate(ROOT)
    print('Checked {python} Python files, {xaml} XAML files, {buttons} buttons.'.format(**counts))
    for error in errors:
        print('FAIL: ' + error)
    print('FAIL' if errors else 'PASS: source syntax, XML, and required button files')
    print('Revit API, IronPython compatibility, WPF loading, and model behavior require Windows/Revit testing.')
    sys.exit(1 if errors else 0)
