"""Safety, refusal, and validation guards for TradeZen Coach."""
import re
import unicodedata
from typing import List, Optional, Set, Tuple
from .config import cfg

# ---------------------------------------------------------------------------
# Distress patterns: hopelessness or self-harm keywords
# ---------------------------------------------------------------------------
DISTRESS_PATTERNS = [
    r"\b(suicid|kill myself|want to die|end my life|end it all|can't go on|hopeless|depressed|no reason to live)\b",
    r"\b(lost everything.*die|better off dead|hurt myself)\b",
    r"\b(khatam karna chahta|jeene ka man nahi|sab barbaad ho gaya.*jaan)\b"
]

# ---------------------------------------------------------------------------
# INPUT gate: tip request patterns (English & Hinglish).
# Explicit word boundaries so "tip" doesn't fire inside "multiple", "participate".
# Must NOT fire on personal-data questions about the user's OWN trading.
# ---------------------------------------------------------------------------
TIP_REQUEST_PATTERNS = [
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+stocks?\b",
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+shares?\b",
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+options?\b",
    r"\b(?:should|can)\s+i\s+(?:buy|sell|short|hold|invest)\b",
    r"\b(?:best|good|hot|top)\s+stocks?\b",
    r"\b(?:recommend|suggest)\s+(?:me\s+)?(?:a\s+)?(?:good\s+)?(?:stock|share)\b",
    r"\bstock\s+recommendations?\b",
    r"\bwill\s+(?:nifty|sensex|[a-zA-Z]+)(?:\s+stock)?\s+(?:go\s+)?(?:up|down|fall|rise)\b",
    r"\b(?:give\s+me\s+a\s+tip|stock\s+tips?|trading\s+tips?|free\s+tips?|calls?)\b",
    r"\b(?:target\s+price|price\s+target|multibagger)\b",
    r"\b(?:kaunsa|kon sa|kaun sa|kya|konsa)\s+(?:stock|share)\b",
    r"\bkya\s+lena\s+chahiye\b",
    r"\b(?:kya\s+.*(?:kharidna|bechna|lena)\s+chahiye|kharidna\s+chahiye|bechna\s+chahiye|kharidu\s+kya)\b",
    r"\bkab\s+(?:bechna|kharidna)\b",
    r"\b(?:buy|sell)\s+call\b",
    r"\b(?:kya\s+)?(?:nifty|sensex|market)(?:\s+kal)?\s+(?:upar|badhega|ghatega|niche|girega)\b",
    r"\b(?:achha|accha)\s+stock\s+batao\b",
    r"\bintraday\s+me\s+kya\s+buy\s+kare\b",
    r"\b(?:ignore|bypass|override|disregard)\s+(?:all\s+)?(?:your\s+|previous\s+|safety\s+)?(?:rules?|instructions?|filters?|guardrails?)\b",
    r"\b(?:jailbreak|dan\s+mode|debug\s+mode|unrestricted)\b"
]

# ---------------------------------------------------------------------------
# OUTPUT scanner: advice-shaped language in Gemini free text.
#
# These patterns detect genuine investment advice directed at the user:
#  - Future recommendations to act on a named security
#  - Explicit predictions of future prices
#  - Claims of professional authority
#
# They deliberately do NOT cover:
#  - Past-tense descriptions of what the user did ("you bought 10 shares")
#  - User's own rule names/values in quotes ("your stop-loss", "profit target")
#  - Side labels (BUY, SELL) as transaction descriptors
#  - Any number, symbol or label that appears in the allowed_facts_text
#
# The allow-list built from facts is passed into scan_and_sanitize_gemini_reply()
# at call time so it's never hardcoded here.
# ---------------------------------------------------------------------------

# Genuine advice recommendations (future-directed, security-specific)
_ADV_RECOMMENDATION = [
    # "you should buy / sell / hold [a security]"
    r"\byou\s+should\s+(?:buy|sell|short|hold|invest|exit|enter)\b",
    # "I recommend buying / selling"
    r"\bi\s+recommend\s+(?:buying|selling|shorting|holding|exiting|entering)\b",
    # "consider buying / selling" with a security context
    r"\bconsider\s+(?:buying|selling|shorting|holding|exiting)\b",
    # "buy now", "sell now", "exit now" (action urgency)
    r"\b(?:buy|sell|exit|enter)\s+now\b",
    # Strong buy / strong sell label
    r"\bstrong\s+(?:buy|sell)\b",
]

# Predictions about future market or security prices (not user's own data)
_ADV_PREDICTION = [
    # "will rise to", "will fall to", "is going to drop"
    r"\b(?:will|is\s+going\s+to|expected\s+to)\s+(?:rise|fall|drop|surge|crash|rally|reach|hit)\b",
    # "price will" followed by anything
    r"\bprice\s+will\b",
    # "market will" followed by anything
    r"\bmarket\s+will\b",
    # "will give good returns"
    r"\bwill\s+give\s+(?:good\s+)?returns?\b",
    # "a target price of X for the stock" (stock-price-target, not user's rule)
    r"\ba\s+target\s+price\s+of\b",
    # "next target [level/price]" with market connotation
    r"\bnext\s+target\b",
]

