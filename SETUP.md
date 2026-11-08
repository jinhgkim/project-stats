# Setting up a new project

A project is one TOML file in `projects/`. Copy `projects/template.toml` and
set `[repo] github`; that is the only required setting. The commented lines in
it show the defaults. Any setting left out uses the default in
`projstats/config.py`; an unknown setting is an error. For filled-in examples,
see `projects/openexr.toml` (themes off) and `projects/oiio.toml` (themes on).
The sections below explain each setting.

## Before you start

- Python 3.11+, `git`, and `gh` logged in (`gh auth status`).
- Ollama with the configured model, only if you turn themes on.

## Required

- `[repo] github`: `"owner/name"`. Names the database, clone, JSON, and page
  (`data/<owner>__<name>.*`).

## Check before the first run

- `[repo] label`: short name on the page. Defaults to `github`.
- `[releases] tag_pattern`: a regex that fully matches final release tags and
  captures major, minor, and patch (a fourth number is optional). Betas and
  RCs should not match. Each major.minor's earliest match is its release.
  - List the tags: `gh api repos/<owner>/<name>/tags --paginate --jq '.[].name'`
  - The default is `^v?(\d+)\.(\d+)\.(\d+)$`.
  - Release cycles on the page come from these tags, so a pattern that
    matches nothing leaves no cycles.

## Optional, better after a first look at the data

- `[people] leave_out_option`: `{ label = "github-login" }`. Adds a checkbox
  that leaves one very active person out. The page shows the label, never the
  name. Check their share of activity after `fetch` and add it only if it is
  large.
- `[people] bots`: extra names, emails, or logins to drop. Logins ending in
  `[bot]` are always dropped.
- `[activity] exclude_items`: PR or issue numbers left out of every count,
  with their linked commits. For one-off spikes, such as a license change that
  drew many commenters.
- `[retention]`: `return_gap_days` (365), `core_share` (0.80) and
  `regular_share` (0.90). Segments are defined in the README.
- `.mailmap` in the repo is applied first when grouping people. Run `people`
  to see each merge and why.

## Themes (off by default)

- Set `[themes] enabled = true` to tag documents and get the Themes tab.
- Then also set:
  - `[themes] about`: one sentence about the project.
  - `[themes] areas`: its main areas, so themes name a specific one.
  - `[themes] project_names`: names of the project itself, so themes named
    after it get dropped.
- `[ollama]` (host, model, timeout, context, think) and the other `[themes]`
  limits have defaults. See `projects/oiio.toml` for the values used there.
- Tagging is slow (hours on a first run), so wrap it in `caffeinate -i`.

## Run

```
python3 -m projstats fetch  projects/<name>.toml   # clone + GitHub data
python3 -m projstats people projects/<name>.toml   # check the grouping
python3 -m projstats tag    projects/<name>.toml   # only with themes on
python3 -m projstats export projects/<name>.toml
python3 -m projstats page   projects/<name>.toml --open
```

- The first `fetch` of a large repo took under 6 minutes (FAQ.md). Reruns only
  fetch what is new.
- Open the page with `#check` added to the address to compare the browser's
  numbers with Python's.
- The project switcher on the page lists the other configs in `projects/`
  whose pages have been built.
