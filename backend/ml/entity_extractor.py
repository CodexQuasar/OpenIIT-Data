"""Address entity extraction for Indian addresses."""

import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from rapidfuzz import fuzz, process

from ml.address_normalizer import get_normalizer, NormalizationResult
from app.schemas import AddressEntity, RelationType, NormalizedAddress


class EntityType(str, Enum):
    """Types of address entities."""
    HOUSE_NUMBER = "HOUSE_NUMBER"
    BUILDING = "BUILDING"
    STREET = "STREET"
    CROSS = "CROSS"
    LANDMARK = "LANDMARK"
    LOCALITY = "LOCALITY"
    VILLAGE = "VILLAGE"
    CITY = "CITY"
    DISTRICT = "DISTRICT"
    STATE = "STATE"
    PINCODE = "PINCODE"
    RELATION = "RELATION"
    DIRECTION = "DIRECTION"
    FLOOR = "FLOOR"
    BLOCK = "BLOCK"
    SECTOR = "SECTOR"
    PHASE = "PHASE"
    WING = "WING"
    UNIT = "UNIT"


# Relation patterns with their types
RELATION_PATTERNS = [
    (r"\b(behind|backside|back\s+side|pichhe|peeche|ke\s+peeche)\b", RelationType.BEHIND),
    (r"\b(near|nearby|close\s+to|pas|paas|ke\s+paas|ke\s+pas)\b", RelationType.NEAR),
    (r"\b(opposite|opp|samne|front\s+of)\b", RelationType.OPPOSITE),
    (r"\b(next\s+to|beside|adjacent)\b", RelationType.NEXT_TO),
    (r"\b(after|past|beyond|baad)\b", RelationType.AFTER),
    (r"\b(before|prior\s+to)\b", RelationType.BEFORE),
    (r"\b(between|in\s+between)\b", RelationType.BETWEEN),
    (r"\b(around|surrounding)\b", RelationType.AROUND),
    (r"\b(inside|within|in)\b", RelationType.INSIDE),
    (r"\b(outside|out\s+of)\b", RelationType.OUTSIDE),
    (r"\b(corner|junction)\b", RelationType.CORNER),
    (r"\b(entrance|entry|gate)\b", RelationType.ENTRANCE),
    (r"\b(left\s+of|left)\b", RelationType.LEFT),
    (r"\b(right\s+of|right)\b", RelationType.RIGHT),
    (r"\b(north\s+of|north)\b", RelationType.NORTH),
    (r"\b(south\s+of|south)\b", RelationType.SOUTH),
    (r"\b(east\s+of|east)\b", RelationType.EAST),
    (r"\b(west\s+of|west)\b", RelationType.WEST),
]

# Landmark keywords with categories
LANDMARK_CATEGORIES = {
    "religious": ["temple", "mandir", "masjid", "mosque", "gurudwara", "church", "dargah", "ashram"],
    "commercial": ["market", "bazaar", "shop", "store", "mall", "showroom", "mall", "complex", "plaza"],
    "financial": ["bank", "atm", "post office", "postoffice"],
    "medical": ["hospital", "clinic", "medical", "pharmacy", "chemist", "dispensary"],
    "education": ["school", "college", "university", "institute", "academy"],
    "transport": ["bus stop", "busstand", "railway station", "metro station", "petrol pump", "fuel station"],
    "government": ["police station", "tehsil", "collectorate", "municipal", "panchayat", "court"],
    "food": ["restaurant", "hotel", "dhaba", "cafe", "bakery", "sweet shop"],
    "residential": ["apartment", "flat", "society", "colony", "nagar", "vihar", "enclave", "residency"],
    "infrastructure": ["bridge", "pul", "flyover", "underpass", "tunnel", "dam", "canal"],
    "landmark": ["chowk", "mod", "phatak", "naka", "gate", "darwaza", "circle", "square", "statue", "monument"],
    "utility": ["water tank", "electricity", "transformer", "substation", "tower"],
}

# Common Indian locality suffixes
LOCALITY_SUFFIXES = [
    "nagar", "vihar", "enclave", "colony", "extension", "extn", "puram", "pura",
    "ganj", "bagh", "baugh", "gunj", "mandi", "chowk", "mod", "phatak",
    "sector", "sec", "phase", "block", "pocket", "zone", "area",
    "road", "rd", "street", "st", "lane", "ln", "avenue", "ave",
    "drive", "dr", "boulevard", "blvd", "highway", "hwy", "expressway",
    "cross", "crs", "main", "parallel", "service road", "svc rd",
    "circle", "chowk", "square", "junction", "intersection",
]

