"""English text processing for ASS subtitles.

Implements automatic line breaking and line merging for English subtitles based on
grammatical cues, syntactic Part-of-Speech tagging, and length constraints.
"""

import re

# Globals for lazy-loaded NLTK
_NLTK_INITIALIZED = False
_NLTK_AVAILABLE = False
_nltk_module = None


def ensure_nltk() -> bool:
    """Lazily import and initialize NLTK on first use."""
    global _NLTK_INITIALIZED, _NLTK_AVAILABLE, _nltk_module
    if _NLTK_INITIALIZED:
        return _NLTK_AVAILABLE

    try:
        import nltk as imported_nltk

        _nltk_module = imported_nltk

        try:
            _nltk_module.data.find("taggers/averaged_perceptron_tagger_eng")
            _nltk_module.data.find("tokenizers/punkt_tab")
        except LookupError:
            # Download silently to keep CLI output clean
            _nltk_module.download("averaged_perceptron_tagger_eng", quiet=True)
            _nltk_module.download("punkt_tab", quiet=True)
        _NLTK_AVAILABLE = True
    except Exception:
        _NLTK_AVAILABLE = False

    _NLTK_INITIALIZED = True
    return _NLTK_AVAILABLE


# fmt: off
# Grammatically correct words that are excellent points for a line break.
SPLIT_WORDS = [
    # Coordinating conjunctions
    "and", "but", "or", "nor", "for", "yet",
    # Subordinating conjunctions / Relatives
    "that", "which", "who", "whom", "whose", "because", "since", "although", "though", "while",
    # Prepositions (medium to long prepositions)
    "with", "about", "against", "between", "through", "during", "before", "after", "under", "over", 
    "from", "into", "towards", "upon", "within", "without", "around",
    # Infinitive/Directional
    "to",
    # Adverbs starting clauses / Comparatives
    "when", "where", "why", "how", "if", "unless", "until", "just", "than", "what", "whenever", "wherever",
    "more", "less",
    # Auxiliary / Modal / Linking verbs (clause transition points)
    "is", "are", "was", "were", "am", "be", "been", "has", "have", "had", "do", "does", "did",
    "can", "could", "will", "would", "should", "shall", "must", "may", "might",
    # Negations & Contractions
    "doesn't", "don't", "can't", "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't",
    "won't", "wouldn't", "shouldn't", "mustn't",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    # Possessives / Determiners
    "my", "your", "his", "her", "its", "our", "their"
]

SUBJECT_PRONOUNS = {"i", "you", "he", "she", "it", "we", "they"}
OBJECT_PRONOUNS = {"me", "him", "her", "us", "them", "you", "it"}
PREPOSITIONS = {
    "with", "about", "against", "between", "through", "during", "before", "after", "under", "over", 
    "from", "into", "towards", "upon", "within", "without", "around", "in", "on", "at", "of", "by", "to"
}
ARTICLES = {"a", "an", "the"}

# Fallback verbs list in case NLTK package isn't installed
FALLBACK_VERBS = {
    "is", "are", "was", "were", "am", "be", "been", "has", "have", "had", "do", "does", "did",
    "can", "could", "will", "would", "should", "shall", "must", "may", "might",
    "doesnt", "dont", "cant", "isnt", "arent", "wasnt", "weren't", "hasnt", "havent",
    "won't", "wouldn't", "shouldn't", "mustn't", "go", "went", "gone", "make", "makes", 
    "made", "like", "likes", "liked", "want", "wants", "wanted", "think", "thinks", 
    "thought", "say", "says", "said", "report", "reports", "reported", "convey", 
    "conveys", "conveyed", "help", "helps", "helped", "done",
    "appear", "appears", "appeared", "destroy", "destroys", "destroyed", "spark", "sparks", "sparked",
    "planning", "plan", "plans", "planned", "seem", "seems", "seemed", "try", "tries", "tried", "trying",
    "mean", "means", "meant", "feel", "feels", "felt", "rising", "rise", "rises", "rose", "risen"
}
# fmt: on


def get_word_tags(text: str) -> dict:
    """Tokenize and tag text with NLTK POS tags."""
    if not ensure_nltk():
        return {}
    try:
        tokens = _nltk_module.word_tokenize(text)
        return {word.lower(): tag for word, tag in _nltk_module.pos_tag(tokens)}
    except Exception:
        return {}


def is_verb(word: str, word_tags: dict) -> bool:
    """Detect if a word is acting as a verb, using NLTK POS tags or fallback suffix patterns."""
    w = word.lower().strip(".,!?\"'")
    if word_tags and w in word_tags:
        tag = word_tags[w]
        # VB* represent verb classes, MD represents modals
        return tag.startswith("VB") or tag == "MD"

    # Fallback to offline rule-based heuristic
    if w.endswith(("ed", "ing")):
        return True
    return w in FALLBACK_VERBS


