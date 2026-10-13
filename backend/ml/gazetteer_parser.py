"""Gazetteer-driven parser for field-collection addresses.

Resolves the locality against the town's known localities, the landmark
against a multilingual landmark lexicon (English, romanised and native-script
Kannada/Hindi), and extracts the street structure (cross/main, gali/ward,
road/block).
"""

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from rapidfuzz import fuzz

LANDMARK_KEYWORDS: dict[str, list[str]] = {
    "community_hall": ["community", "mantapa", "barat", "baraat", "samudaya", "बारात", "ಮಂಟಪ", "ಸಮುದಾಯ"],
    "ration_shop": ["ration", "pds", "nyayabele", "राशन", "ನ್ಯಾಯಬೆಲೆ"],
    "ganesha_temple": ["ganesh", "ganesha", "ganapathi", "ganapati", "गणेश", "ಗಣಪತಿ", "ಗಣೇಶ"],
    "masjid": ["masjid", "mosque", "masidi", "मस्जिद", "ಮಸೀದಿ"],
    "bus_stop": ["bus", "बस", "ಬಸ್"],
    "post_office": ["post", "dak", "anche", "डाकघर", "डाक", "ಅಂಚೆ"],
    "medical_store": ["medical", "medicals", "pharmacy", "dawai", "मेडिकल", "दवाई", "ಮೆಡಿಕಲ್"],
    "church": ["church", "girja", "चर्च", "गिरजा", "ಚರ್ಚ್"],
    "govt_school": ["school", "shaale", "shale", "स्कूल", "ಶಾಲೆ"],
    "hanuman_temple": ["hanuman", "anjaneya", "हनुमान", "ಹನುಮಾನ್", "ಹನುಮಾನ", "ಆಂಜನೇಯ"],
    "milk_dairy": ["milk", "doodh", "haalina", "dairy", "दूध", "डेयरी", "ಹಾಲಿನ", "ಡೈರಿ"],
    "water_tank": ["tank", "tanki", "टंकी", "ಟ್ಯಾಂಕ್"],
    "petrol_bunk": ["petrol", "पेट्रोल", "ಪೆಟ್ರೋಲ್"],
    "park": ["park", "bagicha", "udyanavana", "पार्क", "ಉದ್ಯಾನವನ"],
}
LANDMARK_TYPES: list[str] = list(LANDMARK_KEYWORDS)
_KEYWORD_TO_TYPE = {k: t for t, ks in LANDMARK_KEYWORDS.items() for k in ks}
_FUZZY_KEYWORDS = [k for k in _KEYWORD_TO_TYPE if k.isascii() and len(k) >= 5]

_BEHIND = {"bhd", "behind", "hinde", "hindhe", "peeche", "piche", "पीछे", "ಹಿಂದೆ"}
_OPPOSITE = {"opp", "opposite", "eduru", "edhuru", "edurru", "samne", "saamne", "सामने", "ಎದುರು"}

_ABBREVIATIONS = {
    "layt": "layout", "lyt": "layout", "layou": "layout",
    "nagr": "nagar", "ngr": "nagar", "ngar": "nagar", "naagar": "nagar", "nagra": "nagar", "naagr": "nagar",
    "colny": "colony", "col": "colony",
}

_ORD = r"\b(\d{1,2})\s*(?:st|nd|rd|th)?"
_STREET_PATTERNS = {
    "cross": [rf"{_ORD}\s*(?:cross|crss|crs|cr|x)\b", r"\b(?:cross|crs|cr)\s*(?:no\.?\s*)?(\d{1,2})\b"],
    "main": [rf"{_ORD}\s*(?:mainn|main|mn)\b", r"\b(?:main|mn)\s*(?:no\.?\s*)?(\d{1,2})\b"],
    "gali": [r"(?:gali|glai|gli|gai|गली)\s*(?:no|नं)?[\s.\-]*(\d{1,2})\b", rf"{_ORD}\s*(?:gali|गली)"],
    "ward": [r"\bward\s*(?:no)?[\s.\-]*(\d{1,2})\b", r"वार्ड\s*(?:नं)?[\s.\-]*(\d{1,2})"],
    "road": [rf"{_ORD}\s*(?:road|rd|rad)\b", r"\b(?:road|rd|rad)\s*(?:no\.?\s*)?(\d{1,2})\b"],
    "block": [r"\b(?:block|blk)\s*([a-h])\b", r"\b([a-h])\s*(?:block|blk)\b"],
}
_LOCALITY_MATCH_THRESHOLD = 82
_LANDMARK_FUZZY_THRESHOLD = 84


