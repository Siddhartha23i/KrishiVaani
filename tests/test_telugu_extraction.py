"""
Unit test suite for Telugu PDF Extraction Validation and Conservative De-spacing.
KrishiVaani — Phase 6.4.1.
"""

import unittest
from pathlib import Path
import fitz

from app.knowledge.pjtau.telugu_cleaner import (
    normalize_telugu_combining_spaces,
    clean_telugu_text_by_page,
    evaluate_telugu_accuracy,
    compute_levenshtein_distance,
    compute_word_levenshtein_distance,
)

# Ground-truth lines from official PJTAU Bulletin (2026-11-04_XXXVII_87_2026_f2742207.pdf)
GROUND_TRUTH_PAGE_1 = [
    "ప్రొఫెసర్ జయశంకర్ తెలంగాణ వ్యవసాయ విశ్వవిద్యాలయం",
    "వ్యవసాయ వాతావరణ పరిశోధన విభాగం,",
    "డిజిటల్ సాంకేతిక వ్యవసాయ కేంద్రం, రాజేంద్రనగర్, హైదరాబాద్.",
    "బులెటిన్ నెం. XXXVII/88/2026",
    "రాష్ట్ర రైతాంగానికి",
    "వాతావరణ ఆధారిత వ్యవసాయ సలహాలు",
    "తేది: 04.11.2026(బుధవారం) నుండి 08.11.2026 (ఆదివారం) వరకు",
    "గ్రామీణ కృషి మౌసమ్ సేవ పథకం (GKMS Project)",
    "భారత వాతావరణ శాఖ, న్యూఢిల్లీ.",
]

GROUND_TRUTH_PAGE_3 = [
    "వాతావరణ ఆధారిత వ్యవసాయ సలహాలు",
    "• పైన తెలిపిన జిల్లాల్లో వర్షాలు కురిసే అవకాశం ఉన్నందున, రైతులు పొలంలో నుండి మురుగు నీటిని",
    "తీసివేయడానికి కాలువలు చేసుకోవాలి మరియు పొలం నుండి మురుగు నీటిని తీసివేయాలి.",
    "• వర్షాలు కురిసే అవకాశం ఉన్నందున, యాసంగి పంట పొలాల్లో మందులను పిచికారి చేయడం, ఎరువులు",
    "వేయడం తాత్కాలికంగా వాయిదా వేయాలి మరియు తాత్కాలికంగా పంట కోతలను వాయిదా వేసుకోవాలి.",
    "• తాత్కాలికంగా కోసిన పంటను మార్కెట్ కి తరలించడం వాయిదా వేసుకోవాలి.",
    "• ఇప్పటికే మార్కెట్ కు తరలించిన దాన్యం తడవకుండా టార్పాలిన్ తో కప్పి వుంచవలెను.",
    "• వర్షాలు ఆగిన తరువాత ప్రత్తి మరియు ఇతర ధాన్యాన్ని సరైన తేమ ఉండే విధంగా ఆరబెట్టుకొని తరువాత",
    "కోసుకొని సురక్షిత ప్రాంతానికి తరలించుకోవాలి .",
    "• భారీ వర్షాలు కురిసే సూచనలున్నందున రభీ పంటలను విత్తుకోవడం తాత్కాలికంగా వాయిదా వేసుకోవాలి.",
    "• ఉరుములు మరియు మెరుపులతో కూడిన వర్ష సూచనలున్నందున రైతులు విద్యుత్ స్థంబాలు, విద్యుత్ తీగలు",
    "మరియు చెరువులు, నీటి కుంటలకు దూరంగా ఉండవలెను. అధే విధంగా రైతులు చెట్ల క్రింద నిలబడరాదు",
    "మరియు పశువులు, గొర్రెలు, మేకలను చెట్ల క్రింద ఉంచరాదు.",
    "ప్రధాన శాస్త్రవేత్త (అగ్రానమి)& అధిపతి",
]


