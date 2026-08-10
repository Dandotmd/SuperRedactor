"""Translate fake values in AI output back to the originals using a
mapping produced by a redaction run."""

import re


def deredact_text(text: str, mapping: dict) -> str:
    fake_to_real: dict[str, str] = {}
    for columns in mapping.values():
        for pairs in columns.values():
            for real, fake in pairs.items():
                fake_to_real[fake] = real
    if not fake_to_real:
        return text
    # Longest fakes first so "Maria Lopez" wins over "Maria".
    pattern = re.compile(
        "|".join(re.escape(f) for f in sorted(fake_to_real, key=len, reverse=True))
    )
    return pattern.sub(lambda m: fake_to_real[m.group(0)], text)
