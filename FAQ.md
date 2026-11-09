# FAQ

## Data and setup

### How do we know what's new on a rerun?

Each source saves a bookmark (last git HEAD, last fetch time, last
main-branch sha) in `fetch_state`, and the next run stops there. `fetch --full`
ignores the bookmarks.

See `import_commits` in `projstats/gitlog.py`, and `fetch_items` and
`fetch_commit_logins` in `projstats/github.py`.

### Is the database huge?

No. For OpenImageIO it's about 19 MB, since it stores text and timestamps,
not code. The git clone in `data/repos` is bigger (about 470 MB), even though
it's fetched without file contents.

See `projstats/storage.py` for the tables and `sync_clone` in
`projstats/gitlog.py` for the clone.

## Speed and resources

### How long does processing take?

Theme tagging is the slow step: the first full run over 9,267 documents took
3.1 hours with a local 9B model (`--pause 5`). Reruns only tag new or changed
documents. `people`, `export`, and `page` each take under a second.

With themes off (the default), a first run takes minutes. For
OpenImageIO (6,872 commits, 4,508 PRs, 1,083 issues), a first `fetch`,
including the clone, took 5 min 49 s and 173 GitHub queries.

See `tag_documents` in `projstats/tagger.py`.

### Does the model run on a GPU, and how much memory does it need?

Yes. On an Apple M5 Pro (24 GB unified memory), `ollama ps` showed the 9B
model at 100% GPU and 6.2 GB loaded with the default `context` of 32768,
measured after a short prompt. This is subject to change as we explore
improvements in tagging though.

See `OllamaConfig` in `projstats/config.py`.

### Does recomputing in JavaScript add latency?

Not measured yet. Each filter change recomputes about 29,500 activity rows,
but only for the open tab, and `#check` runs only when it's in the address.

See `renderAll` in `projstats/page/core.js`.

## People and activity

### How do we clean up identities and merge multi-word names?

`.mailmap` is applied first. Then emails join into one person if they share a
multi-word name (ignoring case and accents) or a GitHub login. Single-word
names never join. Bots are dropped by `[bot]` login, a built-in list of AI
tools (Claude, Cursor, Codex, Copilot), or the config `bots` list.

See `group_people` in `projstats/identity.py`. Run `projstats people` to see
each merge and its reason.

### How is each person's activity counted?

Each action is one activity, dated when it happened: opening a PR or issue,
each review, each comment, and each commit (once per author or co-author). A
PR discussed over several months adds activity in each of those months.
Inline code-review comments aren't fetched, so they don't count.

Example: Ana opens a PR in January and comments on it in February and March.
Ben approves it in April. Ana has 3 activities (January, February, March) and
Ben has 1 (April), so both count as active in those months.

See `load_activity` in `projstats/retention.py`.

### Do 2 commits on the same day count as 1 activity?

No, they count as 2. Activity totals (and so segments) go up by 2, but the
person still counts once in that period's active people. Only main-branch
commits are imported, so a squash-merged PR's commits count as 1.

See `load_commit_activity` in `projstats/retention.py` and `read_commits` in
`projstats/gitlog.py`.

## Theme tagging

### How does tagging work?

Two prompts do the work: the tagging prompt, which proposes themes, and a merge
check, which decides whether a new name is an alias. Documents (PRs, issues,
and commits not linked to a PR) go to the local model in batches, oldest
first. For each batch:

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

Reviews, comments, and commits linked to a PR take their PR's themes. Reruns
only tag new or changed documents.

See `SYSTEM`, `tag_documents`, and `parse` in `projstats/tagger.py`, and
`MERGE_SYSTEM` and `resolve` in `projstats/themes.py`.

### Does tagging use text embeddings?

No. It's a prompt-driven workflow, with no text embeddings or similarity
scores. We just wanted a quick first pass over the data for the initial effort.
Coming up with themes and deciding whether to merge them are both
prompt-driven, but normalizing the names and the cleanups are plain code.

See `SYSTEM` and `parse` in `projstats/tagger.py`, and `MERGE_SYSTEM` and
`theme_key` in `projstats/themes.py`.

### Are PRs processed first so their commits, reviews, and comments are skipped?

No ordering is needed. Reviews, comments, and commits linked to a PR are never
sent to the model. When counting, they take their PR's or issue's themes.

See `load_documents` in `projstats/documents.py` and `doc_ref_of` in
`projstats/trends.py`.