# Known Indian states
INDIAN_STATES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar islands", "chandigarh", "dadra and nagar haveli",
    "daman and diu", "delhi", "jammu and kashmir", "ladakh", "lakshadweep",
    "puducherry",
]

# State abbreviations
STATE_ABBREV = {
    "ap": "andhra pradesh", "ar": "arunachal pradesh", "as": "assam",
    "br": "bihar", "cg": "chhattisgarh", "ga": "goa", "gj": "gujarat",
    "hr": "haryana", "hp": "himachal pradesh", "jh": "jharkhand",
    "ka": "karnataka", "kl": "kerala", "mp": "madhya pradesh",
    "mh": "maharashtra", "mn": "manipur", "ml": "meghalaya",
    "mz": "mizoram", "nl": "nagaland", "od": "odisha", "or": "odisha",
    "pb": "punjab", "rj": "rajasthan", "sk": "sikkim", "tn": "tamil nadu",
    "ts": "telangana", "tr": "tripura", "up": "uttar pradesh",
    "uk": "uttarakhand", "wb": "west bengal", "dl": "delhi",
    "jk": "jammu and kashmir", "la": "ladakh", "py": "puducherry",
}


@dataclass
class ExtractedEntities:
    """Container for extracted entities."""
    entities: list[AddressEntity] = field(default_factory=list)
    raw_relations: list[tuple[str, str, str]] = field(default_factory=list)  # (entity, relation, target)
    pincode: Optional[str] = None
    landmark: Optional[str] = None
    confidence: float = 0.0


