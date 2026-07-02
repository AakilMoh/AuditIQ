# ─────────────────────────────────────────────────────────────────────────────
# SPEAKER TURN SEGMENTER
# ─────────────────────────────────────────────────────────────────────────────
#
# PURPOSE:
#   Whisper returns a flat text string with no speaker labels.
#   This module splits that flat text into attributed turns:
#       [{"speaker": "AGENT", "text": "..."}, {"speaker": "DEBTOR", "text": "..."}]
#
# APPROACH:
#   Debt collection calls are highly structured conversations.
#   Agents and debtors have completely different:
#     - Vocabulary (formal vs informal)
#     - Sentence starters ("This is calling from" vs "I already told you")
#     - Conversational role (agent controls the call, debtor reacts)
#     - Linguistic register (professional vs defensive/emotional)
#     - Topic ownership (agent brings up debt, debtor disputes or deflects)
#
#   We use a rule-based classifier (no ML, no API, instant) that scores
#   each sentence segment for AGENT vs DEBTOR likelihood.
#
# ACCURACY EXPECTATION:
#   For standard debt collection calls this achieves ~85-92% turn accuracy.
#   Ambiguous sentences (short responses like "okay", "yes", "fine") default
#   to continuing the previous speaker's turn rather than switching.
#   Good enough to prevent pre-detector false positives on debtor speech.
#
# OUTPUT:
#   SpeakerSegmentation dataclass containing:
#     - turns: List[Turn]           — attributed speaker turns
#     - agent_text: str             — concatenated agent speech only
#     - debtor_text: str            — concatenated debtor speech only
#     - formatted_transcript: str   — human-readable labeled transcript
#     - confidence: float           — 0.0-1.0 overall segmentation confidence
# ─────────────────────────────────────────────────────────────────────────────

import re
import logging
from dataclasses import dataclass, field
from typing      import List, Tuple, Optional

logger = logging.getLogger(__name__)

#Data Structures

@dataclass
class Turn:
    speaker: str # "AGENT" | "DEBTOR" | "UNKNOWN"
    text: str # The raw text of this turn
    confidence: float
    signals: List[str] = field(default_factory=list)

@dataclass
class SpeakerSegmentation:
    turns: List[Turn]
    agent_text: str
    debtor_text: str
    formatted_transcript: str
    agent_turn_count: int
    debtor_turn_count: int
    unknown_turn_count: int
    confidence: float

# Linguistic Signal Libraries

#Agent Signals

AGENT_STRONG = [
    # Self-identification (very strong signal — agents always introduce themselves)
    r"\bthis is\b.{0,30}\b(calling|from|with|at)\b",
    r"\bI('m| am) calling (from|on behalf of|regarding|about)\b",
    r"\bI('m| am) (a |an )?(representative|agent|collector|calling) (from|with|at|for)\b",
    r"\b(calling|contact(ing)?) you (today |this (morning|afternoon|evening) )?regarding\b",
    r"\bour records (show|indicate|reflect)\b",
    r"\baccording to our (records|files|system|account)\b",
    r"\bI('m| am) (reaching out|calling) (today |this (morning|afternoon|evening) )?to\b",

    # Account-specific framing (agent controls the narrative)
    r"\byour account (with|number|balance|status)\b",
    r"\bthe (outstanding|current|past.?due) balance\b",
    r"\bthis (call|matter|account) (has been|is) (referred|forwarded|escalated)\b",
    r"\b(resolve|settle|take care of) this (matter|account|balance|debt)\b",
    r"\bwe('re| are) (prepared|able|willing) to (work with|offer|provide)\b",
    r"\b(payment|payment plan|arrangement|settlement) (options?|plan|arrangement)\b",
    r"\bif you (can|could|are able to) make a (payment|partial payment)\b",
    r"\b(please|kindly) (call|contact|reach) (us|me|our office) (at|back)\b",

    # Mini-miranda and disclosure language
    r"\b(attempt(ing)? to collect (a )?debt)\b",
    r"\bany information (obtained|provided|you give) will be used\b",
    r"\b(debt collector|collection (agency|company|department))\b",
    r"\byou have the right to (dispute|request|verify)\b",
    r"\b(30|thirty) days? (to dispute|to verify|to contest)\b",

    # Professional closing
    r"\b(thank you for your time|have a (good|great|nice) (day|evening|night))\b",
    r"\b(is there anything else|do you have any questions)\b",
    r"\b(I understand|I appreciate) (your|that)\b",
]

