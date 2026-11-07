from knowledge import get_mastery


def choose_difficulty(profile, concept: str) -> int:
    mastery = get_mastery(profile, concept)
    if mastery < 0.40:
        return 1
    if mastery < 0.70:
        return 2
    return 3


def choose_next_concept(profile, default_topic: str):
    weakest = None
    if profile.knowledge:
        weakest = min(profile.knowledge.items(), key=lambda item: item[1].mastery)[0]
    return weakest or default_topic
