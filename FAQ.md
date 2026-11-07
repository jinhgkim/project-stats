# FAQ

## How do we know what's new on a rerun?

Each source saves a bookmark (last git HEAD, last fetch time, last
main-branch sha) in `fetch_state`, and the next run stops there. `fetch --full`
ignores the bookmarks.

See `import_commits` in `projstats/gitlog.py`, and `fetch_items` and
`fetch_commit_logins` in `projstats/github.py`.

## Is the database huge?

No. For OpenImageIO it's about 19 MB, since it stores text and timestamps,
not code. The git clone in `data/repos` is bigger (about 470 MB), even though
it's fetched without file contents.

See `projstats/storage.py` for the tables and `sync_clone` in
`projstats/gitlog.py` for the clone.

## How long does processing take?

Theme tagging is the slow step: the first full run over 9,267 documents took
3.1 hours with a local 9B model (`--pause 3`). Reruns only tag new or changed
documents. `people`, `export`, and `page` each take under a second. Fetch time
wasn't recorded.

See `tag_documents` in `projstats/tagger.py`.

## How do we clean up identities and merge multi-word names?

`.mailmap` is applied first. Then emails join into one person if they share a
multi-word name (ignoring case and accents) or a GitHub login. Single-word
names never join. Bots are dropped by `[bot]` login or the config `bots` list.

See `group_people` in `projstats/identity.py`. Run `projstats people` to see
each merge and its reason.

## How is each person's activity counted?

Each action is one activity, dated when it happened: opening a PR or issue,
each review, each comment, and each commit (once per author or co-author). A
PR discussed over several months adds activity in each of those months.
Inline code-review comments aren't fetched, so they don't count.

See `load_activity` in `projstats/retention.py`.

## Do 2 commits on the same day count as 1 activity?

No, they count as 2. Activity totals (and so segments) go up by 2, but the
person still counts once in that period's active people. Only main-branch
commits are imported, so a squash-merged PR's commits count as 1.

See `load_commit_activity` in `projstats/retention.py` and `read_commits` in
`projstats/gitlog.py`.

## Are we prompting the model to make aliases?

Yes, in two steps. The tagging prompt lists existing themes and says to reuse
them, guided by `about` and `areas` in the config. Any name that still matches
nothing goes to a second prompt that asks whether it's the same as an
existing theme; if so, it becomes an alias.

See `SYSTEM` and `tag_documents` in `projstats/tagger.py`, and `MERGE_SYSTEM`
and `resolve` in `projstats/themes.py`.

## Are PRs processed first so their commits, reviews, and comments are skipped?

No ordering is needed. Reviews, comments, and commits linked to a PR are never
sent to the model. When counting, they take their PR's or issue's themes.

See `load_documents` in `projstats/documents.py` and `doc_ref_of` in
`projstats/trends.py`.

## Does recomputing in JavaScript add latency?

Not measured yet. Each filter change recomputes about 29,500 activity rows,
but only for the open tab, and `#check` runs only when it's in the address.

See `renderAll` in `projstats/page/core.js`.