def has_typesetting(text: str) -> bool:
    """Check if the text contains ASS typesetting commands (other than basic italics/bold/underline)."""
    if "{" not in text:
        return False
    # Extract tags inside curly braces
    tags = re.findall(r"\{([^}]+)\}", text)
    if not tags:
        return False
    for tag in tags:
        # Match only safe formatting commands: \i, \b, \u with optional 0 or 1 and trailing whitespace
        if not re.match(r"^(\\[ibu][01]?\s*)*$", tag, re.IGNORECASE):
            return True
    return False


def is_inside_braces(text: str, pos: int) -> bool:
    """Check if the split index position falls inside ASS curly braces { ... }."""
    last_open = text.rfind("{", 0, pos)
    if last_open == -1:
        return False
    last_close = text.rfind("}", 0, pos)
    return last_open > last_close


class EnglishProcessor:
    """Processes English text to merge continuation lines and add hard line breaks."""

    @staticmethod
    def merge_continuation_lines(events, max_chars: int = 40) -> list:
        """Merge consecutive subtitle events if the first is short and the second is a lowercase continuation.

        Args:
            events: List of SSAEvent objects
            max_chars: Maximum character length threshold for single-line text (default: 40)

        Returns:
            List of merged SSAEvent objects
        """
        if not events:
            return events

        merged_events = []
        i = 0
        n = len(events)
        while i < n:
            curr_ev = events[i]
            if i == n - 1:
                merged_events.append(curr_ev)
                i += 1
                continue

            next_ev = events[i + 1]

            # Time gap in milliseconds
            gap = next_ev.start - curr_ev.end

            curr_text = curr_ev.text.strip()
            next_text = next_ev.text.strip()

            # Find first alphabetic character of next text
            first_alpha = re.search(r"[a-zA-Z]", next_text)
            is_lowercase_continuation = first_alpha and first_alpha.group(0).islower()

            curr_clean = curr_text.replace("\\N", " ").strip()
            next_clean = next_text.replace("\\N", " ").strip()
            merged_len = len(f"{curr_clean} {next_clean}")

            # Merge if gap is small (<= 200ms), current is short (<= 30 chars), and next is lowercase continuation
            has_symbols = any(
                sym in curr_text or sym in next_text
                for sym in ("...", "…", "♪", "♫", "(", ")", "[", "]", '"', "“", "”")
            )

            if (
                0 <= gap <= 200
                and len(curr_text) <= 30
                and is_lowercase_continuation
                and not has_symbols
                and merged_len <= 2 * max_chars
            ):
                curr_ev.text = f"{curr_clean} {next_clean}"
                curr_ev.end = next_ev.end

                # Update next event position to act as the merged event for the next check
                events[i + 1] = curr_ev
                i += 1
            else:
                merged_events.append(curr_ev)
                i += 1

        return merged_events

    @staticmethod
    def process_english_subtitle(text: str, max_chars: int = 40) -> str:
        """Add a hard line break (\\N) to English text if it exceeds max_chars.

        Ensures the split happens before grammatically correct words or after
        sentence-level punctuation (periods, commas) if possible, and structures the
        text in a triangle/reverse-pyramid while avoiding very short lines.

        Args:
            text: Original English subtitle text
            max_chars: Maximum character length threshold for single-line text (default: 40)

        Returns:
            Processed text with hard line breaks added
        """
        # Skip if already contains a line break, is short enough, or contains typesetting commands
        if "\\N" in text or len(text) <= max_chars or has_typesetting(text):
            return text

        # Get grammatical POS tags for this specific line context
        word_tags = get_word_tags(text)

        candidates = []

        # 1. Sentence and clause boundaries (split after . ! ? or ,)
        for m in re.finditer(r"(?<=[.!?,])\s+", text):
            candidates.append((m.start(), True, False, ""))

        # 2. Grammatical split words (split before the word)
        words_regex = "|".join(rf"\b{re.escape(w)}\b" for w in SPLIT_WORDS)
        for m in re.finditer(words_regex, text, re.IGNORECASE):
            candidates.append((m.start(), False, True, m.group(0).lower()))

        # 3. Fallback spaces (any space is a potential split position)
        for m in re.finditer(r"\s+", text):
            candidates.append((m.start(), False, False, ""))

        # Remove duplicate split indices by combining metadata flags
        unique_candidates = {}
        for idx, is_boundary, is_grammatical, word in candidates:
            if idx not in unique_candidates:
                unique_candidates[idx] = (is_boundary, is_grammatical, word)
            else:
                b, g, w = unique_candidates[idx]
                unique_candidates[idx] = (
                    b or is_boundary,
                    g or is_grammatical,
                    w or word,
                )

        best_parts = None
        best_score = float("inf")

        for split_pos, (is_boundary, is_grammatical, word) in unique_candidates.items():
            # Skip candidate splits that fall inside curly brace tag blocks
            if is_inside_braces(text, split_pos):
                continue

            part1 = text[:split_pos].rstrip()
            part2 = text[split_pos:].lstrip()

            if not part1 or not part2:
                continue

            words1 = part1.split()
            words2 = part2.split()

            # Heavy penalty if either side contains only 1 word (e.g. "Just\N...")
            single_word_penalty = 0
            if len(words1) <= 1 or len(words2) <= 1:
                single_word_penalty = 150

            # Forfeit mid-sentence line break if a period/sentence-ending punctuation (. ! ?)
            # occurs within 1-3 words in part2, preferring to split at that period instead.
            short_to_period_penalty = 0
            if not is_boundary:
                # Find words in part2 up to the first sentence boundary (. ! ?)
                m_end = re.search(r"[.!?]", part2)
                if m_end:
                    text_before_end = part2[: m_end.end()]
                    words_before_end = text_before_end.split()
                    if 1 <= len(words_before_end) <= 3:
                        short_to_period_penalty = 100

            len1, len2 = len(part1), len(part2)

            # Penalty for lines that are extremely short (less than 12 characters)
            short_line_penalty = 0
            if len1 < 12 or len2 < 12:
                short_line_penalty = 30

            # Syntax penalties using POS context
            syntax_penalty = 0
            if words1 and words2:
                last_w1 = words1[-1].lower().strip(".,!?\"'")
                first_w2 = words2[0].lower().strip(".,!?\"'")

                # 1. Pronoun object penalty: avoid splitting between a verb and its object pronoun (e.g. "convinced\Nyou")
                if word in OBJECT_PRONOUNS and is_verb(last_w1, word_tags):
                    syntax_penalty += 40

                # 2. Subject-verb penalty: avoid splitting between subject pronoun and its main verb (e.g. "he\Nwas")
                if last_w1 in SUBJECT_PRONOUNS and is_verb(first_w2, word_tags):
                    syntax_penalty += 35

                # 3. Compound prepositions: avoid splitting e.g. "out\Nof", "because\Nof", "due\Nto", "far\Nfrom"
                if last_w1 in (
                    "out",
                    "because",
                    "instead",
                    "according",
                    "due",
                    "close",
                    "far",
                ) and first_w2 in ("of", "to", "from"):
                    syntax_penalty += 40

                # 4. Infinitive splits: avoid splitting before a verb if preceding word is "to" (e.g. "to\Nreport")
                if last_w1 == "to" and is_verb(first_w2, word_tags):
                    syntax_penalty += 30

                # 5. Verb-to-infinitive penalty: avoid splitting between a verb and infinitive 'to' (e.g. "planning\Nto")
                if first_w2 == "to" and is_verb(last_w1, word_tags):
                    syntax_penalty += 30

                # 6. Verb-to-preposition penalty: avoid splitting between a verb/participle and its preposition (e.g. "rising\Nfrom")
                if first_w2 in PREPOSITIONS and is_verb(last_w1, word_tags):
                    syntax_penalty += 25

                # 7. Article/Determiner split penalty: avoid splitting after an article (e.g. "a\Nwarmth")
                if last_w1 in ARTICLES:
                    syntax_penalty += 30

                # 8. Pre-article split penalty: avoid starting the bottom line with an article (e.g. "\Na warmth")
                if first_w2 in ARTICLES:
                    syntax_penalty += 5

                # 9. Adjective-Noun split penalty: avoid splitting between an adjective and a noun (e.g. "proper\Ntaste")
                if (
                    word_tags
                    and last_w1 in word_tags
                    and first_w2 in word_tags
                    and word_tags[last_w1].startswith("JJ")
                    and word_tags[first_w2].startswith("NN")
                ):
                    syntax_penalty += 30

                # 10. Modifier/Cognate penalty: avoid splitting 'royal {noun}' (e.g. "royal\Nship", "royal\Npalace")
                if last_w1 == "royal":
                    syntax_penalty += 45

            # Triangle shape: penalize if top line is longer than bottom line (reverse pyramid)
            shape_penalty = 0 if len1 < len2 else 10

            # Preference/Bonuses
            # Ignore boundary bonus for vocatives or end-of-sentence tags (e.g. "don't you?") to prevent unbalanced tails
            boundary_bonus = (
                -50 if (is_boundary and 12 <= split_pos <= len(text) - 15) else 0
            )
            grammar_bonus = -15 if is_grammatical else 0

            # Non-grammatical fallback spaces get a mild penalty
            fallback_penalty = 15 if (not is_boundary and not is_grammatical) else 0

            # Calculate final heuristic score (lower is better)
            score = (
                abs(len2 - len1)
                + shape_penalty
                + single_word_penalty
                + short_line_penalty
                + syntax_penalty
                + short_to_period_penalty
                + boundary_bonus
                + grammar_bonus
                + fallback_penalty
            )

            if score < best_score:
                best_score = score
                best_parts = (part1, part2)

        if best_parts:
            return f"{best_parts[0]}\\N{best_parts[1]}"

        return text