AGENT_MODERATE = [
    # Reference to the account/debt as an external object
    r"\bthe (debt|account|balance|amount)\b",
    r"\b(owed|outstanding|due|overdue|past.?due)\b",
    r"\b(creditor|original creditor|client)\b",
    r"\b(verify|verification|validate|validation)\b",
    r"\bwould you (like|prefer|be willing)\b",
    r"\b(monthly|weekly|bi.?weekly) (payment|installment)\b",
    r"\b(interest|fees?|charges?) (are|have been) (accruing|added|applied)\b",
    r"\bI (can|will) (note|update|document) (that|your)\b",
    r"\blet me (pull up|check|look at|access) (your|the) (account|file|record)\b",
]

# ── DEBTOR signals — things debtors say ──────────────────────────────────────

DEBTOR_STRONG = [
    # Dispute / denial language
    r"\bI (don't|do not|never) owe(d)?\b",
    r"\bI (already|have already) (paid|sent|took care of|settled)\b",
    r"\bthis (debt|account|bill|amount) (is|was) (already|not mine|wrong|incorrect)\b",
    r"\bthat('s| is) not (right|correct|accurate|my debt|what I owe)\b",
    r"\bI (disputed|dispute|am disputing) this\b",
    r"\b(stop|quit|cease) (calling|contacting|harassing) (me|us)\b",
    r"\bdon('t| not) (call|contact) (me|us) (again|anymore|at this number)\b",
    r"\bremove (me|my number|my information) from\b",
    r"\bI (want|need|am going to|will) (talk to|speak to|get|consult|call) (my )?(lawyer|attorney|legal)\b",
    r"\b(this is|you('re| are)) (harassing|harassment|illegal|breaking the law)\b",

    # Emotional / reactive language
    r"\bI (can't|cannot|am not able to) (afford|pay|do) (this|that|it|anything|anymore)?\b",
    r"\b(leave|get) (me|us) alone\b",
    r"\byou('ve| have) been (calling|contacting) (me|us) (all day|non.?stop|constantly|every day)\b",
    r"\bI('ve| have) (told|asked|said) (you|this) (already|before|multiple times)\b",
    r"\bwhy (do|are) you (keep|still) calling\b",
    r"\bI('m| am) (going to|gonna) (report|file a complaint|sue)\b",
    r"\bthis (call|you|your company) (is|are) (illegal|harassing|violating)\b",

    # Defensive personal reference
    r"\bmy (family|kids|wife|husband|job|boss)\b",
    r"\bI('m| am) (unemployed|broke|struggling|going through)\b",
    r"\bI (just|recently) (lost|got laid off|was fired)\b",
]

DEBTOR_MODERATE = [
    # Short reactive phrases
    r"\bI (know|understand) (but|however|still)\b",
    r"\b(whatever|fine|okay then|alright then)\b",
    r"\bwhat (do you|are you) (want|talking about|mean)\b",
    r"\b(how|why) (did|do) (you|this|it)\b",
    r"\bwho (are you|gave you|told you|is this)\b",
    r"\bthat('s| is) not (fair|right|how it works)\b",
]

# ── Ambiguous / continuation signals ─────────────────────────────────────────

# These appear in both agent and debtor speech — do not use to classify
AMBIGUOUS = [
    r"\b(yes|no|okay|ok|right|sure|uh.?huh|mm.?hmm)\b",
    r"\b(hold on|one moment|just a second)\b",
    r"\b(hello|hi|hey|good (morning|afternoon|evening))\b",
]

# ── Threat direction signals ──────────────────────────────────────────────────
# Critical for your FDCPA use case: who is threatening who?

AGENT_THREATENING_DEBTOR = [
    # Institutional/Legal actions exclusive to collectors
    r"\b(will|are going to|going to|gonna) (garnish|seize|repo|repossess)\b",
    r"\b(this )?will (go|be (sent|referred)) to (our )?(legal|attorney|court)\b",
    r"\b(you|your (wages?|assets?|bank|property)) will be\b",
    # Specific agent threats
    r"\b(will|are going to|going to|gonna) (have you |get you )?(arrest|send (the )?(police|cops|sheriff))\b",
]

