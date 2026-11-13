# Add a project

A project is one TOML file in `projects/`. This takes a project with themes
off (the default) from nothing to a reviewed page. You need the tools listed
under Dependencies in the README, with `gh` logged in. For filled-in
examples, see the other configs in `projects/`.

1. **Copy the template.**

   ```bash
   cp projects/template.toml projects/<name>.toml
   ```

   Set `[repo] github = "owner/name"`. Everything else has a default in
   `projstats/config.py`, and an unknown setting is an error.

2. **Set `tag_pattern`.**

   List the tags with:

   ```bash
   gh api repos/<owner>/<name>/tags --paginate --jq '.[].name'
   ```

   - It must fully match final release tags and capture major, minor, and
     patch. Betas and RCs should not match.
   - For two-number tags like `v0.15`, make the patch group optional:
     `(?:\.(\d+))?`. A missing patch counts as 0 (example:
     `projects/openfx.toml`).
   - For four-number tags like `0.41.0.0`, add an optional fourth group
     (example: `projects/oiio.toml`).

3. **Fetch.**

   ```bash
   python3 -m projstats fetch projects/<name>.toml
   ```

   - `releases: none match [releases] tag_pattern` means the pattern is wrong.

4. **Check people.**

   ```bash
   python3 -m projstats people projects/<name>.toml
   ```

   - Look at the merged identities and the dropped bots.
   - Add extra bots under `[people] bots`. Add `same_person` only when the
     evidence is clear (example: `projects/oiio.toml`).
   - Commits with no author email (common in ancient CVS imports) show up as
     `<name>@no-email.invalid`, one person per name (example:
     `projects/openfx.toml`).

5. **Build the page.**

   ```bash
   python3 -m projstats export projects/<name>.toml
   python3 -m projstats page projects/<name>.toml --open
   ```

   Add `#check` to the address to compare the browser's numbers with Python's.

6. **Decide on `leave_out_option`.**

   The concentration view shows each person's share of activity. If one
   person's share is large, add
   `leave_out_option = { maintainer = "github-login" }` under `[people]` and
   rerun `export` and `page`.

7. **Add it to the daily deploy.**

   List `projects/<name>.toml` in `deploy.toml` so the daily workflow
   (`.github/workflows/deploy.yml`) fetches it and builds its page.
