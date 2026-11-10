"""
Conservative Unicode Normalization and De-spacing for Telugu PDF Extraction.
KrishiVaani — Phase 6.4.1 (Telugu Extraction Validation).

Fixes typesetting advance-width whitespace inserted before Telugu dependent vowel
signs (matras), virama, anusvara, and length marks without removing legitimate
inter-word spaces.
"""

import re
import unicodedata
from typing import Dict, List, Tuple, Any

# Telugu Unicode Combining Characters:
# \u0C01: Candrabindu (ఁ)
# \u0C02: Anusvara / Sunna (ం)
# \u0C03: Visarga (ః)
# \u0C3E-\u0C44: Vowel signs AA, I, II, U, UU, Vocalic R, Vocalic RR (ా, ి, ీ, ు, ూ, ృ, ౄ)
# \u0C46-\u0C48: Vowel signs E, EE, AI (ె, ే, ై)
# \u0C4A-\u0C4C: Vowel signs O, OO, AU (ొ, ో, ౌ)
# \u0C4D: Virama / Halant (్)
# \u0C55-\u0C56: Length marks (ౕ, ౖ)
TELUGU_COMBINING_PATTERN = re.compile(
    r"[ \t]+([\u0C01-\u0C03\u0C3E-\u0C44\u0C46-\u0C48\u0C4A-\u0C4C\u0C4D\u0C55-\u0C56])"
)

# Multiple horizontal whitespace (spaces, tabs) within a single line
HORIZONTAL_SPACE_PATTERN = re.compile(r"[ \t]{2,}")


def normalize_telugu_combining_spaces(text: str) -> str:
    """
    Conservatively remove typesetting whitespace immediately preceding Telugu
    dependent vowel signs, anusvara, and virama.

    Linguistic & Orthographic Rationale:
    In standard Telugu Unicode (and Brahmic scripts generally), a dependent vowel
    sign (matra), anusvara, or virama cannot stand alone or begin a legitimate word.
    A space preceding such a sign is always an artifact of rendering advance widths
    in the PDF print stream.

    Guarantees:
    - Never removes whitespace between valid independent Telugu words.
    - Preserves all dates, digits, punctuation, and Latin characters.
    - Preserves newlines and structural paragraph boundaries.
    """
    if not text:
        return text

    # Step 1: Unicode NFC normalization
    normalized = unicodedata.normalize("NFC", text)

    # Step 2: Remove spaces before dependent combining characters
    corrected = TELUGU_COMBINING_PATTERN.sub(r"\1", normalized)

    # Step 3: Collapse repeated horizontal whitespace (preserves newlines)
    lines = corrected.split("\n")
    cleaned_lines = [HORIZONTAL_SPACE_PATTERN.sub(" ", line).strip() for line in lines]

    return "\n".join(cleaned_lines)


def clean_telugu_text_by_page(raw_text_by_page: Dict[int, str]) -> Dict[int, str]:
    """
    Produce a corrected copy of page texts while leaving the input raw dictionary unchanged.
    """
    return {
        page_num: normalize_telugu_combining_spaces(text)
        for page_num, text in raw_text_by_page.items()
    }


def compute_levenshtein_distance(s1: str, s2: str) -> int:
    """Compute character-level Levenshtein edit distance."""
    if len(s1) < len(s2):
        return compute_levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def compute_word_levenshtein_distance(tokens1: List[str], tokens2: List[str]) -> int:
    """Compute word-level Levenshtein edit distance."""
    if len(tokens1) < len(tokens2):
        return compute_word_levenshtein_distance(tokens2, tokens1)
    if len(tokens2) == 0:
        return len(tokens1)
    previous_row = list(range(len(tokens2) + 1))
    for i, t1 in enumerate(tokens1):
        current_row = [i + 1]
        for j, t2 in enumerate(tokens2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (t1 != t2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def evaluate_telugu_accuracy(
    ground_truth_lines: List[str],
    extracted_lines: List[str],
) -> Dict[str, Any]:
    """
    Evaluate extracted Telugu lines against manually verified ground truth lines.
    Calculates exact line match rate, CER, and WER.
    """
    n = min(len(ground_truth_lines), len(extracted_lines))
    gt = [g.strip() for g in ground_truth_lines[:n]]
    ext = [e.strip() for e in extracted_lines[:n]]

    total_chars = sum(len(s) for s in gt)
    total_words = sum(len(s.split()) for s in gt)

    char_edits = sum(compute_levenshtein_distance(g, e) for g, e in zip(gt, ext))
    word_edits = sum(compute_word_levenshtein_distance(g.split(), e.split()) for g, e in zip(gt, ext))
    matched_lines = sum(1 for g, e in zip(gt, ext) if g == e)

    cer = (char_edits / total_chars * 100.0) if total_chars > 0 else 0.0
    wer = (word_edits / total_words * 100.0) if total_words > 0 else 0.0
    line_accuracy = (matched_lines / n * 100.0) if n > 0 else 0.0

    return {
        "total_lines": n,
        "matched_lines": matched_lines,
        "line_accuracy_percent": round(line_accuracy, 2),
        "total_chars": total_chars,
        "char_edits": char_edits,
        "cer_percent": round(cer, 2),
        "total_words": total_words,
        "word_edits": word_edits,
        "wer_percent": round(wer, 2),
    }

