"""Gibberish filter for the mood field.

Conservative but catches keyboard mashing. Returns (ok, reason).
"""

import re


_VOWELS = {"a", "e", "i", "o", "u", "y"}

# Short genre/acronym inputs we don't want to reject.
_KNOWN_SHORT = {
    "dnb", "edm", "rnb", "idm", "uk", "us", "ye", "tyla",
    "lofi", "lofi", "edm", "synth", "pop",
}


def _letters(s: str) -> list[str]:
    return [c for c in s.lower() if c.isalpha()]


def _vowel_ratio(s: str) -> float:
    letters = _letters(s)
    if not letters:
        return 0.0
    return sum(1 for c in letters if c in _VOWELS) / len(letters)


def _max_consonant_run(s: str) -> int:
    longest = 0
    current = 0
    for c in s.lower():
        if c.isalpha() and c not in _VOWELS:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _word_is_gibberish(word: str) -> bool:
    """True if a single word looks like keyboard mashing."""
    letters = _letters(word)
    if len(letters) < 5:
        return False

    # Low vowel ratio is a strong signal.
    if _vowel_ratio(word) < 0.20:
        return True

    # 5+ consonants in a row is very rare in English.
    if _max_consonant_run(word) >= 5:
        return True

    # Same character 4+ times in a row.
    if re.search(r"(.)\1{3,}", word, re.IGNORECASE):
        return True

    return False


def validate_mood(mood: str) -> tuple[bool, str]:
    text = mood.strip()

    if not text:
        return False, "enter a mood"

    # Known short tokens pass unconditionally.
    if text.lower() in _KNOWN_SHORT:
        return True, ""

    # Very short inputs are fine (acronyms, single letters, etc).
    if len(text) < 4:
        return True, ""

    # Multi-word input: only reject if EVERY word looks like gibberish.
    # This catches "asdkjahs asdkljha" but lets "dnb asdf" through.
    if " " in text:
        words = [w for w in text.split() if w]
        long_words = [w for w in words if len(_letters(w)) >= 5]
        if long_words and all(_word_is_gibberish(w) for w in long_words):
            return False, "that doesn't look like a mood — try more words"
        return True, ""

    # Single word: reject if it looks like gibberish.
    if _word_is_gibberish(text):
        return False, "that doesn't look like a mood — try more words"

    return True, ""