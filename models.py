from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Question:
    id: str
    topic: str
    concept: str
    difficulty: int
    question: str
    options: List[str]
    correct_answer: str
    explanation: str

@dataclass
class ConceptKnowledge:
    mastery: float = 0.5
    confidence: float = 0.0
    questions_seen: int = 0
    correct: int = 0
    incorrect: int = 0

@dataclass
class StudentProfile:
    name: str
    knowledge: Dict[str, ConceptKnowledge] = field(default_factory=dict)
