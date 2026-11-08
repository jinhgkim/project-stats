# project-stats

- **Contributor trends:** how contributor activity changes over time, from a
  project's git history and its GitHub PRs, reviews, issues, and comments.
- **Theme trends (optional):** which themes (lasting efforts or functional
  areas) get work and discussion, tagged by a local LLM.

Live pages: https://jinhgkim.github.io/project-stats/

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
└────────────────────────┬────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────┐
│ identity: group names and emails into people    │
│ retention: activity per period, people          │
│ segments, returns                               │
└────────────────────────┬────────────────────────┘
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
- **Segments** list people by activity: core is the fewest people who
  together reach a share of it (80% by default), regular the next up to 90%.
  Leaving a person out keeps the same people in each segment, and the shares
  are of the activity that remains.
- **Python is the ground truth.** The page redoes its calculations in
  JavaScript so filters work in the browser. Opening it with `#check` compares
  those results to Python's for a fixed set of cases.
- **Project rules live in config**, e.g. `projects/oiio.toml`: extra bots,
  release tag pattern, and segment cutoffs.

## Dependencies

No Python packages: `pyproject.toml` lists none.

| Needs | Used by | For |
|---|---|---|
| Python 3.11+ | everything | the `projstats` commands |
| git | `fetch` | cloning and reading the repository's history |
| `gh` CLI, logged in | `fetch` | PRs, reviews, issues, and comments through GitHub's GraphQL API |
| D3 7.9.0, loaded from cdnjs | the page, when you open it | drawing the charts, so the page needs internet |
| Ollama (optional) | `tag` | tagging documents with themes |

`page --open` uses macOS's `open` command to show the page.

## Usage

```
python3 -m projstats fetch  projects/oiio.toml   # clone/update + GitHub data
python3 -m projstats people projects/oiio.toml   # check how people were grouped
python3 -m projstats export projects/oiio.toml   # data/<owner>__<repo>.json
python3 -m projstats page   projects/oiio.toml --open
```

## Read-only by design

projstats only reads from GitHub. `GhClient` (`projstats/github.py`) refuses
any GraphQL mutation or subscription before calling `gh`. For a hard limit,
log `gh` in with a read-only token.

## Theme tagging (optional, needs a local LLM)

Themes are optional and off by default, and `tag` stops without calling
Ollama. To tag themes, set `enabled = true` under `[themes]` in the config,
then run `tag` between `people` and `export`. Tagging needs
[Ollama](https://ollama.com) running locally with the model named under
`[ollama]` in the config. Nothing else in projstats uses it.

```
┌─────────────────────────────────────────────────┐
│ SQLite cache: data/<owner>__<repo>.db           │
└────────────────────────┬────────────────────────┘
                         ▼  projstats tag
┌─────────────────────────────────────────────────┐
│ local LLM (Ollama) tags each PR, issue, and     │
│ unlinked commit with 0 to 3 themes              │
└────────────────────────┬────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────┐
│ trends: theme share per release cycle, new,     │
│ rising, and fading themes                       │
└────────────────────────┬────────────────────────┘
                         ▼  projstats export, projstats page
┌─────────────────────────────────────────────────┐
│ the page, with theme data                       │
└─────────────────────────────────────────────────┘
```

- **Themes are found bottom-up**, not picked from a fixed list. The model
  reads documents oldest first and reuses theme names it has already made,
  so early names stick. New names that mean the same as an existing theme
  become aliases. Fix the rest by hand with `themes rename`, `merge`, or
  `delete`.
- **Commits, reviews, and comments inherit their PR's themes.**
- **The config steers the model:** `about` and `areas` under `[themes]`
  describe the project, and `max_per_doc` caps themes per document.
- **Reruns only tag new or changed documents.** `--force` re-tags everything,
  `--pause N` rests between model calls, and `--sample N` is a dry run that
  saves nothing.
- **A first full run is slow:** see the timings in [FAQ.md](FAQ.md).

```
python3 -m projstats tag    projects/oiio.toml   # tag documents with themes
python3 -m projstats themes projects/oiio.toml list
```