class TestTeluguExtractionSuite(unittest.TestCase):
    """Test suite verifying conservative Telugu Unicode normalization and accuracy evaluation."""

    def test_01_vowel_sign_despacing_repairs_advance_width_artifacts(self):
        """Preceding spaces before dependent vowel signs and anusvara are safely removed."""
        cases = [
            ("క ేంద్రం", "కేంద్రం"),
            ("ర ైతులు", "రైతులు"),
            ("స ాంకేతిక", "సాంకేతిక"),
            ("న ుండి", "నుండి"),
            ("తడవక ుండా", "తడవకుండా"),
            ("కొత్తగూడ ెం", "కొత్తగూడెం"),
            ("హన్మక ొండ", "హన్మకొండ"),
            ("జనగ ాం", "జనగాం"),
            ("హ ైదరాబాద్", "హైదరాబాద్"),
            ("ప ైన", "పైన"),
        ]
        for corrupted, expected in cases:
            self.assertEqual(normalize_telugu_combining_spaces(corrupted), expected)

    def test_02_inter_word_spacing_strictly_preserved(self):
        """Spaces between distinct valid Telugu words are never collapsed or removed."""
        text = "వ్యవసాయ వాతావరణ పరిశోధన విభాగం"
        self.assertEqual(normalize_telugu_combining_spaces(text), text)

        text2 = "వర్షాలు కురిసే అవకాశం ఉన్నందున రైతులు పొలంలో"
        self.assertEqual(normalize_telugu_combining_spaces(text2), text2)

        text3 = "యాసంగి పంట పొలాల్లో ఎరువులు వేయడం"
        self.assertEqual(normalize_telugu_combining_spaces(text3), text3)

    def test_03_dates_numbers_and_latin_characters_preserved(self):
        """Dates, bulletin IDs, numbers, and Latin script terms remain 100% intact."""
        text = "తేది: 04.11.2026(బుధవారం) న ుండి 08.11.2026 (ఆదివారం) వరకు"
        expected = "తేది: 04.11.2026(బుధవారం) నుండి 08.11.2026 (ఆదివారం) వరకు"
        self.assertEqual(normalize_telugu_combining_spaces(text), expected)

        bulletin_text = "బులెటిన్ న ెం. XXXVII/88/2026"
        expected_bulletin = "బులెటిన్ నెం. XXXVII/88/2026"
        self.assertEqual(normalize_telugu_combining_spaces(bulletin_text), expected_bulletin)

        latin_text = "గ్రామీణ కృషి మౌసమ్ సేవ పథకం (GKMS Project)"
        self.assertEqual(normalize_telugu_combining_spaces(latin_text), latin_text)

        speed_text = "గంటకు 40-50 కి. మీ. వేగంతో"
        self.assertEqual(normalize_telugu_combining_spaces(speed_text), speed_text)

    def test_04_crop_names_and_agricultural_terms_preserved(self):
        """Key crops (cotton, paddy), seasons (Yasangi, Rabi), and management terms are verified."""
        advisory_raw = "• వర్షాలు ఆగిన తరువాత ప్రత్తి మరియు ఇతర ధాన్యాన్ని సర ైన తేమ ఉండే విధంగా"
        advisory_clean = normalize_telugu_combining_spaces(advisory_raw)
        self.assertIn("ప్రత్తి", advisory_clean, "Cotton crop name must be intact")
        self.assertIn("ధాన్యాన్ని", advisory_clean, "Grain/paddy crop name must be intact")
        self.assertIn("సరైన తేమ", advisory_clean, "Proper moisture term must be restored")

        rabi_raw = "• భారీ వర్షాలు కురిసే సూచనలున్నందున రభీ పంటలను విత్తుకోవడం తాత్కాలికంగా"
        rabi_clean = normalize_telugu_combining_spaces(rabi_raw)
        self.assertIn("రభీ పంటలను", rabi_clean)
        self.assertIn("విత్తుకోవడం", rabi_clean, "Sowing operation must be intact")

    def test_05_ground_truth_accuracy_improvement_quantified(self):
        """Real PJTAU Nov 4 bulletin achieves 0.00% CER and 0.00% WER after conservative normalization."""
        pdf_path = Path("data/pjtau/raw_pdfs/2026-11-04_XXXVII_87_2026_f2742207.pdf")
        if not pdf_path.exists():
            self.skipTest(f"PDF not found at {pdf_path}")

        doc = fitz.open(pdf_path)
        p1_raw_lines = [l.strip() for l in doc[0].get_text().split("\n") if l.strip()]
        p3_raw_lines = [l.strip() for l in doc[2].get_text().split("\n") if l.strip()]
        doc.close()

        all_gt = GROUND_TRUTH_PAGE_1 + GROUND_TRUTH_PAGE_3
        all_raw = p1_raw_lines[:len(GROUND_TRUTH_PAGE_1)] + p3_raw_lines[:len(GROUND_TRUTH_PAGE_3)]

        # 1. Raw extraction metrics
        raw_eval = evaluate_telugu_accuracy(all_gt, all_raw)
        self.assertEqual(raw_eval["matched_lines"], 12)
        self.assertAlmostEqual(raw_eval["cer_percent"], 1.42, delta=0.05)
        self.assertAlmostEqual(raw_eval["wer_percent"], 20.11, delta=0.05)

        # 2. Corrected extraction metrics
        cleaned_lines = [normalize_telugu_combining_spaces(l) for l in all_raw]
        clean_eval = evaluate_telugu_accuracy(all_gt, cleaned_lines)
        self.assertEqual(clean_eval["matched_lines"], 23, "All 23 lines must match ground truth exactly")
        self.assertEqual(clean_eval["cer_percent"], 0.00, "CER must drop to 0.00%")
        self.assertEqual(clean_eval["wer_percent"], 0.00, "WER must drop to 0.00%")

    def test_06_clean_telugu_text_by_page_preserves_raw_dictionary(self):
        """clean_telugu_text_by_page returns a new dict without mutating original raw inputs."""
        raw_dict = {
            1: "ర ైతులు క ేంద్రం",
            2: "న ుండి ప ైన",
        }
        cleaned_dict = clean_telugu_text_by_page(raw_dict)
        # Original remains untouched
        self.assertEqual(raw_dict[1], "ర ైతులు క ేంద్రం")
        self.assertEqual(raw_dict[2], "న ుండి ప ైన")
        # Cleaned contains corrected strings
        self.assertEqual(cleaned_dict[1], "రైతులు కేంద్రం")
        self.assertEqual(cleaned_dict[2], "నుండి పైన")


if __name__ == "__main__":
    unittest.main()