class EntityExtractor:
    """Extracts structured entities from normalized Indian addresses."""

    def __init__(self):
        self.normalizer = get_normalizer()
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for entity extraction."""
        # House number patterns
        self.house_number_patterns = [
            re.compile(r"\b(?:house|h\.?no|flat|unit|apartment|apt)\s*[#\-:]?\s*([a-z0-9\-\/]+)", re.IGNORECASE),
            re.compile(r"\b([0-9]+[a-z]?(?:[\-\/][0-9]+[a-z]?)?)\b(?=\s+(?:street|road|lane|cross|main|avenue))", re.IGNORECASE),
            re.compile(r"\bplot\s*[#\-:]?\s*([a-z0-9\-\/]+)", re.IGNORECASE),
            re.compile(r"\bdoor\s*[#\-:]?\s*([a-z0-9\-\/]+)", re.IGNORECASE),
            re.compile(r"\b(?:no|number)\s*[#\-:]?\s*([a-z0-9\-\/]+)", re.IGNORECASE),
        ]

        # Pincode pattern
        self.pincode_pattern = re.compile(r"\b(\d{6})\b")

        # Floor patterns
        self.floor_pattern = re.compile(r"\b(?:floor|flr|fl)\s*[#\-:]?\s*([0-9]+(?:st|nd|rd|th)?|ground|g|lower|upper|basement)", re.IGNORECASE)

        # Block/Wing patterns
        self.block_pattern = re.compile(r"\b(?:block|blk|wing|tower|building|bldg)\s*[#\-:]?\s*([a-z0-9]+)", re.IGNORECASE)

        # Sector/Phase patterns
        self.sector_pattern = re.compile(r"\b(?:sector|sec|phase)\s*[#\-:]?\s*([0-9]+[a-z]?)", re.IGNORECASE)

        # Cross/Road patterns
        self.cross_pattern = re.compile(r"\b(\d+(?:st|nd|rd|th)?)\s*(?:cross|crs|xrd)\b", re.IGNORECASE)
        self.road_pattern = re.compile(r"\b([a-z\s]+?)\s+(?:road|rd|street|st|lane|ln|avenue|ave|main|cross)\b", re.IGNORECASE)

    def extract(self, address: str) -> NormalizedAddress:
        """Full extraction pipeline."""
        # First normalize
        norm_result = self.normalizer.normalize(address)
        
        # Extract entities from normalized address
        extracted = self._extract_entities(norm_result.normalized_address)
        
        # Build NormalizedAddress
        normalized = NormalizedAddress(
            raw_address=norm_result.raw_address,
            normalized_address=norm_result.normalized_address,
            language=norm_result.language,
            entities=extracted.entities,
            pincode=extracted.pincode,
            locality=self._find_entity_value(extracted.entities, EntityType.LOCALITY),
            city=self._find_entity_value(extracted.entities, EntityType.CITY),
            state=self._find_entity_value(extracted.entities, EntityType.STATE),
            landmark=extracted.landmark,
            confidence=min(norm_result.confidence, extracted.confidence),
        )
        
        return normalized

    def _extract_entities(self, text: str) -> ExtractedEntities:
        """Extract all entities from normalized text."""
        result = ExtractedEntities()
        text_lower = text.lower()
        
        # Extract pincode first (remove from text to avoid confusion)
        result.pincode = self._extract_pincode(text_lower)
        
        # Extract relations
        relations = self._extract_relations(text_lower)
        result.raw_relations = relations
        
        # Extract landmarks
        result.landmark = self._extract_landmark(text_lower, relations)
        
        # Extract other entities
        self._extract_house_number(text_lower, result)
        self._extract_building(text_lower, result)
        self._extract_street_cross(text_lower, result)
        self._extract_locality_city_state(text_lower, result)
        self._extract_floor_block_sector(text_lower, result)
        self._extract_directions(text_lower, result)
        
        # Calculate confidence
        result.confidence = self._calculate_confidence(result, text_lower)
        
        return result

    def _extract_pincode(self, text: str) -> Optional[str]:
        """Extract 6-digit pincode."""
        match = self.pincode_pattern.search(text)
        if match:
            return match.group(1)
        return None

    def _extract_relations(self, text: str) -> list[tuple[str, str, str]]:
        """Extract spatial relations between entities."""
        relations = []
        
        for pattern, rel_type in RELATION_PATTERNS:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for match in matches:
                relation_word = match.group(0)
                # Find entity before and after relation
                before_text = text[:match.start()].strip()
                after_text = text[match.end():].strip()
                
                # Get last meaningful word before
                before_words = before_text.split()
                before_entity = before_words[-1] if before_words else ""
                
                # Get first meaningful word after
                after_words = after_text.split()
                after_entity = after_words[0] if after_words else ""
                
                if before_entity or after_entity:
                    relations.append((before_entity, relation_word, after_entity))
        
        return relations

    def _extract_landmark(self, text: str, relations: list[tuple]) -> Optional[str]:
        """Extract primary landmark."""
        # Check relations for landmark targets
        for before, rel, after in relations:
            if any(kw in after.lower() for cat in LANDMARK_CATEGORIES.values() for kw in cat):
                return after
            if any(kw in before.lower() for cat in LANDMARK_CATEGORIES.values() for kw in cat):
                return before
        
        # Fallback: find any landmark keyword in text
        for category, keywords in LANDMARK_CATEGORIES.items():
            for kw in keywords:
                if kw in text:
                    # Extract surrounding context
                    pattern = rf"([a-z\s]{{0,20}}{re.escape(kw)}[a-z\s]{{0,20}})"
                    match = re.search(pattern, text)
                    if match:
                        return match.group(1).strip()
        
        return None

    def _extract_house_number(self, text: str, result: ExtractedEntities):
        """Extract house/flat/plot number."""
        for pattern in self.house_number_patterns:
            matches = pattern.findall(text)
            for match in matches:
                entity = AddressEntity(
                    entity_type=EntityType.HOUSE_NUMBER.value,
                    value=match,
                    confidence=0.8,
                )
                result.entities.append(entity)

    def _extract_building(self, text: str, result: ExtractedEntities):
        """Extract building/apartment/society name."""
        # Pattern: "X apartment", "X society", "X building", "X residency"
        patterns = [
            re.compile(r"\b([a-z\s]+?)\s+(?:apartment|apt|society|soc|building|bldg|residency|complex|tower|heights|plaza)\b", re.IGNORECASE),
            re.compile(r"\b(?:apartment|apt|society|soc|building|bldg|residency|complex|tower|heights|plaza)\s+(?:named\s+)?([a-z\s]+?)(?:\s+(?:road|street|lane|cross|main|sector|phase|block))", re.IGNORECASE),
        ]
        
        for pattern in patterns:
            matches = pattern.findall(text)
            for match in matches:
                entity = AddressEntity(
                    entity_type=EntityType.BUILDING.value,
                    value=match.strip(),
                    confidence=0.75,
                )
                result.entities.append(entity)

    def _extract_street_cross(self, text: str, result: ExtractedEntities):
        """Extract street, road, cross, main."""
        # Cross patterns: "2nd cross", "3rd cross", etc.
        cross_matches = self.cross_pattern.findall(text)
        for match in cross_matches:
            entity = AddressEntity(
                entity_type=EntityType.CROSS.value,
                value=f"{match} cross",
                confidence=0.9,
            )
            result.entities.append(entity)
        
        # Road/Street patterns
        road_matches = self.road_pattern.findall(text)
        for match in road_matches:
            entity = AddressEntity(
                entity_type=EntityType.STREET.value,
                value=f"{match.strip()} road",
                confidence=0.8,
            )
            result.entities.append(entity)
        
        # Generic "main road", "main cross"
        if "main road" in text or "main cross" in text:
            entity = AddressEntity(
                entity_type=EntityType.STREET.value,
                value="main road" if "main road" in text else "main cross",
                confidence=0.7,
            )
            result.entities.append(entity)

    def _extract_locality_city_state(self, text: str, result: ExtractedEntities):
        """Extract locality, city, state."""
        words = text.split()
        
        # Check for state names
        for state in INDIAN_STATES:
            if state in text:
                entity = AddressEntity(
                    entity_type=EntityType.STATE.value,
                    value=state.title(),
                    confidence=0.95,
                )
                result.entities.append(entity)
                # Remove from text to avoid duplicate matching
                text = text.replace(state, "")
        
        # Check for state abbreviations
        for abbrev, full in STATE_ABBREV.items():
            if f" {abbrev} " in f" {text} " or text.endswith(f" {abbrev}") or text.startswith(f"{abbrev} "):
                entity = AddressEntity(
                    entity_type=EntityType.STATE.value,
                    value=full.title(),
                    confidence=0.85,
                )
                result.entities.append(entity)
        
        # Locality: often appears before city/state, after landmark/street
        # This is heuristic - in practice would use NER or gazetteer
        locality_indicators = ["nagar", "vihar", "colony", "enclave", "puram", "ganj", "bagh"]
        for indicator in locality_indicators:
            pattern = rf"([a-z\s]+?)\s+{indicator}\b"
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                entity = AddressEntity(
                    entity_type=EntityType.LOCALITY.value,
                    value=f"{match.strip()} {indicator}".title(),
                    confidence=0.7,
                )
                result.entities.append(entity)

    def _extract_floor_block_sector(self, text: str, result: ExtractedEntities):
        """Extract floor, block, sector, phase."""
        # Floor
        floor_match = self.floor_pattern.search(text)
        if floor_match:
            entity = AddressEntity(
                entity_type=EntityType.FLOOR.value,
                value=floor_match.group(1),
                confidence=0.8,
            )
            result.entities.append(entity)
        
        # Block/Wing
        block_match = self.block_pattern.search(text)
        if block_match:
            entity = AddressEntity(
                entity_type=EntityType.BLOCK.value,
                value=block_match.group(1),
                confidence=0.8,
            )
            result.entities.append(entity)
        
        # Sector/Phase
        sector_match = self.sector_pattern.search(text)
        if sector_match:
            entity = AddressEntity(
                entity_type=EntityType.SECTOR.value,
                value=f"sector {sector_match.group(1)}",
                confidence=0.85,
            )
            result.entities.append(entity)

    def _extract_directions(self, text: str, result: ExtractedEntities):
        """Extract directional information."""
        direction_keywords = {
            "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest",
            "left", "right", "front", "back", "behind",
        }
        
        for direction in direction_keywords:
            if f" {direction} " in f" {text} " or text.endswith(f" {direction}") or text.startswith(f"{direction} "):
                entity = AddressEntity(
                    entity_type=EntityType.DIRECTION.value,
                    value=direction,
                    confidence=0.7,
                )
                result.entities.append(entity)

    def _find_entity_value(self, entities: list[AddressEntity], entity_type: EntityType) -> Optional[str]:
        """Find value of specific entity type."""
        for entity in entities:
            if entity.entity_type == entity_type.value:
                return entity.value
        return None

    def _calculate_confidence(self, result: ExtractedEntities, text: str) -> float:
        """Calculate overall extraction confidence."""
        if not result.entities:
            return 0.3
        
        # Average entity confidence
        entity_conf = sum(e.confidence for e in result.entities) / len(result.entities)
        
        # Bonus for pincode
        pincode_bonus = 0.1 if result.pincode else 0.0
        
        # Bonus for landmark
        landmark_bonus = 0.1 if result.landmark else 0.0
        
        # Bonus for relations
        relation_bonus = min(0.1, len(result.raw_relations) * 0.03)
        
        return min(1.0, entity_conf + pincode_bonus + landmark_bonus + relation_bonus)


# Singleton instance
_extractor = None


def get_extractor() -> EntityExtractor:
    """Get singleton extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = EntityExtractor()
    return _extractor


def extract_entities(address: str) -> NormalizedAddress:
    """Convenience function to extract entities from address."""
    return get_extractor().extract(address)