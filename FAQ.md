# FAQ

## Data and setup

### How do we know what's new on a rerun?

Each source saves a bookmark in `fetch_state`, and the next run starts from it:

- **Commits:** the last imported HEAD. The next run reads only the commits
  after it.
- **PRs and issues:** when the last run started.
  - GitHub lists them newest updated first, and the fetch stops at the first
    one last updated more than a day before that time.
  - A new comment moves an item's `updatedAt`, so an old PR with a new comment
    is read again and saved over its old row.
  - Nothing is compared with the database.
- **Commit logins:** the newest main-branch sha handled.

`fetch --full` ignores the bookmarks.

See `import_commits` in `projstats/gitlog.py`, and `fetch_items` and
`fetch_commit_logins` in `projstats/github.py`.

### What's in the git clone and the database, and how big are they?

- **Sizes:**
  - The sizes here are for OpenImageIO (6,872 commits, 4,508 PRs, 1,083 issues
    when measured).
  - Other projects scale with their history: OpenEXR's database is about
    12 MB and OpenFX's about 1 MB, while a project with themes and a long
    history, like Gaffer, is about 31 MB.
- **The clone** in `data/repos`:
  - A read-only copy of the project's git history: commits, folder listings,
    and tags, but no file contents (git downloads `.mailmap` when it's needed).
  - A fresh OpenImageIO one is about 13 MB, takes seconds to make, and uses no
    GitHub API budget.
  - Only the databases are saved to the data repo, so CI makes a fresh clone on
    every run.
- **The database** is filled by two separate fetches plus the model:
  - Commits are read out of the clone with `git log`.
  - PRs, issues, reviews, and comments come from the GitHub API.
  - Themes come from the model.
  - For OpenImageIO it's about 19 MB, of which about 7.5 MB is the text of PRs,
    issues, and commit messages.
- **What isn't stored:**
  - Comments and reviews keep only who, when, and what kind, with no text.
  - Code and diffs are not stored.
  - PRs, issues, and reviews exist only on GitHub and in the database.

See `sync_clone` in `projstats/gitlog.py`, the tables in `projstats/storage.py`,
and `COMMENT_FIELDS` and `REVIEW_FIELDS` in `projstats/github.py`.

### How much of the GitHub API budget does a fetch use?

- **Cost:** GitHub's GraphQL API charges points.
  - A page of 50 PRs costs 2.
  - A page of 100 issues costs 2.
  - A page of 100 commit logins costs 1.
  - The git clone costs none.
- **Examples:**
  - A first fetch of OpenFX (743 commits, 195 PRs, 93 issues) cost 19 points
    over 14 queries.
  - A rerun that read 4 PRs and 2 issues cost 5.
- **Hourly limit,** per GitHub's docs:
  - 5,000 points for a personal token.
  - 1,000 per repository for the `GITHUB_TOKEN` in GitHub Actions.
  - 15,000 when the requests are for resources that belong to an enterprise
    account.
- **Safety stop:** `fetch` stops with an error when fewer than 50 points are
  left.

See `RATE_FLOOR` and `Fetcher` in `projstats/github.py`.

### Where does the data come from, and how does it reach the site?

- **Sources:** a project's git history, read from a local clone, and GitHub's
  API, through `gh`. `fetch` puts both into one SQLite database per project,
  `data/<owner>__<repo>.db`.
- **Where the databases live:** the databases of the deployed projects are in
  the private repo `project-stats-data`, because they contain commit emails.
- **The site** is built by the daily Deploy run.

See `.github/workflows/deploy.yml`, `cmd_fetch` in `projstats/cli.py`, and
`build` in `projstats/deploy.py`.

## Speed and resources

### Where does theme tagging happen?

- **First run for a new project:** on a local Mac (Apple M5 Pro, 24 GB unified
  memory), with the `ornith-1.5:9b` model (6.6 GB) running on the GPU through
  Ollama.
  - OpenShadingLanguage took about 42 minutes for 4,224 documents.
  - Not on CI, because the runner has no GPU and a first run there takes too
    long.
- **Daily run on CI:** tags only the documents the fetch added.

See `tag_documents` in `projstats/tagger.py` and the "Tag new documents" step in
`.github/workflows/deploy.yml`.

## People and activity

### How do we clean up identities and merge multi-word names?

- `.mailmap` is applied first.
- Then emails join into one person if they share a multi-word name (ignoring
  case and accents) or a GitHub login.
- Single-word names never join.
- Bots are dropped by `[bot]` login, a built-in list of AI tools (Claude,
  Cursor, Codex, Copilot), or the config `bots` list.

See `group_people` and `name_key` in `projstats/identity.py`, and
`map_identities` in `projstats/gitlog.py`. Run `projstats people` to see each
merge and its reason.

### How is each person's activity counted?

- **What counts:** each action is one activity, dated when it happened.
  - Opening a PR or issue.
  - Each review.
  - Each comment.
  - Each commit (once per author or co-author). Only main-branch commits are
    imported, so a squash-merged PR's commits count as 1.
- **Same day:** 2 commits on the same day count as 2 activities, not 1. Activity
  totals (and so segments) go up by 2, but the person still counts once in that
  period's active people.
- **Over time:** a PR discussed over several months adds activity in each of
  those months.
- **Not counted:** inline code-review comments aren't fetched.

Example: Ana opens a PR in January and comments on it in February and March.
Ben approves it in April. Ana has 3 activities (January, February, March) and
Ben has 1 (April), so both count as active in those months.

See `load_activity` and `load_commit_activity` in `projstats/retention.py`, and
`read_commits` in `projstats/gitlog.py`.

## Theme tagging

### How does tagging work?

Two prompts do the work:

- The tagging prompt, which proposes themes.
- A merge check, which decides whether a new name is an alias.

Documents (PRs, issues, and commits not linked to a PR) go to the model
in batches, oldest first. For each batch:

1. The prompt has the project's `about` and `areas`, the rules, the themes made
   so far (most used first), and the batch's items.
2. The model gives each item 0 to `max_per_doc` themes, reusing an existing
   name when one fits, and a one-line description for each new name.
3. Plain code drops generic or project-wide names and duplicates, strips text
   the model copied from the theme list, and caps the count.
4. Names that match no existing theme or alias (ignoring case, accents, and
   punctuation) go to the merge check, a second prompt that asks whether each
   is the same as an existing theme or another new name. If so, it becomes an
   alias; if not, it becomes a new theme. There is no second call when every
   name matches, or when the very first theme is the only name.
5. The tags are saved, and the next batch sees the new themes, so early names
   stick.

Also:

- Reviews, comments, and commits linked to a PR take their PR's themes.
- Reruns only tag new or changed documents.

See `SYSTEM`, `tag_documents`, and `parse` in `projstats/tagger.py`, and
`MERGE_SYSTEM` and `resolve` in `projstats/themes.py`.

### Does tagging use text embeddings?

- **No.** It's a prompt-driven workflow, with no text embeddings or similarity
  scores. We just wanted a quick first pass over the data for the initial
  effort.
- Coming up with themes and deciding whether to merge them are both
  prompt-driven.
- Normalizing the names and the cleanups are plain code.

See `SYSTEM` and `parse` in `projstats/tagger.py`, and `MERGE_SYSTEM` and
`theme_key` in `projstats/themes.py`.

### Are PRs processed first so their commits, reviews, and comments are skipped?

- **No ordering is needed.**
- Reviews, comments, and commits linked to a PR are never sent to the model.
- When counting, they take their PR's or issue's themes.

See `load_documents` in `projstats/documents.py` and `doc_ref_of` in
`projstats/trends.py`.
