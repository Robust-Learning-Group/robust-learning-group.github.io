# Robust Learning Group website

Static site for the Robust Learning Group at CMAP, École Polytechnique.
Built by `build.py`, a single explicit Python script: YAML and Markdown in, HTML out.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python build.py --serve        # http://localhost:8000, rebuilds on every save
python build.py --clean        # production build into dist/
```

## Where things live

| To change…                         | Edit                     |
|------------------------------------|--------------------------|
| Site name, address, nav, news kinds| `config.yaml`            |
| Colours and fonts                  | `themes.yaml` (pick one with `theme:` in `config.yaml`) |
| Home page intro and headline       | `content/home.md`        |
| Research areas                     | `data/research.yaml`     |
| Publications                       | `data/publications.yaml` |
| People and alumni                  | `data/people.yaml`       |
| News                               | `data/news.yaml`         |
| Photos                             | `static/images/people/`  |
| Layout                             | `templates/`, `static/css/style.css` |

Each data file has a comment at the top describing its fields.

## How the pieces connect

- Research areas have a `slug`. Publications and people list the slugs they belong to
  in `areas:`. The build fails with a clear message if a slug does not exist.
- Author names in publications that match a person in `people.yaml` (or one of their
  `aliases`) are highlighted and linked to that person's card.
- The home page shows the most recent publications (`home_latest_publications` in `config.yaml`).
- The research page shows, for each area, the people and papers tagged with it.
- `/publications/?area=<slug>` opens the publications page pre-filtered.

## Themes

Each theme in `themes.yaml` is a list of colours (light and dark mode) plus two Google
Fonts families. To try a new look, copy an existing theme, rename it and change the values.

To compare themes with colleagues, set `theme_switcher: true` in `config.yaml`: a small
"Preview theme" picker appears in the corner of every page, and the choice is remembered
while browsing. Once you've decided, set `theme:` to the winner and `theme_switcher: false`.

## Adding a page

1. Create `templates/<page>.html` extending `base.html`.
2. Add a line to `ROUTES` in `build.py`.
3. Add an entry to `nav` in `config.yaml`.

## Deployment

`.github/workflows/deploy.yml` builds and publishes `dist/` on every push to `main`.
In the GitHub repository settings, set **Pages → Source** to **GitHub Actions**.

If the site lives under a subpath (for example `https://org.github.io/robust-learning/`),
set `base_path: "/robust-learning"` in `config.yaml`. Every internal link goes through
the `url()` helper in the templates, so nothing else needs to change.
