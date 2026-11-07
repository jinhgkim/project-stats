import os

# Keeps the user's git config (signing, hooks, aliases) out of git calls.
GIT_TEST_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def isolate_git(test) -> None:
    """Set GIT_TEST_ENV for the duration of `test`, restoring the old values."""
    for key, value in GIT_TEST_ENV.items():
        old = os.environ.get(key)
        os.environ[key] = value
        if old is None:
            test.addCleanup(os.environ.pop, key, None)
        else:
            test.addCleanup(os.environ.__setitem__, key, old)
