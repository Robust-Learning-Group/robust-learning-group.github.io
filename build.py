#!/usr/bin/env python3
"""
Explicit Static Site Generator for the Robust Learning Group
=============================================================
Philosophy: explicit over implicit. One readable script turns
Markdown (content/), YAML collections (data/) and Jinja2 templates
(templates/) into a static site in dist/.

Every collection is normalised here, in Python, so templates never
have to guess whether a field exists. Cross-references between files
(publication -> research area, person -> research area) are validated,
and the build stops with a clear message when something is wrong.

Usage:
    python build.py            # build into dist/
    python build.py --clean    # wipe dist/ first
    python build.py --serve    # build, serve on :8000 and rebuild on change
"""

import argparse
import json
import datetime
import http.server
import re
import shutil
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

import frontmatter
import jinja2
import markdown
import yaml
from markupsafe import Markup

# ---------------------------------------------------------------------------
# Directory configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONTENT_DIR = BASE_DIR / "content"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DIST_DIR = BASE_DIR / "dist"
CONFIG_FILE = BASE_DIR / "config.yaml"
THEMES_FILE = BASE_DIR / "themes.yaml"

# Colour tokens every theme must define, in both light and dark mode.
THEME_COLORS = [
    "paper", "surface", "ink", "ink-2", "ink-3", "rule", "rule-strong",
    "primary", "primary-soft", "adversary", "link",
]

# Order in which publication links are displayed, and their labels.
PUBLICATION_LINKS = [
    ("paper", "Paper"),
    ("arxiv", "arXiv"),
    ("code", "Code"),
    ("project", "Project"),
    ("slides", "Slides"),
    ("video", "Video"),
    ("doi", "DOI"),
    ("bibtex", "BibTeX"),
]

# Order in which a person's links are displayed, and their labels.
PERSON_LINKS = [
    ("website", "Website"),
    ("scholar", "Scholar"),
    ("github", "GitHub"),
    ("linkedin", "LinkedIn"),
    ("orcid", "ORCID"),
    ("email", "Email"),
]


class ContentError(Exception):
    """Raised when a content or data file is malformed. Message says where and why."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    """'El Mahdi El Mhamdi' -> 'el-mahdi-el-mhamdi' (accents stripped)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def name_key(person: Dict[str, Any]) -> str:
    """Sort key: full name, accents stripped, case-insensitive (i.e. by first name)."""
    return slugify(person["name"])


def initials(name: str) -> str:
    """'El Mahdi El Mhamdi' -> 'EM' (first and last word)."""
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def require(item: Dict[str, Any], keys: List[str], where: str) -> None:
    """Fails loudly if any required key is missing or empty."""
    if not isinstance(item, dict):
        raise ContentError(f"{where}: expected a mapping, got {type(item).__name__}")
    missing = [k for k in keys if item.get(k) in (None, "", [])]
    if missing:
        raise ContentError(f"{where}: missing required field(s): {', '.join(missing)}")


