"""Translate fake values in AI output back to the originals using a
mapping produced by a redaction run."""

import re


def deredact_text(text: str, mapping: dict) -> str:
    return deredact_with_count(text, mapping)[0]


def deredact_with_count(text: str, mapping: dict) -> tuple[str, int]:
    """Returns the restored text and how many values were swapped, so the UI
    can tell the user when a key file simply doesn't match their text."""
    fake_to_real: dict[str, str] = {}
    for columns in mapping.values():
        if not isinstance(columns, dict):
            continue
        for pairs in columns.values():
            if not isinstance(pairs, dict):
                continue
            for real, fake in pairs.items():
                if isinstance(real, str) and isinstance(fake, str) and fake:
                    fake_to_real[fake] = real
    if not fake_to_real:
        return text, 0
    # Longest fakes first so "Maria Lopez" wins over "Maria". Each fake is
    # fenced by word boundaries where its own edges are word characters, so
    # a fake of "3" cannot rewrite the 3 inside "350" and a fake that
    # happens to be a word like "is" only matches that whole word.
    parts = []
    for fake in sorted(fake_to_real, key=len, reverse=True):
        body = re.escape(fake)
        prefix = r"(?<!\w)" if fake[:1].isalnum() or fake[:1] == "_" else ""
        suffix = r"(?!\w)" if fake[-1:].isalnum() or fake[-1:] == "_" else ""
        parts.append(prefix + body + suffix)
    return re.compile("|".join(parts)).subn(
        lambda m: fake_to_real[m.group(0)], text
    )
