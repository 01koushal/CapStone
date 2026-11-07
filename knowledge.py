from models import ConceptKnowledge, StudentProfile


def get_concept(profile: StudentProfile, concept: str) -> ConceptKnowledge:
    if concept not in profile.knowledge:
        profile.knowledge[concept] = ConceptKnowledge()
    return profile.knowledge[concept]


def update_knowledge(profile: StudentProfile, concept: str, correct: bool):
    knowledge = get_concept(profile, concept)
    knowledge.questions_seen += 1
    if correct:
        knowledge.correct += 1
        knowledge.mastery += 0.10
    else:
        knowledge.incorrect += 1
        knowledge.mastery -= 0.10
    knowledge.mastery = max(0.0, min(1.0, knowledge.mastery))
    knowledge.confidence = min(1.0, knowledge.questions_seen / 10)


def get_mastery(profile: StudentProfile, concept: str) -> float:
    return get_concept(profile, concept).mastery


def get_weakest_concept(profile: StudentProfile):
    if not profile.knowledge:
        return None
    return min(profile.knowledge.items(), key=lambda item: item[1].mastery)[0]