def parse_date(val: Any, where: str) -> datetime.date:
    """Accepts a YAML date, 'YYYY-MM-DD', 'YYYY-MM' or a bare year."""
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, int):
        return datetime.date(val, 1, 1)
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
    raise ContentError(f"{where}: unsupported date {val!r} (use YYYY-MM-DD, YYYY-MM or YYYY)")


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise ContentError(f"Missing file: {path.relative_to(BASE_DIR)}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_markdown(name: str) -> Dict[str, Any]:
    """Loads content/<name>.md -> {'meta': {...}, 'body': str}."""
    path = CONTENT_DIR / f"{name}.md"
    if not path.exists():
        raise ContentError(f"Missing file: {path.relative_to(BASE_DIR)}")
    with open(path, "r", encoding="utf-8") as f:
        post = frontmatter.load(f)
    return {"meta": post.metadata, "body": post.content}


def ordered_links(raw: Dict[str, str], spec: List[tuple], where: str) -> List[Dict[str, str]]:
    """Turns a {kind: url} mapping into an ordered [{label, url}] list."""
    raw = raw or {}
    known = {k for k, _ in spec}
    unknown = set(raw) - known
    if unknown:
        raise ContentError(
            f"{where}: unknown link type(s) {sorted(unknown)}; allowed: {sorted(known)}"
        )
    links = []
    for kind, label in spec:
        url = raw.get(kind)
        if url:
            if kind == "email" and not url.startswith("mailto:"):
                url = f"mailto:{url}"
            links.append({"kind": kind, "label": label, "url": url})
    return links


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
_md = markdown.Markdown(extensions=["tables", "footnotes", "attr_list", "smarty"])


def render_markdown(text: str) -> Markup:
    _md.reset()
    return Markup(_md.convert(text or ""))


def render_markdown_inline(text: str) -> Markup:
    """For one-line fields: renders Markdown but drops the wrapping <p>."""
    html = str(render_markdown(text)).strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return Markup(html)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def load_research() -> List[Dict[str, Any]]:
    raw = load_yaml(DATA_DIR / "research.yaml") or []
    areas, seen = [], set()
    for i, item in enumerate(raw):
        where = f"data/research.yaml, entry {i + 1}"
        require(item, ["title", "summary"], where)
        slug = item.get("slug") or slugify(item["title"])
        if slug in seen:
            raise ContentError(f"{where}: duplicate slug '{slug}'")
        seen.add(slug)
        areas.append({
            "slug": slug,
            "title": item["title"],
            "short": item.get("short") or item["title"],
            "summary": item["summary"],
            "description": item.get("description", ""),
            "questions": item.get("questions") or [],
            # filled in later by cross-referencing
            "publications": [],
            "people": [],
        })
    return areas


def load_people(area_slugs: set) -> Dict[str, Any]:
    raw = load_yaml(DATA_DIR / "people.yaml") or {}
    sections, members_by_name = [], {}

    def person(item: Dict[str, Any], where: str, alumni: bool = False) -> Dict[str, Any]:
        require(item, ["name"], where)
        bad = set(item.get("areas") or []) - area_slugs
        if bad:
            raise ContentError(
                f"{where}: unknown research area(s) {sorted(bad)}; "
                f"defined in data/research.yaml: {sorted(area_slugs)}"
            )
        p = {
            "name": item["name"],
            "slug": slugify(item["name"]),
            "initials": initials(item["name"]),
            "role": item.get("role", ""),
            "affiliation": item.get("affiliation", ""),
            "photo": item.get("photo", ""),
            "bio": item.get("bio", ""),
            "areas": item.get("areas") or [],
            "links": ordered_links(item.get("links"), PERSON_LINKS, where),
            "years": str(item.get("years", "")),
            "now": item.get("now", ""),
            "alumni": alumni,
        }
        if p["photo"] and not (STATIC_DIR / p["photo"]).exists():
            print(f"[warn] {where}: photo not found at static/{p['photo']}, using initials")
            p["photo"] = ""
        if p["name"] in members_by_name:
            raise ContentError(f"{where}: '{p['name']}' is listed twice in people.yaml")
        members_by_name[p["name"]] = p
        # Alternative spellings that should also be highlighted in author lists
        for alias in item.get("aliases") or []:
            members_by_name[alias] = p
        return p

    for s_i, section in enumerate(raw.get("sections") or []):
        where = f"data/people.yaml, section {s_i + 1}"
        require(section, ["title", "members"], where)
        members = [
            person(m, f"{where} ({section['title']}), member {m_i + 1}")
            for m_i, m in enumerate(section["members"])
        ]
        if section.get("sort", True):
            members.sort(key=name_key)
        sections.append({"title": section["title"], "members": members})

    alumni = [
        person(m, f"data/people.yaml, alumni entry {i + 1}", alumni=True)
        for i, m in enumerate(raw.get("alumni") or [])
    ]
    current = [m for s in sections for m in s["members"]]
    return {"sections": sections, "alumni": alumni, "current": current, "by_name": members_by_name}


def load_publications(area_slugs: set, members_by_name: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = load_yaml(DATA_DIR / "publications.yaml") or []
    pubs = []
    for i, item in enumerate(raw):
        where = f"data/publications.yaml, entry {i + 1}"
        require(item, ["title", "authors", "venue", "date"], where)
        if not isinstance(item["authors"], list):
            raise ContentError(f"{where}: 'authors' must be a list of names")
        areas = item.get("areas") or []
        bad = set(areas) - area_slugs
        if bad:
            raise ContentError(
                f"{where} ('{item['title'][:40]}...'): unknown research area(s) {sorted(bad)}; "
                f"defined in data/research.yaml: {sorted(area_slugs)}"
            )
        d = parse_date(item["date"], where)
        authors = []
        for name in item["authors"]:
            m = members_by_name.get(name)
            authors.append({
                "name": name,
                "member": bool(m),
                "slug": m["slug"] if m else "",
                "alumni": m["alumni"] if m else False,
            })
        links = ordered_links(item.get("links"), PUBLICATION_LINKS, where)
        pubs.append({
            "title": item["title"],
            "authors": authors,
            "venue": item["venue"],
            "note": item.get("note", ""),
            "date": d,
            "year": d.year,
            "areas": areas,
            "links": links,
            "primary_url": links[0]["url"] if links else "",
            "search_text": " ".join(
                [item["title"], item["venue"], *item["authors"]]
            ).lower(),
        })
    pubs.sort(key=lambda p: p["date"], reverse=True)
    return pubs


def load_news(categories: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = load_yaml(DATA_DIR / "news.yaml") or []
    items = []
    for i, item in enumerate(raw):
        where = f"data/news.yaml, entry {i + 1}"
        require(item, ["date", "title"], where)
        kind = item.get("kind", "update")
        if kind not in categories:
            raise ContentError(
                f"{where}: unknown kind '{kind}'; defined in config.yaml news_kinds: "
                f"{sorted(categories)}"
            )
        d = parse_date(item["date"], where)
        items.append({
            "date": d,
            "date_str": f"{d.day} {d:%B %Y}",
            "date_iso": d.isoformat(),
            "kind": kind,
            "kind_label": categories[kind]["label"],
            "title": item["title"],
            "body": item.get("body", ""),
            "link": item.get("link", ""),
        })
    items.sort(key=lambda n: n["date"], reverse=True)
    return items



# ---------------------------------------------------------------------------
# Themes (colours and fonts, from themes.yaml)
# ---------------------------------------------------------------------------
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def load_themes() -> Dict[str, Dict[str, Any]]:
    raw = load_yaml(THEMES_FILE) or {}
    themes = {}
    for name, t in raw.items():
        where = f"themes.yaml, theme '{name}'"
        require(t, ["fonts", "light", "dark"], where)
        require(t["fonts"], ["heading", "text"], f"{where}, fonts")
        for mode in ("light", "dark"):
            missing = [c for c in THEME_COLORS if c not in t[mode]]
            if missing:
                raise ContentError(f"{where}, {mode}: missing colour(s): {', '.join(missing)}")
            bad = [f"{c}={v!r}" for c, v in t[mode].items() if not HEX_RE.match(str(v))]
            if bad:
                raise ContentError(f"{where}, {mode}: not a hex colour: {', '.join(bad)}")

        fonts, font_urls = {}, []
        for role in ("heading", "text"):
            f = t["fonts"][role]
            require(f, ["family"], f"{where}, fonts.{role}")
            fonts[role] = f"'{f['family']}', {f.get('fallback', 'sans-serif')}"
            weights = str(f.get("weights", "400;500;600"))
            font_url = (
                "https://fonts.googleapis.com/css2?family="
                + f["family"].replace(" ", "+") + ":wght@" + weights + "&display=swap"
            )
            if font_url not in font_urls:
                font_urls.append(font_url)

        themes[name] = {
            "name": name,
            "label": t.get("label", name),
            "fonts": fonts,
            "font_urls": font_urls,
            "light": t["light"],
            "dark": t["dark"],
        }
    if not themes:
        raise ContentError("themes.yaml: define at least one theme")
    return themes


def generate_theme_css(themes: Dict[str, Dict[str, Any]]) -> None:
    """Writes dist/static/css/theme.css: one block of CSS variables per theme and mode."""

    def block(selector: str, theme: Dict[str, Any], mode: str) -> str:
        lines = [f"  --{c}: {theme[mode][c]};" for c in THEME_COLORS]
        lines.append(f"  --focus: {theme[mode]['link']};")
        lines.append(f"  color-scheme: {mode};")
        if mode == "light":
            lines.append(f"  --font-head: {theme['fonts']['heading']};")
            lines.append(f"  --font-text: {theme['fonts']['text']};")
        return selector + " {\n" + "\n".join(lines) + "\n}\n"

    css = ["/* Generated by build.py from themes.yaml. Do not edit by hand. */\n"]
    for name, t in themes.items():
        sel = f':root[data-palette="{name}"]'
        css.append(block(sel, t, "light"))
        css.append(
            "@media (prefers-color-scheme: dark) {\n"
            + block(f'{sel}:not([data-theme="light"])', t, "dark")
            + "}\n"
        )
        css.append(block(f'{sel}[data-theme="dark"]', t, "dark"))
    out = DIST_DIR / "static" / "css" / "theme.css"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(css), encoding="utf-8")


def group_by_year(pubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[int, List] = {}
    for p in pubs:
        groups.setdefault(p["year"], []).append(p)
    return [{"year": y, "publications": groups[y]} for y in sorted(groups, reverse=True)]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
ROUTES = [
    # (template, output path, current_page)
    ("index.html", "index.html", "home"),
    ("research.html", "research/index.html", "research"),
    ("publications.html", "publications/index.html", "publications"),
    ("people.html", "people/index.html", "people"),
    ("news.html", "news/index.html", "news"),
]


def build(clean: bool = False) -> None:
    start = time.time()
    print("[build] Starting site generation...")

    if clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Static assets
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, DIST_DIR / "static", dirs_exist_ok=True)

    # 2. Config
    config = load_yaml(CONFIG_FILE) or {}
    require(config, ["site_name", "institution", "base_url", "nav"], "config.yaml")
    base_path = "/" + str(config.get("base_path", "")).strip("/")
    base_path = "" if base_path == "/" else base_path
    news_kinds = {k["name"]: k for k in config.get("news_kinds", [])}

    all_themes = load_themes()
    active = config.get("theme") or next(iter(all_themes))
    if active not in all_themes:
        raise ContentError(
            f"config.yaml: theme '{active}' is not defined in themes.yaml "
            f"(available: {', '.join(all_themes)})"
        )
    switcher = bool(config.get("theme_switcher", False))
    # Only ship every theme when the preview picker is on.
    themes = all_themes if switcher else {active: all_themes[active]}
    generate_theme_css(themes)

    # 3. Collections, in dependency order
    research = load_research()
    area_slugs = {a["slug"] for a in research}
    areas_by_slug = {a["slug"]: a for a in research}
    people = load_people(area_slugs)
    publications = load_publications(area_slugs, people["by_name"])
    news = load_news(news_kinds)

    # 4. Cross-references: attach publications and people to each area
    for pub in publications:
        for slug in pub["areas"]:
            areas_by_slug[slug]["publications"].append(pub)
    for p in people["current"]:
        for slug in p["areas"]:
            areas_by_slug[slug]["people"].append(p)
    for area in research:
        area["people"].sort(key=name_key)

    latest_count = int(config.get("home_latest_publications", 5))

    # 5. Markdown content
    home = load_markdown("home")

    # 6. Jinja2 environment. StrictUndefined: a typo in a template is an error.
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    version = str(int(time.time()))  # cache-busting for CSS/JS

    def url(path: str) -> str:
        """Site-relative URL that respects base_path (for GitHub Pages subpaths)."""
        return base_path + "/" + path.lstrip("/")

    env.globals.update(
        url=url,
        static=lambda p: url("/static/" + p.lstrip("/")),
        asset=lambda p: url("/static/" + p.lstrip("/")) + "?v=" + version,
        config=config,
        areas_by_slug=areas_by_slug,
        news_kinds=news_kinds,
        themes=themes,
        active_theme=all_themes[active],
        theme_switcher=switcher,
        themes_font_json=json.dumps({n: t["font_urls"] for n, t in themes.items()}),
        current_year=datetime.date.today().year,
    )
    env.filters["markdown"] = render_markdown
    env.filters["markdown_inline"] = render_markdown_inline

    context = {
        "home": home,
        "research": research,
        "people": people,
        "publications": publications,
        "publications_by_year": group_by_year(publications),
        "latest_publications": publications[:latest_count],
        "news": news,
        "recent_news": news[:4],
    }

    for template, out, page in ROUTES:
        html = env.get_template(template).render(current_page=page, **context)
        out_file = DIST_DIR / out
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html, encoding="utf-8")

    (DIST_DIR / "404.html").write_text(
        env.get_template("404.html").render(current_page="", **context), encoding="utf-8"
    )

    # 7. Sitemap + .nojekyll (GitHub Pages must not run Jekyll on dist/)
    generate_sitemap(config)
    (DIST_DIR / ".nojekyll").touch()

    print(
        f"[build] {len(research)} research areas, {len(publications)} publications, "
        f"{len(people['current'])} members, {len(people['alumni'])} alumni, {len(news)} news items"
    )
    print(f"[build] Done in {time.time() - start:.2f}s -> {DIST_DIR.relative_to(BASE_DIR)}/")


def generate_sitemap(config: Dict[str, Any]) -> None:
    base = config["base_url"].rstrip("/") + "/" + str(config.get("base_path", "")).strip("/")
    base = base.rstrip("/")
    today = datetime.date.today().isoformat()
    urls = []
    for _, out, _ in ROUTES:
        route = "/" + out.removesuffix("index.html")
        urls.append(f"  <url><loc>{base}{route}</loc><lastmod>{today}</lastmod></url>")
    (DIST_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Development server with auto-rebuild
# ---------------------------------------------------------------------------
def serve_and_watch(port: int = 8000) -> None:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        sys.exit("[error] --serve needs watchdog: pip install watchdog")

    build(clean=True)

    class ChangeHandler(FileSystemEventHandler):
        def __init__(self):
            self.last = 0.0
            self.lock = threading.Lock()

        def on_any_event(self, event):
            path = Path(event.src_path)
            if event.is_directory or DIST_DIR in path.parents or "__pycache__" in path.parts:
                return
            if path.parent == BASE_DIR and path.name not in ("config.yaml", "themes.yaml", "build.py"):
                return
            with self.lock:
                if time.time() - self.last < 0.4:
                    return
                self.last = time.time()
            print(f"\n[watch] Changed: {path.relative_to(BASE_DIR)}")
            try:
                build()
            except ContentError as e:
                print(f"[error] {e}", file=sys.stderr)
            except Exception as e:  # keep the server alive on template errors
                print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)

    observer = Observer()
    handler = ChangeHandler()
    for d in (CONTENT_DIR, DATA_DIR, TEMPLATES_DIR, STATIC_DIR):
        if d.exists():
            observer.schedule(handler, str(d), recursive=True)
    observer.schedule(handler, str(BASE_DIR), recursive=False)
    observer.start()

    config = load_yaml(CONFIG_FILE) or {}
    base_path = "/" + str(config.get("base_path", "")).strip("/")

    class Handler(http.server.SimpleHTTPRequestHandler):
        """Serves dist/ and strips base_path, so URLs match production."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DIST_DIR), **kwargs)

        def translate_path(self, path):
            if base_path != "/" and path.startswith(base_path):
                path = path[len(base_path):] or "/"
            return super().translate_path(path)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("", port), Handler)
    home = base_path.rstrip("/") + "/"
    print(f"\n  Serving at http://localhost:{port}{home}\n  Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        server.server_close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Robust Learning Group website.")
    parser.add_argument("--clean", action="store_true", help="wipe dist/ before building")
    parser.add_argument("--serve", action="store_true", help="serve dist/ and rebuild on change")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.serve:
            serve_and_watch(args.port)
        else:
            build(clean=args.clean)
    except ContentError as e:
        sys.exit(f"[error] {e}")


if __name__ == "__main__":
    main()