# Hindsight advice on past security decisions
_ADV_HINDSIGHT = [
    r"\b(?:you\s+)?should\s+have\s+(?:bought|sold|shorted|held|entered|exited|booked|taken)\b",
    r"\bbetter\s+to\s+have\s+(?:bought|sold|held|exited)\b",
    r"\byou\s+could\s+have\s+(?:made|bought|sold|exited)\b",
]

# Claims of certification or regulatory authority
_ADV_AUTHORITY = [
    r"\b(?:as\s+a\s+(?:certified|licensed|registered|professional)\s+(?:financial\s+)?(?:advisor|adviser|analyst|instructor|broker))\b",
    r"\bi\s+am\s+(?:a\s+)?(?:certified|licensed|registered)\s+(?:advisor|adviser|analyst|instructor|broker)\b",
    r"\bsebi\s+registered\b",
    r"\bcfa\s+charterholder\b",
]

# Combined for quick scan
_ALL_ADV_PATTERNS: List[Tuple[str, str]] = (
    [(p, "recommendation") for p in _ADV_RECOMMENDATION]
    + [(p, "prediction") for p in _ADV_PREDICTION]
    + [(p, "hindsight") for p in _ADV_HINDSIGHT]
    + [(p, "authority") for p in _ADV_AUTHORITY]
)

# Neutral replacement sentences
_NEUTRAL_PROCESS = (
    "In practice, the focus is on reviewing your own execution and risk rules "
    "rather than past or future prices."
)
_NEUTRAL_AUTHORITY = "I am TradeZen Coach, an educational practice coach for your paper-trading data."


