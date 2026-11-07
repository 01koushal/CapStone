
from models import ConceptKnowledge, StudentProfile


PRIOR_CORRECT = 2
PRIOR_INCORRECT = 2


def calculate_mastery(correct: int, incorrect: int) -> float:
    """
    Beta-Binomial posterior mean.
    Starts at 0.50 and becomes more reliable with observations.
    """
    correct = max(0, int(correct))
    incorrect = max(0, int(incorrect))

    alpha = PRIOR_CORRECT + correct
    beta = PRIOR_INCORRECT + incorrect

    return alpha / (alpha + beta)


def calculate_confidence(questions_seen: int) -> float:
    """
    Evidence strength, not probability of correctness.
    """
    n = max(0, int(questions_seen))
    return n / (n + 4)


def get_concept(profile: StudentProfile, concept: str) -> ConceptKnowledge:
    if concept not in profile.knowledge:
        profile.knowledge[concept] = ConceptKnowledge()

    return profile.knowledge[concept]


def normalize_knowledge(knowledge: ConceptKnowledge):
    """
    Recalculate estimates from historical answer counts.
    This also upgrades previously stored profiles automatically.
    """
    knowledge.correct = max(0, int(knowledge.correct))
    knowledge.incorrect = max(0, int(knowledge.incorrect))

    knowledge.questions_seen = (
        knowledge.correct + knowledge.incorrect
    )

    knowledge.mastery = calculate_mastery(
        knowledge.correct,
        knowledge.incorrect
    )

    knowledge.confidence = calculate_confidence(
        knowledge.questions_seen
    )

    return knowledge


def update_knowledge(
    profile: StudentProfile,
    concept: str,
    correct: bool
):
    knowledge = get_concept(profile, concept)

    if correct:
        knowledge.correct += 1
    else:
        knowledge.incorrect += 1

    normalize_knowledge(knowledge)


def get_mastery(profile: StudentProfile, concept: str) -> float:
    knowledge = get_concept(profile, concept)
    normalize_knowledge(knowledge)

    return knowledge.mastery


def get_confidence(profile: StudentProfile, concept: str) -> float:
    knowledge = get_concept(profile, concept)
    normalize_knowledge(knowledge)

    return knowledge.confidence


def get_uncertainty(profile: StudentProfile, concept: str) -> float:
    """
    Posterior standard deviation of the Beta distribution.
    Higher value means less evidence about the concept.
    """
    knowledge = get_concept(profile, concept)

    alpha = PRIOR_CORRECT + max(0, knowledge.correct)
    beta = PRIOR_INCORRECT + max(0, knowledge.incorrect)

    total = alpha + beta

    variance = (
        alpha * beta /
        ((total ** 2) * (total + 1))
    )

    return variance ** 0.5


def get_weakest_concept(profile: StudentProfile):
    if not profile.knowledge:
        return None

    return min(
        profile.knowledge.items(),
        key=lambda item: item[1].mastery
    )[0]
