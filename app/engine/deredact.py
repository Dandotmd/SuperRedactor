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
    # Longest fakes first so "Maria Lopez" wins over "Maria".
    pattern = re.compile(
        "|".join(re.escape(f) for f in sorted(fake_to_real, key=len, reverse=True))
    )
    return pattern.subn(lambda m: fake_to_real[m.group(0)], text)
