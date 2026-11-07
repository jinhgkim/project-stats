import unittest

from projstats import storage
from projstats.identity import (
    Identity,
    group_people,
    load_identities,
    name_key,
    noreply_login,
)


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


if __name__ == "__main__":
    unittest.main()
