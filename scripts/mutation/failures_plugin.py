"""Pytest plugin that activates MUTATION_MUTANT after collection and records failing tests.

Collection runs unmutated, as under mutmut, so import-time calls see the original code.
A test running longer than MUTATION_TEST_TIMEOUT seconds fails, which counts as a kill.
"""

import os
import signal
from pathlib import Path

import pytest
from mutmut.mutation.trampoline import set_mutant_under_test

_failed: set[str] = set()


def _timeout(signum, frame):
    raise TimeoutError("mutation test timeout")


def pytest_collection_finish(session):
    set_mutant_under_test(os.environ["MUTATION_MUTANT"])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    signal.signal(signal.SIGALRM, _timeout)
    signal.setitimer(signal.ITIMER_REAL, float(os.environ.get("MUTATION_TEST_TIMEOUT", "30")))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def pytest_runtest_logreport(report):
    if report.failed:
        _failed.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    Path(os.environ["MUTATION_FAILURES_FILE"]).write_text("\n".join(sorted(_failed)))
