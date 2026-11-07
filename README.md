# project-stats

Shows project activity analytics over time, and which themes
(lasting efforts or functional areas) get work and discussion. OpenImageIO is
the first project.

The output is one self-contained web page with three tabs:

- **Overview:** summary numbers and contributors per month, quarter, year,
  or release cycle.
- **People:** retention, cohorts, segments (core, regular, casual,
  one-time), and a timeline of each person's activity.
- **Themes:** each theme's share of activity per release cycle, plus rising
  and fading themes.

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
│ per period, cohorts,  │  │ release cycle, new, rising,  │
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
- **Python is the reference.** The page recomputes everything in JavaScript
  for its filters. Opening the page with `#check` compares those numbers to
  Python's.
- **Project rules live in config**, e.g. `projects/oiio.toml`: bots, release
  tag pattern, segment cutoffs, model, and tagging settings.

## Usage

Needs Python 3.11+, git, the `gh` CLI (logged in), and Ollama with the model
named in the config. No Python dependencies.

```
python3 -m projstats fetch  projects/oiio.toml   # clone/update + GitHub data
python3 -m projstats people projects/oiio.toml   # check how people were grouped
python3 -m projstats tag    projects/oiio.toml   # tag documents with themes
python3 -m projstats themes projects/oiio.toml list
python3 -m projstats export projects/oiio.toml   # data/<owner>__<repo>.json
python3 -m projstats page   projects/oiio.toml --open
```
