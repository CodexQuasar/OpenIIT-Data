"""Directions generation from address entities and landmarks."""

import math
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from app.schemas import NormalizedAddress, AddressEntity, CandidateLocation, RelationType
from ml.entity_extractor import EntityType


class DirectionStepType(str, Enum):
    """Types of direction steps."""
    START = "start"
    GO_TO_LANDMARK = "go_to_landmark"
    TURN = "turn"
    CONTINUE = "continue"
    PASS_LANDMARK = "pass_landmark"
    DESTINATION = "destination"


@dataclass
class DirectionStep:
    """Single step in directions."""
    step_type: DirectionStepType
    instruction: str
    landmark: Optional[str] = None
    relation: Optional[RelationType] = None
    distance_m: Optional[float] = None
    bearing: Optional[float] = None


class DirectionsGenerator:
    """Generates human-readable landmark-based directions."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.max_steps = self.config.get("max_steps", 8)

    def generate(self, 
                 normalized_address: NormalizedAddress,
                 candidate: CandidateLocation,
                 reference_location: tuple[float, float] = None) -> str:
        """Generate directions from reference location to candidate."""
        steps = self._build_steps(normalized_address, candidate, reference_location)
        return self._format_steps(steps)

    def _build_steps(self,
                     normalized_address: NormalizedAddress,
                     candidate: CandidateLocation,
                     reference_location: tuple[float, float] = None) -> List[DirectionStep]:
        """Build direction steps from address entities."""
        steps = []
        
        # Extract landmarks and relations
        landmarks = []
        relations = []
        
        for entity in normalized_address.entities:
            if entity.entity_type == EntityType.LANDMARK.value:
                landmarks.append(entity.value)
                if entity.relation:
                    relations.append((entity.value, entity.relation))
            elif entity.entity_type == EntityType.STREET.value:
                landmarks.append(entity.value)
            elif entity.entity_type == EntityType.CROSS.value:
                landmarks.append(entity.value)
            elif entity.entity_type == EntityType.BUILDING.value:
                landmarks.append(entity.value)
        
        if normalized_address.landmark and normalized_address.landmark not in landmarks:
            landmarks.insert(0, normalized_address.landmark)
        
        # If no landmarks found, use locality
        if not landmarks and normalized_address.locality:
            landmarks.append(normalized_address.locality)
        
        # Build steps
        step_num = 1
        
        # Step 1: Go to primary landmark
        if landmarks:
            primary = landmarks[0]
            relation = None
            for lm, rel in relations:
                if lm == primary:
                    relation = rel
                    break
            
            if relation:
                instruction = self._relation_instruction(relation, primary)
            else:
                instruction = f"Reach {primary}."
            
            steps.append(DirectionStep(
                step_type=DirectionStepType.GO_TO_LANDMARK,
                instruction=instruction,
                landmark=primary,
                relation=relation,
            ))
        
        # Step 2: Handle secondary landmarks with relations
        for i, landmark in enumerate(landmarks[1:3], 1):  # Max 2 more landmarks
            relation = None
            for lm, rel in relations:
                if lm == landmark:
                    relation = rel
                    break
            
            if relation:
                instruction = self._relation_instruction(relation, landmark)
            else:
                instruction = f"Continue towards {landmark}."
            
            steps.append(DirectionStep(
                step_type=DirectionStepType.PASS_LANDMARK,
                instruction=instruction,
                landmark=landmark,
                relation=relation,
            ))
        
        # Step 3: Handle cross/road
        cross_entities = [e for e in normalized_address.entities if e.entity_type == EntityType.CROSS.value]
        if cross_entities:
            cross = cross_entities[0].value
            steps.append(DirectionStep(
                step_type=DirectionStepType.CONTINUE,
                instruction=f"Continue on {cross}.",
                landmark=cross,
            ))
        
        # Step 4: Final approach
        if candidate and (candidate.latitude, candidate.longitude) != (0, 0):
            steps.append(DirectionStep(
                step_type=DirectionStepType.DESTINATION,
                instruction="The predicted location is approximately at this point.",
            ))
        
        return steps[:self.max_steps]

    def _relation_instruction(self, relation: RelationType, landmark: str) -> str:
        """Generate instruction for a spatial relation."""
        instructions = {
            RelationType.BEHIND: f"Go behind {landmark}.",
            RelationType.NEAR: f"Look near {landmark}.",
            RelationType.OPPOSITE: f"Go opposite {landmark}.",
            RelationType.NEXT_TO: f"Go next to {landmark}.",
            RelationType.AFTER: f"Go past {landmark}, then continue.",
            RelationType.BEFORE: f"Stop before {landmark}.",
            RelationType.BETWEEN: f"Go between {landmark} and the next landmark.",
            RelationType.AROUND: f"Go around {landmark}.",
            RelationType.INSIDE: f"Go inside {landmark}.",
            RelationType.OUTSIDE: f"Go outside {landmark}.",
            RelationType.CORNER: f"Turn at the corner of {landmark}.",
            RelationType.ENTRANCE: f"Enter through {landmark} entrance.",
            RelationType.BACKSIDE: f"Go to the backside of {landmark}.",
            RelationType.FRONT: f"Go to the front of {landmark}.",
            RelationType.LEFT: f"Turn left at {landmark}.",
            RelationType.RIGHT: f"Turn right at {landmark}.",
            RelationType.NORTH: f"Go north from {landmark}.",
            RelationType.SOUTH: f"Go south from {landmark}.",
            RelationType.EAST: f"Go east from {landmark}.",
            RelationType.WEST: f"Go west from {landmark}.",
        }
        return instructions.get(relation, f"Find {landmark}.")

    def _format_steps(self, steps: List[DirectionStep]) -> str:
        """Format steps into readable directions."""
        if not steps:
            return "No directions available."
        
        lines = []
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step.instruction}")
        
        return "\n".join(lines)

    def generate_field_agent_directions(self,
                                         normalized_address: NormalizedAddress,
                                         candidate: CandidateLocation,
                                         current_location: tuple[float, float] = None) -> dict:
        """Generate structured directions for field agent view."""
        steps = self._build_steps(normalized_address, candidate, current_location)
        
        return {
            "steps": [
                {
                    "step_number": i + 1,
                    "instruction": step.instruction,
                    "landmark": step.landmark,
                    "relation": step.relation.value if step.relation else None,
                    "type": step.step_type.value,
                }
                for i, step in enumerate(steps)
            ],
            "summary": self._format_steps(steps),
            "confidence_radius_m": 0,  # Will be filled by caller
            "primary_landmark": steps[0].landmark if steps else None,
        }


def generate_directions(
    normalized_address: NormalizedAddress,
    candidate: CandidateLocation,
    reference_location: tuple[float, float] = None,
    config: dict = None
) -> str:
    """Convenience function to generate directions."""
    generator = DirectionsGenerator(config)
    return generator.generate(normalized_address, candidate, reference_location)


def generate_field_directions(
    normalized_address: NormalizedAddress,
    candidate: CandidateLocation,
    current_location: tuple[float, float] = None,
    config: dict = None
) -> dict:
    """Convenience function for field agent directions."""
    generator = DirectionsGenerator(config)
    return generator.generate_field_agent_directions(normalized_address, candidate, current_location)