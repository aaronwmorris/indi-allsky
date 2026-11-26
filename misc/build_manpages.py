#!/usr/bin/env python3
"""Generate roff man pages for indi-allsky-ctl(1) and docs/wiki/*.md (section 7)."""

import argparse
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / 'docs' / 'wiki'
CTL_PATH = REPO_ROOT / 'misc' / 'indi-allsky-ctl'


def _escape_roff(text):
    text = text.replace('\\', '\\e')
    lines = []
    for line in text.splitlines():
        if line.startswith(('.', "'")):
            line = '\\&' + line
        lines.append(line)
    return '\n'.join(lines)


def _format_inline(text):
    text = _escape_roff(text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'[\1]', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = re.sub(r'`([^`]+)`', r'\\fB\1\\fR', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\\fB\1\\fR', text)
    text = re.sub(r'__([^_]+)__', r'\\fB\1\\fR', text)
    return text


def _slug_to_man_name(slug):
    cleaned = re.sub(r'[^a-z0-9]+', '-', slug.lower()).strip('-')
    if cleaned == 'home':
        return 'indi-allsky'
    return f'indi-allsky-{cleaned}'


def markdown_to_roff(title, md_text, section='7', description=''):
    """Convert a Markdown document to a valid roff man page."""
    out = [
        f'.TH "{_escape_roff(title.upper())}" "{section}" "" "indi-allsky" "INDI Allsky Manual"',
        '.SH NAME',
        f'{_escape_roff(title)} \\- {_escape_roff(description or title)}',
    ]

    in_code = False
    has_section = False
    for raw_line in md_text.splitlines():
        line = raw_line.rstrip()

        if line.strip().startswith('```'):
            if not in_code:
                if not has_section:
                    out.append('.SH DESCRIPTION')
                    has_section = True
                out.append('.PP\n.nf\n.RS 4')
                in_code = True
            else:
                out.append('.RE\n.fi')
                in_code = False
            continue

        if in_code:
            out.append(_escape_roff(line))
            continue

        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith('#'):
            level = len(stripped) - len(stripped.lstrip('#'))
            heading = stripped.lstrip('#').strip()
            if level == 1 and not has_section:
                out.append(f'.SH "{_escape_roff(heading.upper())}"')
                has_section = True
            elif level <= 2:
                out.append(f'.SH "{_escape_roff(heading.upper())}"')
                has_section = True
            else:
                out.append(f'.SS "{_escape_roff(heading)}"')
                has_section = True
            continue

        if not has_section:
            out.append('.SH DESCRIPTION')
            has_section = True

        bullet_match = re.match(r'^[-*+]\s+(.*)$', stripped)
        if bullet_match:
            out.append(f'.IP "\\(bu" 2\n{_format_inline(bullet_match.group(1))}')
            continue

        num_match = re.match(r'^(\d+\.)\s+(.*)$', stripped)
        if num_match:
            out.append(f'.IP "{num_match.group(1)}" 4\n{_format_inline(num_match.group(2))}')
            continue

        if stripped.startswith('>'):
            quote_text = stripped.lstrip('>').strip()
            out.append(f'.RS 4\n{_format_inline(quote_text)}\n.RE')
            continue

        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            if all(re.match(r'^:?-+:?$', c) for c in cells if c):
                continue
            out.append('.TP\n' + _format_inline(' | '.join(cells)))
            continue

        out.append('.PP\n' + _format_inline(stripped))

    if in_code:
        out.append('.RE\n.fi')

    out.append('.SH "SEE ALSO"')
    out.append('.BR indi-allsky (7),')
    out.append('.BR indi-allsky-ctl (1)')
    return '\n'.join(out) + '\n'


def build_ctl_manpage(ctl_path=CTL_PATH):
    """Generate indi-allsky-ctl(1) from misc/indi-allsky-ctl --help output."""
    help_text = ''
    if ctl_path.is_file():
        res = subprocess.run(
            ['bash', str(ctl_path), '--help'],
            capture_output=True,
            text=True,
            check=False,
        )
        help_text = res.stdout or res.stderr or ''

    lines = [
        '.TH "INDI-ALLSKY-CTL" "1" "" "indi-allsky" "INDI Allsky Manual"',
        '.SH NAME',
        'indi-allsky-ctl \\- Command-line control and maintenance utility for indi-allsky',
        '.SH SYNOPSIS',
        '.B indi-allsky-ctl',
        '.I command',
        '[\\fIoptions/arguments...\\fR]',
        '.SH DESCRIPTION',
        'Command-line administration tool for managing users, database backups, dark frames, camera diagnostics, peripherals, TLS certificates, and systemd services for \\fBindi-allsky\\fR.',
    ]

    if help_text:
        lines.append('.SH COMMANDS')
        lines.append('.nf')
        for raw_line in help_text.splitlines():
            lines.append(_escape_roff(raw_line))
        lines.append('.fi')

    lines.extend([
        '.SH "SEE ALSO"',
        '.BR indi-allsky (7)',
    ])
    return '\n'.join(lines) + '\n'


def generate_all_manpages(out_dir, docs_dir=DOCS_DIR, ctl_path=CTL_PATH):
    """Generate man1/indi-allsky-ctl.1 and man7/indi-allsky*.7 under out_dir."""
    out_path = Path(out_dir)
    man1_dir = out_path / 'man1'
    man7_dir = out_path / 'man7'
    man1_dir.mkdir(parents=True, exist_ok=True)
    man7_dir.mkdir(parents=True, exist_ok=True)

    ctl_out = man1_dir / 'indi-allsky-ctl.1'
    ctl_out.write_text(build_ctl_manpage(ctl_path), encoding='utf-8')
    generated = [ctl_out]

    docs_path = Path(docs_dir)
    if docs_path.is_dir():
        for md_file in sorted(docs_path.glob('*.md')):
            if md_file.stem.startswith('_'):
                continue
            man_name = _slug_to_man_name(md_file.stem)
            desc = 'INDI Allsky Documentation' if man_name == 'indi-allsky' else md_file.stem.replace('-', ' ')
            roff = markdown_to_roff(man_name, md_file.read_text(encoding='utf-8'), section='7', description=desc)
            dest = man7_dir / f'{man_name}.7'
            dest.write_text(roff, encoding='utf-8')
            generated.append(dest)

    return generated


def main():
    parser = argparse.ArgumentParser(description='Build roff man pages for indi-allsky')
    parser.add_argument('--out', required=True, help='Output directory containing man1/ and man7/')
    args = parser.parse_args()
    generated = generate_all_manpages(args.out)
    print(f'Generated {len(generated)} man pages in {args.out}')


if __name__ == '__main__':
    main()
