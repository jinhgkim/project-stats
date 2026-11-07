# project-stats

Shows project activity analytics over time, and which themes
(lasting efforts or functional areas) get work and discussion. OpenImageIO is
the first project.

The output is one self-contained web page with three tabs. A pinned top bar
holds the filters: dates, activity (all, code, or discussion), leaving out a
very active person, and theme, plus Group by for the period shown on Overview
and People. They live in the URL, so a view can be bookmarked or shared.

- **Overview:** three summary tiles (active, new, and core people) and
  contributors per month, quarter, year, or release cycle, split into new,
  returning, and continuing.
- **People:** how concentrated the activity is, as a curve with segments
  (core, regular, casual, one-time) as zones, with a list of the people in
  each zone, and a timeline of one segment's people at a time.
- **Themes:** each theme's share of activity per release cycle as a heatmap
  (rising and fading shows on hover), and a table of each theme's
  documents, first and last seen, peak, and top people.

## How it works

```
┌──────────────────┐   ┌───────────────────────────┐
│ git history      │   │ GitHub (via `gh`)         │
│ commits          │   │ PRs, reviews, issues,     │
│                  │   │ comments, labels          │
└────────┬─────────┘   └─────────────┬─────────────┘
         └──────────────┬────────────┘
                        ▼  projstats fetch
┌─────────────────────────────────────────────────┐
│ SQLite cache: data/<owner>__<repo>.db           │
└───────┬───────────────────────────────┬─────────┘
        ▼                               ▼  projstats tag
┌───────────────────────┐  ┌──────────────────────────────┐
│ identity: group       │  │ local LLM (Ollama) tags each │
│ names and emails into │  │ PR, issue, and unlinked      │
│ people                │  │ commit with 0 to 3 themes    │
└───────┬───────────────┘  └──────────────┬───────────────┘
        ▼                                 ▼
┌───────────────────────┐  ┌──────────────────────────────┐
│ retention: activity   │  │ trends: theme share per      │
│ per period, people    │  │ release cycle, new, rising,  │
│ segments, returns     │  │ and fading themes            │
└───────┬───────────────┘  └──────────────┬───────────────┘
        └─────────────┬───────────────────┘
                      ▼  projstats export, projstats page
┌─────────────────────────────────────────────────┐
│ one HTML page: data as JSON + D3 charts         │
│ filtering and counting happen in the browser    │
└─────────────────────────────────────────────────┘
```

- **Fetch once, compute on demand.** Everything is fetched into SQLite.
  Reruns only fetch what's new.
- **People:** identities with the same multi-word name or GitHub login
  count as one person. Bots are dropped.
- **Themes are found bottom-up**, not picked from a fixed list. The model
  reads documents oldest first and reuses theme names it has already made,
  so early names stick. New names that mean the same as an existing theme
  become aliases. Fix the rest by hand with `themes rename`, `merge`, or
  `delete`.
- **Commits, reviews, and comments inherit their PR's themes.**
- **Segments** rank people by activity: core is the fewest people who
  together reach a share of it (80% by default), regular the next up to 90%.
  Leaving a person out keeps the same people in each segment, and the shares
  are of the activity that remains.
- **Python is the reference.** The page recomputes everything in JavaScript
  for its filters. Opening the page with `#check` compares those numbers to
  Python's.
- **Project rules live in config**, e.g. `projects/oiio.toml`: bots, release
  tag pattern, segment cutoffs, model, and tagging settings.

## Dependencies

No Python packages: `pyproject.toml` lists none.

| Needs | Used by | For |
|---|---|---|
| Python 3.11+ | everything | the `projstats` commands |
| git | `fetch` | cloning and reading the repository's history |
| `gh` CLI, logged in | `fetch` | PRs, reviews, issues, and comments through GitHub's GraphQL API |
| Ollama, with the model named in the config | `tag` | tagging documents with themes (not needed when themes are off) |
| D3 7.9.0, loaded from cdnjs | the page, when you open it | drawing the charts, so the page needs internet |

Ollama is only needed for tagging. Fetching, building the page, and the
Overview and People tabs work without it.

`page --open` uses macOS's `open` command to show the page.

## Usage

Themes are optional. For analytics only, set `enabled = false` under
`[themes]` in the config: the Themes tab and the theme filter are left out of
the page, and `tag` stops without calling Ollama.

```
python3 -m projstats fetch  projects/oiio.toml   # clone/update + GitHub data
python3 -m projstats people projects/oiio.toml   # check how people were grouped
python3 -m projstats tag    projects/oiio.toml   # tag documents with themes
python3 -m projstats themes projects/oiio.toml list
python3 -m projstats export projects/oiio.toml   # data/<owner>__<repo>.json
python3 -m projstats page   projects/oiio.toml --open
```
