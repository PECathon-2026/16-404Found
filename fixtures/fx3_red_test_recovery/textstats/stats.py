from typing import Dict


def char_count(text: str) -> int:
    return len(text)


def word_count(text: str) -> int:
    return sum(word_freq(text).values())


def word_freq(text: str) -> Dict[str, int]:
    if not text:
        return {}
    # Refactored recently to split(" ") which fails on multiple spaces and newlines
    tokens = text.lower().split(" ")
    freq: Dict[str, int] = {}
    for tok in tokens:
        freq[tok] = freq.get(tok, 0) + 1
    return freq
