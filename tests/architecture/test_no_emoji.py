"""No emoji anywhere in source.

Comments, docstrings, log strings, error messages, and `Field(description=...)`
alike. Emoji in source is a documented LLM tell that accumulates as noise
across reviews, and it has no place in a log line an operator greps.

Scope is pictographic ranges ONLY. An earlier version of this check also swept
the arrows block and patched over the fallout with an allowlist of four
arrows, which meant it silently banned every other arrow: a docstring drawing
a mapping with a double arrow or a maps-to arrow failed a check named "no
emoji". A rule that fails for a reason its name does not describe is a rule
people learn to suppress, so the arrows are simply out of scope.
"""

import re

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, symbols
    "\U0001f000-\U0001f0ff"  # mahjong, dominoes, cards
    "\U0001f900-\U0001f9ff"  # supplemental symbols, faces, gestures
    "\u2600-\u27bf"  # misc symbols and dingbats
    "]"
)


def test_tracked_python_files_carry_no_emoji() -> None:
    hits: list[str] = []
    for path in sorted(tracked_python_files()):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            found = _EMOJI.findall(line)
            if found:
                hits.append(f"{path}:{lineno}: {found!r} in {line.strip()}")
    assert not hits, "Emoji in source:\n" + "\n".join(hits)
