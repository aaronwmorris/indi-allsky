import re
from pathlib import Path
from urllib.parse import unquote

from markupsafe import Markup, escape

try:
    import markdown as md_lib
except ImportError:
    md_lib = None


DOCS_DIR = Path(__file__).resolve().parent.parent.parent / 'docs' / 'wiki'
GITHUB_WIKI_PREFIX_RE = re.compile(
    r'^https?://github\.com/aaronwmorris/indi-allsky/wiki(?:/([^#]*))?(#.*)?$'
)
HREF_RE = re.compile(r'href=(["\'])([^"\']+)\1')
SRC_RE = re.compile(r'src=(["\'])([^"\']+)\1')
ALERT_BLOCKQUOTE_RE = re.compile(
    r'<blockquote>\s*<p>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?:<br\s*/?>|\r?\n)?\s*(.*?)</p>(.*?)</blockquote>',
    re.DOTALL | re.IGNORECASE,
)
_ALERT_META = {
    'NOTE': ('note', 'info', 'Note'),
    'TIP': ('tip', 'lightbulb', 'Tip'),
    'IMPORTANT': ('important', 'alert-circle', 'Important'),
    'WARNING': ('warning', 'triangle-alert', 'Warning'),
    'CAUTION': ('caution', 'octagon-alert', 'Caution'),
}


def _get_docs_dir(docs_dir=None):
    return (Path(docs_dir) if docs_dir is not None else DOCS_DIR).resolve()


def resolve_doc_file(page, docs_dir=None):
    """Resolve a wiki page slug to a Markdown file inside docs/wiki, guarding against traversal."""
    base_dir = _get_docs_dir(docs_dir)
    slug = unquote(page or '').strip().strip('/')
    if not slug:
        slug = 'Home'
    if slug.endswith('.md'):
        slug = slug[:-3]

    candidate = (base_dir / f'{slug}.md').resolve()
    try:
        if not candidate.is_relative_to(base_dir):
            return None
    except AttributeError:
        if base_dir not in candidate.parents and candidate != base_dir:
            return None

    if candidate.is_file():
        return candidate
    return None


def resolve_doc_asset(asset, docs_dir=None):
    """Resolve a non-Markdown asset inside docs/wiki, guarding against traversal."""
    base_dir = _get_docs_dir(docs_dir)
    rel = unquote(asset or '').strip().lstrip('/')
    if not rel:
        return None

    candidate = (base_dir / rel).resolve()
    try:
        if not candidate.is_relative_to(base_dir):
            return None
    except AttributeError:
        if base_dir not in candidate.parents:
            return None

    if candidate.is_file() and candidate.suffix.lower() != '.md':
        return candidate
    return None


def load_doc_navigation(docs_dir=None):
    """Parse Home.md sections into sidebar navigation groups plus unlinked pages."""
    base_dir = _get_docs_dir(docs_dir)
    home_file = resolve_doc_file('Home', base_dir)
    sections = []
    seen_slugs = {'Home'}

    if home_file is not None:
        current_section = {'title': 'Documentation', 'items': []}
        for line in home_file.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                heading = stripped.lstrip('#').strip()
                if current_section['items']:
                    sections.append(current_section)
                current_section = {'title': heading, 'items': []}
                continue

            m = re.match(r'^[-*]\s+\[([^\]]+)\]\(([^)]+)\)', stripped)
            if m:
                label = m.group(1).strip()
                slug = unquote(m.group(2).strip()).split('#', 1)[0]
                if slug.endswith('.md'):
                    slug = slug[:-3]
                if resolve_doc_file(slug, base_dir) is not None:
                    current_section['items'].append({'label': label, 'slug': slug})
                    seen_slugs.add(slug)

        if current_section['items']:
            sections.append(current_section)

    extra_items = []
    if base_dir.is_dir():
        for md_path in sorted(base_dir.glob('*.md')):
            slug = md_path.stem
            if slug.startswith('_') or slug in seen_slugs:
                continue
            extra_items.append({
                'label': slug.replace('-', ' '),
                'slug': slug,
            })

    if extra_items:
        sections.append({'title': 'Additional Pages', 'items': extra_items})

    return sections


def render_doc_markdown(md_text, url_for_doc, url_for_asset):
    """Render Markdown to HTML and rewrite wiki/asset links to local viewer endpoints."""
    if md_lib is None:
        html_body = f'<pre class="tw:whitespace-pre-wrap">{escape(md_text)}</pre>'
        return Markup(html_body), Markup('')

    md = md_lib.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'])
    html_body = md.convert(md_text)

    def _rewrite_href(match):
        quote, href = match.group(1), match.group(2)
        wiki_match = GITHUB_WIKI_PREFIX_RE.match(href)
        if wiki_match:
            slug = unquote((wiki_match.group(1) or 'Home').strip('/')) or 'Home'
            anchor = wiki_match.group(2) or ''
            return f'href={quote}{url_for_doc(slug)}{anchor}{quote}'

        if href.startswith(('http://', 'https://', 'mailto:', '#', '/')):
            return match.group(0)

        target, anchor = (href.split('#', 1) + [''])[:2]
        anchor_suffix = f'#{anchor}' if anchor else ''
        slug = unquote(target).strip('/') or 'Home'
        if slug.endswith('.md'):
            slug = slug[:-3]
        return f'href={quote}{url_for_doc(slug)}{anchor_suffix}{quote}'

    def _rewrite_src(match):
        quote, src = match.group(1), match.group(2)
        if src.startswith(('http://', 'https://', 'data:', '/')):
            return match.group(0)
        return f'src={quote}{url_for_asset(unquote(src))}{quote}'

    def _rewrite_alert(match):
        kind = match.group(1).upper()
        first_body = match.group(2).strip()
        rest_body = match.group(3).strip()
        css_kind, icon_name, label = _ALERT_META.get(kind, ('note', 'info', kind.title()))
        inner = f'<p>{first_body}</p>' if first_body else ''
        if rest_body:
            inner += rest_body
        return (
            f'<div class="indi-doc-alert indi-doc-alert-{css_kind}">'
            f'<div class="indi-doc-alert-title">'
            f'<i class="tw:icon-[lucide--{icon_name}] tw:w-4 tw:h-4"></i>'
            f'<span>{label}</span>'
            f'</div>'
            f'<div class="indi-doc-alert-body">{inner}</div>'
            f'</div>'
        )

    html_body = HREF_RE.sub(_rewrite_href, html_body)
    html_body = SRC_RE.sub(_rewrite_src, html_body)
    html_body = ALERT_BLOCKQUOTE_RE.sub(_rewrite_alert, html_body)
    return Markup(html_body), Markup(getattr(md, 'toc', ''))
