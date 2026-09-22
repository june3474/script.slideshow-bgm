"""Tests for the shipped ``strings.po`` files (specs/002 FR-012, SC-007).

Kodi shows a raw string id -- or nothing -- for an id a language file does not
define, so what these pin down is that the four shipped languages stay in step
and that the consent dialog's body survives translation with its pointer to the
README section intact.
"""

import pathlib
import re
from typing import Dict, Tuple

import pytest

LANGUAGES = ["en_gb", "ko_kr", "es_es", "fr_fr"]
CONSENT_HEADING = 32006
CONSENT_BODY = 32007
README_SECTION = "2. Skin integration"

_LANGUAGE_DIR = pathlib.Path(__file__).resolve().parents[2] / "resources" / "language"
_ENTRY = re.compile(
    r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"'
)


def _unescape(text: str) -> str:
    return text.replace("\\n", "\n").replace('\\"', '"')


def _strings(language: str) -> Dict[int, Tuple[str, str]]:
    """Map each string id to its ``(msgid, msgstr)`` in one language file."""
    path = _LANGUAGE_DIR / "resource.language.{0}".format(language) / "strings.po"
    text = path.read_text(encoding="utf-8")
    return {
        int(string_id): (_unescape(msgid), _unescape(msgstr))
        for string_id, msgid, msgstr in _ENTRY.findall(text)
    }


def _shown(language: str, string_id: int) -> str:
    """The text Kodi displays: the translation, or the English source itself."""
    msgid, msgstr = _strings(language)[string_id]
    return msgstr or msgid


def test_every_languages_msgid_matches_the_english_source_byte_for_byte() -> None:
    # Break named: editing one language file's msgid without the others.
    # Confirmed on real Kodi (2026-09-22): LocalizeStrings.cpp reloads en_gb
    # after any other language and, for each id, compares the just-read
    # msgid against the msgid a translated file stored as its own reference
    # copy of the English source. A mismatch makes Kodi treat the whole
    # translation as stale and silently overwrite it with the English text
    # (logged as "POParser: id:<n> was recently re-used in the English
    # string file, which is not yet changed in the translated file") --
    # even though the msgstr translation itself is perfectly correct.
    english = {string_id: msgid for string_id, (msgid, _) in _strings("en_gb").items()}

    for language in LANGUAGES:
        assert {sid: msgid for sid, (msgid, _) in _strings(language).items()} == english


def test_every_language_defines_the_same_string_ids() -> None:
    # Break named: adding an id to one language file and forgetting another,
    # so that language's users see a raw string id.
    english = set(_strings("en_gb"))

    assert {language: set(_strings(language)) for language in LANGUAGES} == {
        language: english for language in LANGUAGES
    }


@pytest.mark.parametrize("string_id", [CONSENT_HEADING, CONSENT_BODY])
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_consent_strings_have_text_in_every_language(
    language: str, string_id: int
) -> None:
    # Break named: a language file with the id but an empty translation, which
    # Kodi renders as a blank dialog.
    assert _shown(language, string_id).strip() != ""


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_consent_body_has_no_leftover_placeholder(language: str) -> None:
    # Break named: a translation still carrying the {0} the dialog used to fill
    # with the injected line. Nothing formats the body any more, so Kodi would
    # show the braces literally.
    body = _shown(language, CONSENT_BODY)

    assert "{" not in body
    assert "}" not in body


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_consent_body_points_to_the_readme_section_with_the_details(
    language: str,
) -> None:
    # Break named: a translation dropping the pointer, leaving the dialog with
    # no way for the user to learn what exactly is added to their skin.
    body = _shown(language, CONSENT_BODY)

    assert "README.md" in body
    assert README_SECTION in body


def test_the_readme_has_the_section_the_dialog_points_to() -> None:
    # Break named: renaming the README heading, which would leave the dialog
    # pointing at a section that no longer exists.
    readme = (_LANGUAGE_DIR.parents[1] / "README.md").read_text(encoding="utf-8")

    assert "\n## {0}\n".format(README_SECTION) in readme


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_consent_body_still_names_the_file_it_asks_to_modify(
    language: str,
) -> None:
    # Break named: a translation localising the filename, which no user could
    # then find in their skin.
    assert "SlideShow.xml" in _shown(language, CONSENT_BODY)
