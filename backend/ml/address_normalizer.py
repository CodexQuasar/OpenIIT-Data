"""Address normalization for messy Indian addresses."""

import re
import unicodedata
from typing import Optional
from dataclasses import dataclass

from rapidfuzz import fuzz, process


@dataclass
class NormalizationResult:
    """Result of address normalization."""
    raw_address: str
    normalized_address: str
    language: Optional[str]
    confidence: float


class AddressNormalizer:
    """Normalizes messy Indian addresses."""

    # Common Indian address abbreviations
    ABBREVIATIONS = {
        # English abbreviations
        r"\bno\.?\b": "number",
        r"\bflat\.?\b": "flat",
        r"\bapt\.?\b": "apartment",
        r"\bapts?\.?\b": "apartments",
        r"\bbldg\.?\b": "building",
        r"\bsoc\.?\b": "society",
        r"\bsociety\.?\b": "society",
        r"\bsec\.?\b": "sector",
        r"\bsect\.?\b": "sector",
        r"\bblk\.?\b": "block",
        r"\bflr\.?\b": "floor",
        r"\brd\.?\b": "road",
        r"\bst\.?\b": "street",
        r"\bave\.?\b": "avenue",
        r"\bln\.?\b": "lane",
        r"\bdr\.?\b": "drive",
        r"\bcrs?\.?\b": "cross",
        r"\bgali\.?\b": "gali",
        r"\bgl\.?\b": "gali",
        r"\bxrd?\.?\b": "cross",
        r"\bmain\.?\b": "main",
        r"\bcross\.?\b": "cross",
        r"\bnear\.?\b": "near",
        r"\bopp\.?\b": "opposite",
        r"\boppst\.?\b": "opposite",
        r"\bbehind\.?\b": "behind",
        r"\bbhnd\.?\b": "behind",
        r"\bnext\s+to\.?\b": "next to",
        r"\bcorner\.?\b": "corner",
        r"\bentrance\.?\b": "entrance",
        r"\bbackside\.?\b": "backside",
        r"\bback\s+side\.?\b": "backside",

        # Hindi/Devanagari abbreviations (transliterated)
        r"\bke\s+peeche?\b": "behind",
        r"\bke\s+paas\b": "near",
        r"\bke\s+paas\s+mein\b": "near",
        r"\bsamne\b": "opposite",
        r"\bpas\b": "near",
        r"\bpaas\b": "near",
        r"\bpichhe\b": "behind",
        r"\bpeeche\b": "behind",
        r"\baage\b": "in front",
        r"\bbaad\b": "after",
        r"\bpurana\b": "old",
        r"\bnaya\b": "new",
        r"\bchota\b": "small",
        r"\bbada\b": "big",
        r"\bmandir\b": "temple",
        r"\bmasjid\b": "mosque",
        r"\bgurudwara\b": "gurudwara",
        r"\bchurch\b": "church",
        r"\bhospital\b": "hospital",
        r"\bschool\b": "school",
        r"\bcollege\b": "college",
        r"\bbank\b": "bank",
        r"\bpost\s*office\b": "post office",
        r"\bration\s*shop\b": "ration shop",
        r"\bkirana\b": "kirana",
        r"\bmedical\b": "medical",
        r"\bclinic\b": "clinic",
        r"\bpetrol\s*pump\b": "petrol pump",
        r"\bbus\s*stop\b": "bus stop",
        r"\brailway\s*station\b": "railway station",
        r"\bmetro\s*station\b": "metro station",
        r"\bpolice\s*station\b": "police station",
        r"\bmarket\b": "market",
        r"\bchowk\b": "chowk",
        r"\bmod\b": "mod",
        r"\bphatak\b": "phatak",
        r"\bpul\b": "bridge",
        r"\bbridge\b": "bridge",
        r"\bnaka\b": "naka",
        r"\bgate\b": "gate",
        r"\bdarwaza\b": "gate",
    }

    # Direction words
    DIRECTIONS = {
        "north", "south", "east", "west",
        "northeast", "northwest", "southeast", "southwest",
        "left", "right", "front", "back", "behind",
        "aage", "peeche", "pichhe", "baad", "purana", "naya",
        "dakshin", "uttar", "poorva", "paschim",
    }

    # Landmark keywords
    LANDMARK_KEYWORDS = {
        "temple", "mandir", "masjid", "mosque", "gurudwara", "church",
        "hospital", "school", "college", "university", "bank", "atm",
        "post office", "ration shop", "kirana", "medical", "clinic",
        "petrol pump", "bus stop", "railway station", "metro station",
        "police station", "market", "chowk", "mod", "phatak", "pul",
        "bridge", "naka", "gate", "darwaza", "park", "garden",
        "mall", "shop", "store", "showroom", "factory", "industry",
        "company", "office", "building", "tower", "complex", "plaza",
        "hotel", "restaurant", "dhaba", "cafe", "bakery", "sweet",
    }

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for abbreviation expansion."""
        self.abbrev_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.ABBREVIATIONS.items()
        ]

    def normalize_unicode(self, text: str) -> str:
        """Normalize Unicode characters."""
        # Normalize to NFC form
        text = unicodedata.normalize("NFC", text)
        # Replace common lookalikes
        text = text.replace("\u2019", "'").replace("\u2018", "'")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        text = text.replace("\u2013", "-").replace("\u2014", "-")
        text = text.replace("\u00a0", " ")
        return text

    def expand_abbreviations(self, text: str) -> str:
        """Expand common abbreviations."""
        for pattern, replacement in self.abbrev_patterns:
            text = pattern.sub(replacement, text)
        return text

    def normalize_punctuation(self, text: str) -> str:
        """Normalize punctuation and whitespace."""
        # Replace multiple spaces with single
        text = re.sub(r"\s+", " ", text)
        # Normalize commas and separators
        text = re.sub(r"[;|/\\]+", ",", text)
        # Remove extra punctuation around commas
        text = re.sub(r"\s*,\s*", ", ", text)
        text = re.sub(r",+", ",", text)
        # Trim
        text = text.strip(" ,.;")
        return text

    def normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace."""
        return re.sub(r"\s+", " ", text).strip()

    def lowercase_normalize(self, text: str) -> str:
        """Lowercase with Unicode awareness."""
        return text.lower()

    def detect_language(self, text: str) -> Optional[str]:
        """Detect primary language of address."""
        # Simple heuristic based on script
        devanagari = len(re.findall(r"[\u0900-\u097F]", text))
        bengali = len(re.findall(r"[\u0980-\u09FF]", text))
        gujarati = len(re.findall(r"[\u0A80-\u0AFF]", text))
        gurmukhi = len(re.findall(r"[\u0A00-\u0A7F]", text))
        kannada = len(re.findall(r"[\u0C80-\u0CFF]", text))
        malayalam = len(re.findall(r"[\u0D00-\u0D7F]", text))
        oriya = len(re.findall(r"[\u0B00-\u0B7F]", text))
        tamil = len(re.findall(r"[\u0B80-\u0BFF]", text))
        telugu = len(re.findall(r"[\u0C00-\u0C7F]", text))
        latin = len(re.findall(r"[a-zA-Z]", text))

        counts = {
            "hi": devanagari,
            "bn": bengali,
            "gu": gujarati,
            "pa": gurmukhi,
            "kn": kannada,
            "ml": malayalam,
            "or": oriya,
            "ta": tamil,
            "te": telugu,
            "en": latin,
        }

        max_lang = max(counts, key=counts.get)
        if counts[max_lang] > 0:
            return max_lang
        return None

    def normalize_pincode(self, text: str) -> Optional[str]:
        """Extract and normalize pincode."""
        # Indian pincode: 6 digits
        match = re.search(r"\b(\d{6})\b", text)
        if match:
            return match.group(1)
        return None

    def normalize(self, address: str) -> NormalizationResult:
        """Full normalization pipeline."""
        if not address or not address.strip():
            return NormalizationResult(
                raw_address=address,
                normalized_address="",
                language=None,
                confidence=0.0
            )

        raw = address.strip()
        language = self.detect_language(raw)

        # Pipeline
        text = self.normalize_unicode(raw)
        text = self.lowercase_normalize(text)
        text = self.expand_abbreviations(text)
        text = self.normalize_punctuation(text)
        text = self.normalize_whitespace(text)

        # Calculate confidence based on transformations
        confidence = self._calculate_confidence(raw, text)

        return NormalizationResult(
            raw_address=raw,
            normalized_address=text,
            language=language,
            confidence=confidence
        )

    def _calculate_confidence(self, raw: str, normalized: str) -> float:
        """Calculate normalization confidence."""
        if not raw:
            return 0.0
        
        # Ratio of preserved alphanumeric characters
        raw_alnum = len(re.findall(r"[a-zA-Z0-9\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0A00-\u0A7F\u0C80-\u0CFF\u0D00-\u0D7F\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F]", raw))
        norm_alnum = len(re.findall(r"[a-zA-Z0-9\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0A00-\u0A7F\u0C80-\u0CFF\u0D00-\u0D7F\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F]", normalized))
        
        if raw_alnum == 0:
            return 0.5
        
        preservation = min(1.0, norm_alnum / max(1, raw_alnum))
        
        # Bonus for successful abbreviation expansion
        expansion_bonus = 0.1 if len(normalized) > len(raw) * 0.8 else 0.0
        
        return min(1.0, preservation + expansion_bonus)


# Singleton instance
_normalizer = None


def get_normalizer() -> AddressNormalizer:
    """Get singleton normalizer instance."""
    global _normalizer
    if _normalizer is None:
        _normalizer = AddressNormalizer()
    return _normalizer


def normalize_address(address: str) -> NormalizationResult:
    """Convenience function to normalize an address."""
    return get_normalizer().normalize(address)