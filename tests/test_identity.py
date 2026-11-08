import unittest

from projstats import storage
from projstats.identity import (
    Identity,
    group_people,
    load_github_logins,
    load_identities,
    load_links,
    load_people,
    name_key,
    noreply_login,
    unmatched_links,
)
from tests.github_rows import add_commit, add_commit_login, add_event, add_item


def ids(*rows):
    return [Identity(name, email, count) for name, email, count in rows]


class NameKeyTest(unittest.TestCase):
    def test_ignores_case_spacing_and_accents(self):
        self.assertEqual(name_key("Aras  Pranckevičius"), "aras pranckevicius")
        self.assertEqual(name_key("aras pranckevicius"), "aras pranckevicius")

    def test_single_word_names_have_no_key(self):
        self.assertIsNone(name_key("Luc"))
        self.assertIsNone(name_key("  zachlewis "))


class NoreplyLoginTest(unittest.TestCase):
    def test_both_formats(self):
        self.assertEqual(noreply_login("123+Octo@users.noreply.github.com"), "octo")
        self.assertEqual(noreply_login("octo@users.noreply.github.com"), "octo")

    def test_other_emails(self):
        self.assertIsNone(noreply_login("octo@example.com"))


class GroupPeopleTest(unittest.TestCase):
    def test_shared_multi_word_name_merges(self):
        result = group_people(
            ids(("Ann Lee", "ann@a.example", 3), ("ann lee", "ann@b.example", 1))
        )
        self.assertEqual(len(result.people), 1)
        p = result.people[0]
        self.assertEqual(p.emails, {"ann@a.example", "ann@b.example"})
        self.assertEqual(p.reasons, ["name 'ann lee'"])

    def test_shared_single_word_name_does_not_merge(self):
        result = group_people(
            ids(("Luc", "luc@a.example", 1), ("Luc", "luc@b.example", 1))
        )
        self.assertEqual(len(result.people), 2)

    def test_noreply_login_merges_with_link(self):
        result = group_people(
            ids(("zl", "zl@users.noreply.github.com", 2), ("Z", "z@work.example", 1)),
            links=[("Z@work.example", "ZL")],
        )
        self.assertEqual(len(result.people), 1)
        self.assertEqual(result.people[0].logins, {"zl"})
        self.assertIs(result.by_login["zl"], result.by_email["z@work.example"])

    def test_merges_chain(self):
        # a and b share a name; b and c share a login.
        result = group_people(
            ids(
                ("Ann Lee", "a@x.example", 1),
                ("Ann Lee", "b@x.example", 1),
                ("al", "al@users.noreply.github.com", 1),
            ),
            links=[("b@x.example", "al")],
        )
        self.assertEqual(len(result.people), 1)
        self.assertEqual(len(result.people[0].emails), 3)

    def test_display_name_and_key_follow_activity(self):
        result = group_people(
            ids(
                ("Zach Lewis", "zl@users.noreply.github.com", 26),
                ("zachlewis", "zl@users.noreply.github.com", 13),
                ("Zach Lewis", "zach@work.example", 40),
            )
        )
        p = result.people[0]
        self.assertEqual(p.name, "Zach Lewis")
        self.assertEqual(p.key, "zach@work.example")
        self.assertEqual(p.activity, 79)

    def test_bots_dropped(self):
        result = group_people(
            ids(
                ("dependabot[bot]", "1+dependabot[bot]@users.noreply.github.com", 9),
                ("Copilot", "2+copilot@users.noreply.github.com", 4),
                ("Ann Lee", "ann@a.example", 1),
            ),
            bots=["Copilot"],
        )
        self.assertEqual([p.key for p in result.people], ["ann@a.example"])
        self.assertEqual(len(result.bots), 2)
        self.assertNotIn("copilot", result.by_login)

    def test_ai_tools_dropped_without_any_config(self):
        result = group_people(
            ids(
                ("Cursor", "cursoragent@cursor.com", 30),
                ("Claude Sonnet 4.6", "noreply@anthropic.com", 12),
                ("Claude Sonnet 5.5", "noreply@anthropic.com", 1),
                ("Codex", "noreply@openai.com", 2),
                ("Copilot App", "9+Copilot@users.noreply.github.com", 1),
                ("Ann Lee", "ann@a.example", 1),
            ),
            links=[("cursoragent@cursor.com", "cursoragent")],
        )
        self.assertEqual([p.key for p in result.people], ["ann@a.example"])
        self.assertEqual(len(result.bots), 4)

    def test_ai_tool_logins_dropped_without_a_commit_identity(self):
        result = group_people([], github_logins={"claude": 3, "cursoragent": 1})
        self.assertEqual(result.people, [])
        self.assertEqual(len(result.bots), 2)

    def test_humans_with_lookalike_names_kept(self):
        result = group_people(
            ids(
                ("Claude", "claude@a.example", 5),
                ("Harry Mallon", "harry.mallon@codex.online", 6),
            ),
            github_logins={"claudeha": 7},
        )
        self.assertEqual(len(result.people), 3)
        self.assertEqual(result.bots, [])


