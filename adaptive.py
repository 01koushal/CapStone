
from knowledge import (
    get_concept,
    get_mastery,
    get_uncertainty
)


EXPLORATION_WEIGHT = 0.75


def choose_difficulty(profile, concept: str) -> int:
    """
    Select difficulty using Bayesian mastery estimation.

    1 = Easy
    2 = Medium
    3 = Hard
    """
    mastery = get_mastery(profile, concept)

    if mastery < 0.40:
        return 1

    if mastery < 0.70:
        return 2

    return 3


def choose_next_concept(
    profile,
    concepts,
    default_topic=None
):
    """
    Balance weak-concept revision with exploration.

    Concepts with low mastery receive priority.
    Concepts with little evidence receive an exploration bonus.

    Lower selection score = higher priority.
    """

    if isinstance(concepts, str):
        concepts = [concepts]

    candidates = [
        concept.strip()
        for concept in concepts
        if isinstance(concept, str) and concept.strip()
    ]

    if not candidates:
        return default_topic

    best_concept = None
    best_score = float("inf")

    for concept in candidates:
        knowledge = get_concept(profile, concept)

        mastery = get_mastery(profile, concept)
        uncertainty = get_uncertainty(profile, concept)

        # Lower mastery increases priority.
        # Higher uncertainty encourages exploration.
        score = (
            mastery -
            EXPLORATION_WEIGHT * uncertainty
        )

        if score < best_score:
            best_score = score
            best_concept = concept

    return best_concept or default_topic
