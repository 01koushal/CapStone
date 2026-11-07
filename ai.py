import json, os, re, uuid
from dotenv import load_dotenv
from openai import OpenAI
from models import Question
load_dotenv()
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

def generate_question(topic: str, concept: str, difficulty: int, previous_questions=None, previous_answer=None) -> Question:
    """Groq-backed adaptation of the original repository's question generator."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured. Add it to your .env file.")
    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=40.0, max_retries=0)
    difficulty_name = {1:"Easy",2:"Medium",3:"Hard"}.get(int(difficulty),"Medium")
    system_prompt = """You are an expert AI assessment question generator. Generate high-quality multiple-choice questions. Test the requested concept and difficulty, use exactly four distinct options, exactly one correct answer, make it clear and unambiguous, avoid repeats, and keep it educationally meaningful. Return ONLY valid JSON with no markdown."""
    user_message = f"""Generate one assessment question.
Topic: {topic}
Concept: {concept}
Difficulty: {difficulty_name} (level {difficulty})
Previous questions: {json.dumps(previous_questions or [], ensure_ascii=False)}
Previous student answer: {json.dumps(previous_answer, ensure_ascii=False)}
Return JSON with keys topic, concept, difficulty, question, options (exactly four strings), correct_answer (exact option string), explanation."""
    response = client.chat.completions.create(model=MODEL, messages=[
        {"role":"system","content":system_prompt},{"role":"user","content":user_message}
    ], temperature=0.7, max_completion_tokens=3000)
    if not response.choices:
        raise ValueError("The AI service returned no choices.")
    message=response.choices[0].message
    raw=message.content
    if isinstance(raw,list):
        raw="".join(getattr(x,"text","") or "" for x in raw)
    if not raw:
        raise ValueError(f"The AI returned an empty response (finish reason: {response.choices[0].finish_reason}).")
    raw=raw.strip()
    raw=re.sub(r"^```(?:json)?\s*|\s*```$","",raw,flags=re.I)
    start,end=raw.find("{"),raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The AI response did not contain a JSON object. Please retry.")
    data=json.loads(raw[start:end+1])
    required=("topic","concept","difficulty","question","options","correct_answer","explanation")
    missing=[k for k in required if k not in data]
    if missing: raise ValueError("AI response missing: "+", ".join(missing))
    options=data["options"]
    if not isinstance(options,list) or len(options)!=4 or any(not isinstance(x,str) or not x.strip() for x in options) or len(set(options))!=4:
        raise ValueError("AI must return four distinct, non-empty options.")
    if data["correct_answer"] not in options:
        raise ValueError("AI correct answer does not match one of its options.")
    # Models sometimes echo the prompt label ("Medium (level 2)") instead
    # of returning the requested integer. Normalize both forms safely.
    raw_difficulty = data.get("difficulty", difficulty)
    if isinstance(raw_difficulty, (int, float)):
        parsed_difficulty = int(raw_difficulty)
    else:
        label = str(raw_difficulty).strip().lower()
        match = re.search(r"\\b([123])\\b", label)
        if match:
            parsed_difficulty = int(match.group(1))
        elif "easy" in label:
            parsed_difficulty = 1
        elif "medium" in label:
            parsed_difficulty = 2
        elif "hard" in label:
            parsed_difficulty = 3
        else:
            parsed_difficulty = int(difficulty)
    if parsed_difficulty not in (1, 2, 3):
        parsed_difficulty = int(difficulty)

    return Question(id=str(uuid.uuid4()),topic=str(data["topic"]),concept=str(data["concept"]),
        difficulty=parsed_difficulty,question=str(data["question"]),options=options,
        correct_answer=data["correct_answer"],explanation=str(data["explanation"]))