def clean_user_text(text: str) -> str:
    """Strip control characters, collapse whitespace, cut to CHAT_MAX_MESSAGE_CHARS."""
    if not text:
        return ""
    cleaned = "".join(ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C"))
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    cleaned = cleaned.strip()
    max_len = cfg.CHAT_MAX_MESSAGE_CHARS
    return cleaned[:max_len]


def is_distress(message: str) -> bool:
    """Detects hopelessness or self-harm language."""
    if not message:
        return False
    msg = message.lower()
    for pat in DISTRESS_PATTERNS:
        if re.search(pat, msg):
            return True
    return False


def is_tip_request(message: str) -> bool:
    """True for requests for buy/sell/hold advice, stock picks, price targets or predictions.

    Must NOT fire on questions about the user's own data (e.g. 'my target for today is ₹500',
    'why did my trade fall', 'what are multiple orders', 'what is a target price in finance').
    """
    if not message:
        return False
    msg = message.lower().strip()

    # Exclude user's own target / own data questions
    if re.search(r"\bmy\s+target\b", msg) or re.search(r"\bwhy\s+did\s+my\s+trade\b", msg):
        return False

    # Exclude definitions / educational questions
    if re.search(r"\bwhat\s+(?:is|are)\s+(?:a\s+)?(?:target\s+price|multiple\s+orders?)\b", msg):
        return False

    for pat in TIP_REQUEST_PATTERNS:
        if re.search(pat, msg):
            return True

    return False


# ---------------------------------------------------------------------------
# Sentence-level output scanner
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '!', '?' followed by space or end-of-string."""
    # Keep delimiter at end of each sentence
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _sentence_is_flagged(sentence: str, allowed_set: Set[str]) -> Optional[str]:
    """
    Returns the violation kind if this sentence contains advice-shaped language
    that is NOT covered by the runtime allow-list built from facts.

    The allow-list suppresses false positives for the user's own rule names
    and values (e.g. 'target price' appearing as a named user rule).
    """
    s_lower = sentence.lower()
    for pat, kind in _ALL_ADV_PATTERNS:
        m = re.search(pat, s_lower)
        if not m:
            continue
        matched_phrase = m.group(0).strip()
        # If the matched phrase itself appears verbatim in allowed_set, skip
        if matched_phrase in allowed_set:
            continue
        return kind
    return None


def _build_allowed_set(allowed_facts_text: str) -> Set[str]:
    """
    Build a set of lowercase word-runs from the facts text that the scanner
    should treat as safe even if they superficially match a pattern.
    Includes each individual word and each 2-gram so short phrases pass through.
    """
    if not allowed_facts_text:
        return set()
    words = re.findall(r"[a-z0-9%₹.,+\-]+", allowed_facts_text.lower())
    result: Set[str] = set(words)
    for i in range(len(words) - 1):
        result.add(f"{words[i]} {words[i+1]}")
    return result


def scan_and_sanitize_gemini_reply(
    reply: str,
    allowed_facts_text: str = "",
    is_template: bool = False,
) -> Tuple[str, List[str]]:
    """
    Scan and sanitize a Gemini-generated reply at the sentence level.

    Rules:
    - Template replies (is_template=True) are NEVER modified. They are built
      from the user's own records and are data, not advice.
    - For Gemini free text: flag only advice-shaped sentences (recommendations
      to act on a security, predictions of future prices, authority claims).
    - Replace only flagged sentences with neutral process-based text; keep all
      other sentences and all metadata.
    - Build the allow-list at runtime from allowed_facts_text; never hardcode.

    Returns (sanitized_reply, list_of_violation_kinds_found).
    """
    if not reply:
        return reply, []
    if is_template:
        return reply, []

    allowed_set = _build_allowed_set(allowed_facts_text)
    sentences = _split_sentences(reply)
    violations_found: List[str] = []
    out_parts: List[str] = []

    for sent in sentences:
        kind = _sentence_is_flagged(sent, allowed_set)
        if kind is None:
            out_parts.append(sent)
        else:
            violations_found.append(kind)
            if kind == "authority":
                out_parts.append(_NEUTRAL_AUTHORITY)
            else:
                out_parts.append(_NEUTRAL_PROCESS)

    sanitized = " ".join(out_parts)
    return sanitized, violations_found


# ---------------------------------------------------------------------------
# Legacy helpers kept for backward compatibility with existing call sites.
# They delegate to the new sentence-level scanner where appropriate.
# ---------------------------------------------------------------------------

def scan_coach_reply_violations(reply: str) -> List[str]:
    """Scans coach output for hindsight advice, predictions, and certification claims.
    Returns list of violation kind strings. Does NOT modify the reply."""
    if not reply:
        return []
    _, violations = scan_and_sanitize_gemini_reply(reply, allowed_facts_text="", is_template=False)
    return violations


def sanitize_coach_reply(reply: str, allowed_facts_text: str = "") -> str:
    """Replaces flagged sentences with neutral wording. Never replaces template replies."""
    sanitized, _ = scan_and_sanitize_gemini_reply(reply, allowed_facts_text=allowed_facts_text, is_template=False)
    return sanitized


def reply_has_tip_language(reply: str, allowed_facts_text: str = "") -> bool:
    """Returns True only if advice-shaped language was found in this Gemini reply.

    Does NOT scan template replies (use scan_and_sanitize_gemini_reply with is_template=True).
    """
    if not reply:
        return False
    _, violations = scan_and_sanitize_gemini_reply(reply, allowed_facts_text=allowed_facts_text, is_template=False)
    return len(violations) > 0


# ---------------------------------------------------------------------------
# Number verification helpers (unchanged)
# ---------------------------------------------------------------------------

def mask_date_time_tokens(text: str) -> str:
    """Masks dates, times, and years to prevent false number check rejections."""
    if not text:
        return ""
    # 1. Times: e.g. 11:10, 11:10:00, 11:10 AM, 15:15
    t = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?\b", " ", text)
    # 2. ISO/hyphen dates: e.g. 2022-03-10, 2022/03/10
    t = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", t)
    # 3. Slash/hyphen dates: e.g. 10/03/2022, 10-03-2022
    t = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", " ", t)
    # 4. Textual dates: March 10, 2022 or 10th March 2022
    t = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+\d{4}\b", " ", t, flags=re.I)
    # 5. Standalone year in 19xx/20xx
    t = re.sub(r"\b(?:19|20)\d{2}\b", " ", t)
    return t


def _normalize_num_token(token: str) -> str:
    """Normalizes number token by stripping rupee symbol, commas, and percentage."""
    t = token.replace("₹", "").replace(",", "").replace("%", "").strip()
    if not t:
        return ""
    try:
        val = float(t)
        if val.is_integer():
            return str(int(val))
        return str(round(val, 2))
    except ValueError:
        return t


def numbers_ok(reply: str, allowed_text: str) -> List[str]:
    """Extract every number from reply and return any that do NOT appear in allowed_text.

    Treats 1,800 and 1800 and ₹1,800 and -₹1,800 and 60% as equal.
    Ignores numbers inside date and time tokens.
    Allows integers 0 to 10 freely.
    """
    num_pattern = r"(?:-|\b)₹?-?\d+(?:,\d+)*(?:\.\d+)?%?"

    reply_masked = mask_date_time_tokens(reply)
    reply_raw = re.findall(num_pattern, reply_masked)
    allowed_raw = re.findall(num_pattern, allowed_text)

    allowed_set: Set[str] = set()
    for item in allowed_raw:
        norm = _normalize_num_token(item)
        if norm:
            allowed_set.add(norm)
            try:
                fv = float(norm)
                if fv.is_integer():
                    allowed_set.add(str(int(fv)))
            except ValueError:
                pass
            if norm.startswith("-"):
                allowed_set.add(norm[1:])
            else:
                allowed_set.add("-" + norm)

    unmatched = []
    for item in reply_raw:
        norm = _normalize_num_token(item)
        if not norm:
            continue
        try:
            val = float(norm)
            if val.is_integer() and 0 <= int(val) <= 10:
                continue
        except ValueError:
            pass
        if norm not in allowed_set:
            unmatched.append(item)

    return unmatched