class LoadIdentitiesTest(unittest.TestCase):
    def test_counts_authors_and_coauthors_case_insensitively(self):
        conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        rows = [
            ("c1", "Ann Lee", "Ann@a.example"),
            ("c2", "Ann Lee", "ann@a.example"),
            ("c3", "Bo Ma", "bo@b.example"),
        ]
        conn.executemany(
            "INSERT INTO commits VALUES (?, 0, 0, ?, ?, ?, ?, '', '')",
            [(sha, n, e, n, e) for sha, n, e in rows],
        )
        conn.execute(
            "INSERT INTO commit_coauthors VALUES "
            "('c3', 'Ann Lee', 'ann@a.example', 'Ann Lee', 'ann@a.example')"
        )
        self.assertEqual(
            load_identities(conn),
            ids(("Ann Lee", "ann@a.example", 3), ("Bo Ma", "bo@b.example", 1)),
        )


class GithubLoginsTest(unittest.TestCase):
    def test_link_joins_commit_person_and_login(self):
        result = group_people(
            ids(("Ann Lee", "ann@a.example", 1)),
            links=[("ann@a.example", "annl")],
            github_logins={"AnnL": 5},
        )
        self.assertEqual(len(result.people), 1)
        p = result.people[0]
        self.assertEqual((p.key, p.logins, p.activity), ("ann@a.example", {"annl"}, 6))
        self.assertIs(result.by_login["annl"], p)

    def test_unlinked_login_becomes_login_only_person(self):
        result = group_people(
            ids(("Ann Lee", "ann@a.example", 1)), github_logins={"Hara-Yoki": 3}
        )
        p = result.by_login["hara-yoki"]
        self.assertEqual(
            (p.key, p.name, p.emails), ("login:hara-yoki", "Hara-Yoki", set())
        )
        self.assertEqual(len(result.people), 2)

    def test_login_only_bots_dropped(self):
        result = group_people(
            [], bots=["helper"], github_logins={"renovate[bot]": 2, "helper": 1}
        )
        self.assertEqual(result.people, [])
        self.assertEqual(len(result.bots), 2)

    def test_logins_sharing_a_commitless_email_are_one_person(self):
        result = group_people(
            [],
            links=[("x@e.example", "a"), ("x@e.example", "b")],
            github_logins={"a": 3, "b": 1},
        )
        self.assertEqual(len(result.people), 1)
        p = result.people[0]
        self.assertEqual((p.key, p.logins, p.activity), ("login:a", {"a", "b"}, 4))


class ManualLinksTest(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)
        add_commit(self.conn, "c1", 1, "Rob Mat", "rob@x.example")
        add_item(self.conn, "I1", 1, "pr", "rob-mat", 10)

    def test_listed_link_joins_login_to_commit_identity(self):
        links = [("Rob@X.example", "Rob-Mat")]
        before = load_people(self.conn)
        self.assertEqual(len(before.people), 2)
        after = load_people(self.conn, manual_links=links)
        self.assertEqual(len(after.people), 1)
        p = after.people[0]
        self.assertEqual((p.emails, p.logins), ({"rob@x.example"}, {"rob-mat"}))
        self.assertEqual(p.reasons, ["listed in config: login 'rob-mat'"])
        self.assertEqual(unmatched_links(self.conn, links), [])

    def test_unmatched_entries_are_reported(self):
        links = [("typo@x.example", "rob-mat"), ("rob@x.example", "nobody")]
        self.assertEqual(
            unmatched_links(self.conn, links),
            ["nobody: no GitHub activity", "typo@x.example: no commits with this email"],
        )


class LoadGithubTest(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_links_use_mailmapped_emails(self):
        add_commit(
            self.conn,
            "c1",
            1,
            "Alice Smith",
            "alice@new.example",
            "Alice",
            "Alice@Old.example",
        )
        add_commit_login(self.conn, "c1", "alice@old.example", "alicegh")
        add_commit_login(self.conn, "c1", "other@x.example", None)
        self.assertEqual(load_links(self.conn), [("alice@new.example", "alicegh")])

    def test_github_logins_skip_ghosts_and_vanished_rows(self):
        add_item(self.conn, "I1", 1, "pr", "alicegh", 10)
        add_item(self.conn, "I2", 2, "issue", None, 10)
        add_item(self.conn, "I3", 3, "issue", "bo", 10, vanished=99)
        add_event(self.conn, "E1", "I1", "comment", "bo", 11)
        add_event(self.conn, "E2", "I1", "comment", "bo", 12, vanished=99)
        add_event(self.conn, "E3", "I3", "comment", "bo", 13)  # on a vanished item
        self.assertEqual(load_github_logins(self.conn), {"alicegh": 1, "bo": 1})


if __name__ == "__main__":
    unittest.main()