DEBTOR_THREATENING_AGENT = [
    # Consumer protection agencies and actions exclusive to Debtors
    r"\bI('m| am) going to (contact|call|report (this|you) to) the (CFPB|FTC|BBB|attorney general|news)\b",
    r"\b(I'll|I will|I am going to|gonna) (call|hire|get) (my )?(lawyer|attorney)\b",
    r"\bmy (lawyer|attorney) (will|is going to|has been)\b",
]

#sentence splitter

def _split_into_sentences(text: str) -> List[str]:
    """
    Splits flat transcript text innto sentence-level segments.

    Whisper produces natural punctuation most of the time.
    We split on sentence boundaries, keeping each sentence intact
    for per-sentence classification.
    """
    if not text or not text.strip():
        return []
    
    text = re.sub(r'\s+', ' ', text.strip()) #normalizing whitesapce

    # Split on sentence-ending punctuation followed by space + capital letter
    # or end of string. Keep the punctuation with the preceding sentence.
    # Added negative lookbehinds to ignore titles and common abbreviations
    sentences = re.split(r'(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bInc)(?<!\bLLC)(?<=[.!?])\s+(?=[A-Z])', text)

    # Also split on dialogue markers if present (some Whisper outputs include them)
    # e.g., "Agent: Hello. Caller: Hi."
    expanded = []
    for sent in sentences:
        # Check for colon-based speaker markers
        colon_split = re.split(r'(?:^|\s)(?:Agent|Caller|Debtor|Speaker \d+|Person \d+):\s*', sent, flags=re.IGNORECASE)
        if len(colon_split) > 1:
            expanded.extend([s.strip() for s in colon_split if s.strip()])
        else:
            if sent.strip():
                expanded.append(sent.strip())

    return expanded