@dataclass
class ParsedAddress:
    """Structured view of a raw address."""

    locality_id: Optional[str] = None
    locality_score: float = 0.0
    landmark_type: Optional[str] = None
    relation: str = "near"            # near | behind | opposite
    s1: Optional[float] = None        # cross / gali / road number
    s2: Optional[float] = None        # main / ward / block index
    pincode: Optional[str] = None


def _first_match(kind: str, text: str) -> Optional[str]:
    for pattern in _STREET_PATTERNS[kind]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def parse_address(
    text: str,
    localities: Sequence[tuple[str, str]],
    town_name: str = "",
) -> ParsedAddress:
    """Parse a raw address.

    Args:
        text: raw address text.
        localities: (locality_id, locality_name) pairs for the address's town.
        town_name: town name, ignored when looking for landmark words.
    """
    parsed = ParsedAddress()
    t = re.sub(r"[,;:()\"']", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()

    pin = re.search(r"(\d{5,7})\s*$", t)
    if pin:
        parsed.pincode = pin.group(1)[:6]
        t = t[:pin.start()].rstrip(" -")

    cross, main, gali, ward, road, block = (
        _first_match(k, t) for k in ("cross", "main", "gali", "ward", "road", "block")
    )
    if cross or main:
        parsed.s1 = float(cross) if cross else None
        parsed.s2 = float(main) if main else None
    elif gali or ward:
        parsed.s1 = float(gali) if gali else None
        parsed.s2 = float(ward) if ward else None
    elif road or block:
        parsed.s1 = float(road) if road else None
        parsed.s2 = float(ord(block) - ord("a") + 1) if block else None

    tokens = [_ABBREVIATIONS.get(tok, tok) for tok in re.sub(r"[#.\-/]", " ", t).split()]

    best_score, best_id, best_span = 0.0, None, None
    for locality_id, name in localities:
        name = name.lower()
        width = len(name.split())
        for i in range(len(tokens) - width + 1):
            score = fuzz.ratio(" ".join(tokens[i:i + width]), name)
            if score > best_score:
                best_score, best_id, best_span = score, locality_id, (i, i + width)
    if best_id is not None and best_score >= _LOCALITY_MATCH_THRESHOLD:
        parsed.locality_id = best_id
        parsed.locality_score = best_score / 100.0
        tokens = tokens[:best_span[0]] + tokens[best_span[1]:]

    town_tokens = set(town_name.lower().split())
    landmark = next((_KEYWORD_TO_TYPE[tok] for tok in tokens if tok in _KEYWORD_TO_TYPE), None)
    if landmark is None:
        # Tolerate typos such as "communitty" or "cuhrch"
        for tok in tokens:
            if len(tok) < 5 or not tok.isascii() or tok.isdigit() or tok in town_tokens:
                continue
            hit = next((k for k in _FUZZY_KEYWORDS if fuzz.ratio(tok, k) >= _LANDMARK_FUZZY_THRESHOLD), None)
            if hit:
                landmark = _KEYWORD_TO_TYPE[hit]
                break
    parsed.landmark_type = landmark
    if landmark:
        if any(tok in _BEHIND for tok in tokens):
            parsed.relation = "behind"
        elif any(tok in _OPPOSITE for tok in tokens):
            parsed.relation = "opposite"
    return parsed
