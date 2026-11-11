"""Safety, refusal, and validation guards for TradeZen Coach."""
import re
import unicodedata
from typing import List, Set
from .config import cfg

# Distress patterns: hopelessness or self-harm keywords
DISTRESS_PATTERNS = [
    r"\b(suicid|kill myself|want to die|end my life|end it all|can't go on|hopeless|depressed|no reason to live)\b",
    r"\b(lost everything.*die|better off dead|hurt myself)\b",
    r"\b(khatam karna chahta|jeene ka man nahi|sab barbaad ho gaya.*jaan)\b"
]

# Tip request patterns: English & Hinglish
# Explicit word boundaries so "tip" doesn't fire inside "multiple", "participate", etc.
TIP_REQUEST_PATTERNS = [
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+stocks?\b",
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+shares?\b",
    r"\b(?:which|what|any|konsa|kaunsa|kon\s+sa)\s+options?\b",
    r"\b(?:should|can)\s+i\s+(?:buy|sell|short|hold|invest)\b",
    r"\b(?:best|good|hot|top)\s+stocks?\b",
    r"\b(?:recommend|suggest)\s+(?:me\s+)?(?:a\s+)?(?:good\s+)?(?:stock|share)\b",
    r"\bstock\s+recommendations?\b",
    r"\bwill\s+(?:nifty|sensex|[a-zA-Z]+)(?:\s+stock)?\s+(?:go\s+)?(?:up|down|fall|rise)\b",
    r"\b(?:target\s+price|price\s+target|multibagger)\b",
    r"\b(?:give\s+me\s+a\s+tip|stock\s+tips?|trading\s+tips?|free\s+tips?|calls?)\b",
    r"\b(?:kaunsa|kon sa|kaun sa|kya|konsa)\s+(?:stock|share)\b",
    r"\bkya\s+lena\s+chahiye\b",
    r"\bkab\s+(?:bechna|kharidna)\b",
    r"\b(?:buy|sell)\s+call\b",
    r"\b(?:kya\s+nifty|kal\s+market)\s+(?:upar|badhega|ghatega|niche)\b",
    r"\b(?:achha|accha)\s+stock\s+batao\b",
    r"\bintraday\s+me\s+kya\s+buy\s+kare\b",
    r"\b(?:ignore|bypass|override|disregard)\s+(?:all\s+)?(?:your\s+|previous\s+|safety\s+)?(?:rules?|instructions?|filters?|guardrails?)\b",
    r"\b(?:jailbreak|dan\s+mode|debug\s+mode|unrestricted)\b"
]

# Patterns in generated replies that suggest tips/recommendations
REPLY_TIP_PATTERNS = [
    r"\byou\s+should\s+buy\b",
    r"\byou\s+should\s+sell\b",
    r"\bi\s+recommend\s+buying\b",
    r"\bi\s+recommend\s+selling\b",
    r"\btarget\s+price\b",
    r"\bwill\s+rise\s+to\b",
    r"\bwill\s+fall\s+to\b",
    r"\bstrong\s+buy\b"
]


def clean_user_text(text: str) -> str:
    """Strip control characters, collapse whitespace, cut to CHAT_MAX_MESSAGE_CHARS."""
    if not text:
        return ""
    # Strip control chars except newline and tab
    cleaned = "".join(ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C"))
    # Collapse multiple whitespaces/tabs (keep single newlines)
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
    """True for requests for buy, sell, hold advice, stock picks, price targets or predictions.
    
    Must NOT fire on questions about the user's own data (e.g., 'my target for today is ₹500',
    'why did my trade fall', 'what are multiple orders', 'what is a target price in finance').
    """
    if not message:
        return False
    msg = message.lower().strip()

    # First check: Is this a question about own trades, performance, or educational definition?
    # Exclude user's own target / own data
    if re.search(r"\bmy\s+target\b", msg) or re.search(r"\bwhy\s+did\s+my\s+trade\b", msg):
        return False

    # Exclude definitions / educational questions
    if re.search(r"\bwhat\s+(?:is|are)\s+(?:a\s+)?(?:target\s+price|multiple\s+orders?)\b", msg):
        return False

    for pat in TIP_REQUEST_PATTERNS:
        if re.search(pat, msg):
            return True

    return False


def reply_has_tip_language(reply: str) -> bool:
    """Scans coach output for recommendations. Returns True if unwanted tip language is found."""
    if not reply:
        return False
    r = reply.lower()
    for pat in REPLY_TIP_PATTERNS:
        if re.search(pat, r):
            return True
    return False


def _normalize_num_token(token: str) -> str:
    """Normalizes number token by stripping rupee symbol, commas, and percentage."""
    t = token.replace("₹", "").replace(",", "").replace("%", "").strip()
    if not t:
        return ""
    # Convert string to float then int if whole number
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
    Allows integers 0 to 10 freely.
    """
    # Regex to capture numbers with optional minus, rupee sign, commas, decimals, percentages
    num_pattern = r"(?:-|\b)₹?-?\d+(?:,\d+)*(?:\.\d+)?%?"

    reply_raw = re.findall(num_pattern, reply)
    allowed_raw = re.findall(num_pattern, allowed_text)

    allowed_set: Set[str] = set()
    for item in allowed_raw:
        norm = _normalize_num_token(item)
        if norm:
            allowed_set.add(norm)
            # also add positive form if negative
            if norm.startswith("-"):
                allowed_set.add(norm[1:])
            else:
                allowed_set.add("-" + norm)

    unmatched = []
    for item in reply_raw:
        norm = _normalize_num_token(item)
        if not norm:
            continue

        # Allow integers 0 to 10 freely
        try:
            val = float(norm)
            if val.is_integer() and 0 <= int(val) <= 10:
                continue
        except ValueError:
            pass

        if norm not in allowed_set:
            unmatched.append(item)

    return unmatched