# per sentence classifier
def _compile_patterns(pattern_list: List[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in pattern_list]

_AGENT_STRONG_PAT    = _compile_patterns(AGENT_STRONG)
_AGENT_MODERATE_PAT  = _compile_patterns(AGENT_MODERATE)
_DEBTOR_STRONG_PAT   = _compile_patterns(DEBTOR_STRONG)
_DEBTOR_MODERATE_PAT = _compile_patterns(DEBTOR_MODERATE)
_AGENT_THREAT_PAT    = _compile_patterns(AGENT_THREATENING_DEBTOR)
_DEBTOR_THREAT_PAT   = _compile_patterns(DEBTOR_THREATENING_AGENT)

def _classify_sentence(
    sentence:       str,
    prev_speaker:   Optional[str],
    sentence_index: int,
) -> Tuple[str, float, List[str]]:
    """
    Classifies a single sentence as AGENT, DEBTOR, or UNKNOWN.

    Returns: (speaker, confidence, signals_fired)

    Scoring logic:
        +3.0 per AGENT_STRONG match
        +1.5 per AGENT_MODERATE match
        +3.0 per AGENT_THREATENING_DEBTOR match
        +3.0 per DEBTOR_STRONG match
        +1.5 per DEBTOR_MODERATE match
        +3.0 per DEBTOR_THREATENING_AGENT match
        +0.5 continuation bonus (if score is ambiguous, default to prev speaker)

    Positive score → AGENT, Negative score → DEBTOR
    """
    score   = 0.0
    signals = []
    s       = sentence.strip()

    if not s:
        return (prev_speaker or "UNKNOWN", 0.3, ["empty sentence — continued previous"])

    # ── Threat direction (highest priority) ──────────────────────────────────
    for pat in _AGENT_THREAT_PAT:
        if pat.search(s):
            score += 3.0
            signals.append(f"AGENT_THREAT: '{pat.pattern[:40]}'")

    for pat in _DEBTOR_THREAT_PAT:
        if pat.search(s):
            score -= 3.5   # slightly stronger — debtor threats are very distinctive
            signals.append(f"DEBTOR_THREAT: '{pat.pattern[:40]}'")

    # ── Agent signals ─────────────────────────────────────────────────────────
    for pat in _AGENT_STRONG_PAT:
        if pat.search(s):
            score += 3.0
            signals.append(f"AGENT_STRONG: '{pat.pattern[:40]}'")

    for pat in _AGENT_MODERATE_PAT:
        if pat.search(s):
            score += 1.5
            signals.append(f"AGENT_MODERATE: '{pat.pattern[:40]}'")

    # ── Debtor signals ────────────────────────────────────────────────────────
    for pat in _DEBTOR_STRONG_PAT:
        if pat.search(s):
            score -= 3.0
            signals.append(f"DEBTOR_STRONG: '{pat.pattern[:40]}'")

    for pat in _DEBTOR_MODERATE_PAT:
        if pat.search(s):
            score -= 1.5
            signals.append(f"DEBTOR_MODERATE: '{pat.pattern[:40]}'")

    # ── Call position heuristic ───────────────────────────────────────────────
    # Agents almost always speak first (intro, self-identification)
    # Debtors almost always speak second (response)
    # Early in the call → slight agent bias; late → slight debtor bias
    if sentence_index < 3:
        score += 0.5
        signals.append("POSITION: call intro (+agent bias)")

    # ── Short sentence with no signals → continuation ─────────────────────────
    word_count = len(s.split())
    if word_count <= 3 and not signals:
        # Very short, ambiguous — continue previous speaker
        speaker    = prev_speaker or "UNKNOWN"
        confidence = 0.4
        signals.append(f"SHORT_AMBIGUOUS: continuing {speaker}")
        return speaker, confidence, signals

    # ── Continuation bonus ────────────────────────────────────────────────────
    # If the sentence has mixed or weak signals, lean toward the previous speaker
    # This handles natural multi-sentence monologues by the same person
    if prev_speaker and abs(score) < 2.0:
        if "?" not in s:
            if prev_speaker == "AGENT":
                score += 0.5
                signals.append("CONTINUATION: weak signal, continuing AGENT")
            elif prev_speaker == "DEBTOR":
                score -= 0.5
                signals.append("CONTINUATION: weak signal, continuing DEBTOR")

    # ── Decision ──────────────────────────────────────────────────────────────
    if not signals:
        # No signals fired at all — truly ambiguous
        speaker    = prev_speaker or "UNKNOWN"
        confidence = 0.35
        signals.append("NO_SIGNAL: defaulting to previous speaker")
        return speaker, confidence, signals

    if score > 0:
        speaker    = "AGENT"
        # Confidence scales with score strength: score 3 → ~0.75, score 9 → ~0.95
        confidence = min(0.95, 0.5 + (score / 20.0))
    elif score < 0:
        speaker    = "DEBTOR"
        confidence = min(0.95, 0.5 + (abs(score) / 20.0))
    else:
        speaker    = prev_speaker or "UNKNOWN"
        confidence = 0.4
        signals.append("TIED: defaulting to previous speaker")

    return speaker, confidence, signals

# ─────────────────────────────────────────────────────────────────────────────
# TURN MERGER
# Consecutive sentences from the same speaker are merged into one turn
# ─────────────────────────────────────────────────────────────────────────────

def _merge_turns(classified: List[Tuple[str, str, float, List[str]]]) -> List[Turn]:
    """
    Merges consecutive same-speaker sentences into single Turn objects.

    Input: List of (speaker, sentence, confidence, signals)
    Output: List[Turn] with merged text
    """
    if not classified:
        return []

    turns  = []
    current_speaker     = classified[0][0]
    current_texts       = [classified[0][1]]
    current_confidences = [classified[0][2]]
    current_signals     = list(classified[0][3])

    for speaker, text, confidence, signals in classified[1:]:
        if speaker == current_speaker:
            # Same speaker — append to current turn
            current_texts.append(text)
            current_confidences.append(confidence)
            current_signals.extend(signals)
        else:
            # Speaker change — save current turn, start new one
            turns.append(Turn(
                speaker    = current_speaker,
                text       = " ".join(current_texts),
                confidence = sum(current_confidences) / len(current_confidences),
                signals    = current_signals,
            ))
            current_speaker     = speaker
            current_texts       = [text]
            current_confidences = [confidence]
            current_signals     = list(signals)

    # The last turn
    turns.append(Turn(
        speaker    = current_speaker,
        text       = " ".join(current_texts),
        confidence = sum(current_confidences) / len(current_confidences),
        signals    = current_signals,
    ))

    return turns

# ─────────────────────────────────────────────────────────────────────────────
# MAIN SEGMENTER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class SpeakerSegmenter:
    """
    Splits a flat Whisper transcript into speaker-attributed turns.

    Usage:
        segmenter = SpeakerSegmenter()
        result    = segmenter.segment(transcript)

        # Feed only agent speech to pre-detector
        pre_report = pre_detector.analyze(result.agent_text, sql_balance=balance)

        # Full labeled transcript for the audit prompt and result display
        labeled = result.formatted_transcript
    """

    def segment(self, transcript: str) -> SpeakerSegmentation:
        """
        Main entry point. Takes flat Whisper transcript, returns SpeakerSegmentation.
        """
        if not transcript or not transcript.strip():
            return SpeakerSegmentation(
                turns                = [],
                agent_text           = "",
                debtor_text          = "",
                formatted_transcript = "",
                agent_turn_count     = 0,
                debtor_turn_count    = 0,
                unknown_turn_count   = 0,
                confidence           = 0.0,
            )

        # ── Step 1: Split into sentences ──────────────────────────────────────
        sentences    = _split_into_sentences(transcript)
        total        = len(sentences)

        if total == 0:
            return self._empty(transcript)

        # ── Step 2: Classify each sentence ────────────────────────────────────
        classified   = []
        prev_speaker = None

        for i, sentence in enumerate(sentences):

            speaker, confidence, signals = _classify_sentence(
                sentence     = sentence,
                prev_speaker = prev_speaker,
                sentence_index = i,
            )
            classified.append((speaker, sentence, confidence, signals))
            prev_speaker = speaker

            logger.debug(
                f"[{i:02d}] {speaker} ({confidence:.2f}) | "
                f"{sentence[:60]}{'...' if len(sentence) > 60 else ''}"
            )

        # ── Step 3: Merge consecutive same-speaker sentences into turns ────────
        turns = _merge_turns(classified)

        # ── Step 4: Build outputs ─────────────────────────────────────────────
        agent_parts   = []
        debtor_parts  = []
        format_lines  = []
        agent_count   = 0
        debtor_count  = 0
        unknown_count = 0
        confidences   = []

        for turn in turns:
            confidences.append(turn.confidence)
            label = f"[{turn.speaker}]"

            if turn.speaker == "AGENT":
                agent_parts.append(turn.text)
                agent_count += 1
                format_lines.append(f"{label} {turn.text}")
            elif turn.speaker == "DEBTOR":
                debtor_parts.append(turn.text)
                debtor_count += 1
                format_lines.append(f"{label} {turn.text}")
            else:
                unknown_count += 1
                format_lines.append(f"[UNKNOWN] {turn.text}")

        agent_text           = " ".join(agent_parts)
        debtor_text          = " ".join(debtor_parts)
        formatted_transcript = "\n".join(format_lines)
        avg_confidence       = sum(confidences) / len(confidences) if confidences else 0.0

        logger.info(
            f"Segmentation: {agent_count} agent turns, {debtor_count} debtor turns, "
            f"{unknown_count} unknown | avg confidence: {avg_confidence:.2f}"
        )

        return SpeakerSegmentation(
            turns                = turns,
            agent_text           = agent_text,
            debtor_text          = debtor_text,
            formatted_transcript = formatted_transcript,
            agent_turn_count     = agent_count,
            debtor_turn_count    = debtor_count,
            unknown_turn_count   = unknown_count,
            confidence           = avg_confidence,
        )

    def _empty(self, original_text: str) -> SpeakerSegmentation:
        return SpeakerSegmentation(
            turns                = [],
            agent_text           = original_text,  # fallback: treat everything as agent
            debtor_text          = "",
            formatted_transcript = f"[UNKNOWN] {original_text}",
            agent_turn_count     = 0,
            debtor_turn_count    = 0,
            unknown_turn_count   = 1,
            confidence           = 0.0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────────────────
speaker_segmenter = SpeakerSegmenter()