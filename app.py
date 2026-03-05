import os
import json
import signal
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import anthropic
import openai
from google import genai
from google.genai import types as genai_types
import config

app = Flask(__name__)

# Initialize API clients
anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
openai_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

DISCUSSIONS_DIR = os.path.join(os.path.dirname(__file__), "discussions")
os.makedirs(DISCUSSIONS_DIR, exist_ok=True)

MAX_TOPIC_LENGTH = 2000
API_TIMEOUT = 60  # seconds per model call


def format_history(history):
    return "".join(
        f"[{entry['model']} - Round {entry['round']}]\n{entry['text']}\n\n"
        for entry in history
    )


def build_initial_prompt(topic):
    return (
        "You are participating in a structured discussion with two other AI models "
        "(Claude, ChatGPT, and Gemini). Please give your initial thoughts on the "
        "following topic. Be substantive and take a clear position where appropriate.\n\n"
        f"Topic: {topic}"
    )


def build_followup_prompt(topic, history, model_name):
    return (
        f"You are {model_name} participating in a multi-round discussion. Here is the "
        "discussion so far:\n\n"
        f"{format_history(history)}"
        "Please respond to the other models' points. Agree where you genuinely agree, "
        "push back where you disagree, and add new dimensions to the discussion. "
        "Be direct and substantive."
    )


def build_summary_prompt(topic, history):
    return (
        f"The following is a multi-round discussion between AI models "
        f"on this topic: \"{topic}\"\n\n"
        f"{format_history(history)}"
        "Please provide:\n"
        "1. A concise summary of the key points raised across the discussion\n"
        "2. Areas of consensus or agreement between the models\n"
        "3. Areas of disagreement or differing perspectives\n"
        "4. A synthesized consensus answer to the original topic, where possible\n\n"
        "Be direct and concise."
    )


def call_claude(prompt):
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            timeout=API_TIMEOUT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"[Claude error: {str(e)}]"


def call_chatgpt(prompt):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1000,
            timeout=API_TIMEOUT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[ChatGPT error: {str(e)}]"


def call_gemini(prompt):
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=4000,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return response.text
    except Exception as e:
        return f"[Gemini error: {str(e)}]"


MODEL_DISPATCH = {
    "claude": ("Claude", call_claude),
    "chatgpt": ("ChatGPT", call_chatgpt),
    "gemini": ("Gemini", call_gemini),
}


def run_discussion(topic, rounds, models):
    history = []

    # Round 0: each model answers independently
    for model_key in models:
        model_name, call_fn = MODEL_DISPATCH[model_key]
        prompt = build_initial_prompt(topic)
        text = call_fn(prompt)
        history.append({"model": model_name, "round": 0, "text": text})

    # Rounds 1+: each model sees prior responses
    for round_num in range(1, rounds + 1):
        for model_key in models:
            model_name, call_fn = MODEL_DISPATCH[model_key]
            prompt = build_followup_prompt(topic, history, model_name)
            text = call_fn(prompt)
            history.append({"model": model_name, "round": round_num, "text": text})

    # Summary: use Claude if available, otherwise first selected model
    summary_fn = call_claude if "claude" in models else MODEL_DISPATCH[models[0]][1]
    summary_text = summary_fn(build_summary_prompt(topic, history))

    return history, summary_text


def build_followup_initial_prompt(topic, original_history, prior_followups, question, model_name):
    context = f"Original Topic: {topic}\n\nOriginal Discussion:\n{format_history(original_history)}"
    for i, fu in enumerate(prior_followups, 1):
        context += f"---\nFollow-up {i}: {fu['question']}\n\n{format_history(fu['discussion'])}"
    return (
        f"You are {model_name} in a structured discussion. Here is the full context:\n\n"
        f"{context}---\n"
        f"The user has a follow-up question: {question}\n\n"
        "Please respond to this follow-up, drawing on the full discussion above. Be substantive and direct."
    )


def build_followup_round_prompt(topic, original_history, prior_followups, question, followup_history, model_name):
    context = f"Original Topic: {topic}\n\nOriginal Discussion:\n{format_history(original_history)}"
    for i, fu in enumerate(prior_followups, 1):
        context += f"---\nFollow-up {i}: {fu['question']}\n\n{format_history(fu['discussion'])}"
    return (
        f"You are {model_name} in a follow-up discussion. Full context:\n\n"
        f"{context}---\n"
        f"Follow-up Question: {question}\n\n"
        f"Follow-up discussion so far:\n{format_history(followup_history)}\n"
        "Respond to the other models' points. Agree where you genuinely agree, push back where you disagree. Be direct."
    )


def run_followup(topic, original_history, prior_followups, question, rounds, models):
    followup_history = []

    for model_key in models:
        model_name, call_fn = MODEL_DISPATCH[model_key]
        prompt = build_followup_initial_prompt(topic, original_history, prior_followups, question, model_name)
        text = call_fn(prompt)
        followup_history.append({"model": model_name, "round": 0, "text": text})

    for round_num in range(1, rounds + 1):
        for model_key in models:
            model_name, call_fn = MODEL_DISPATCH[model_key]
            prompt = build_followup_round_prompt(topic, original_history, prior_followups, question, followup_history, model_name)
            text = call_fn(prompt)
            followup_history.append({"model": model_name, "round": round_num, "text": text})

    # Summary covering the full conversation
    all_history = list(original_history)
    for fu in prior_followups:
        all_history.extend(fu["discussion"])
    all_history.extend(followup_history)

    all_questions = [fu["question"] for fu in prior_followups] + [question]
    summary_topic = f"{topic} (follow-ups: {'; '.join(all_questions)})"
    summary_fn = call_claude if "claude" in models else MODEL_DISPATCH[models[0]][1]
    summary_text = summary_fn(build_summary_prompt(summary_topic, all_history))

    return followup_history, summary_text


@app.route("/followup", methods=["POST"])
def followup():
    data = request.get_json()
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Follow-up question is required"}), 400
    if len(question) > MAX_TOPIC_LENGTH:
        return jsonify({"error": f"Question must be {MAX_TOPIC_LENGTH} characters or fewer"}), 400

    topic = data.get("topic", "")
    original_history = data.get("discussion", [])
    prior_followups = data.get("followups", [])
    models = data.get("models", ["claude", "chatgpt", "gemini"])

    try:
        rounds = int(data.get("rounds", 1))
    except (ValueError, TypeError):
        return jsonify({"error": "Rounds must be a number"}), 400
    rounds = max(1, min(3, rounds))

    valid_models = [m for m in models if m in MODEL_DISPATCH]
    if not valid_models:
        return jsonify({"error": "At least one valid model must be selected"}), 400

    followup_history, summary = run_followup(
        topic, original_history, prior_followups, question, rounds, valid_models
    )

    return jsonify({
        "question": question,
        "discussion": followup_history,
        "summary": summary,
    })


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/discuss", methods=["POST"])
def discuss():
    data = request.get_json()
    topic = data.get("topic", "").strip()

    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    if len(topic) > MAX_TOPIC_LENGTH:
        return jsonify({"error": f"Topic must be {MAX_TOPIC_LENGTH} characters or fewer"}), 400

    try:
        rounds = int(data.get("rounds", 2))
    except (ValueError, TypeError):
        return jsonify({"error": "Rounds must be a number"}), 400
    rounds = max(1, min(3, rounds))

    models = data.get("models", ["claude", "chatgpt", "gemini"])
    valid_models = [m for m in models if m in MODEL_DISPATCH]
    if not valid_models:
        return jsonify({"error": "At least one valid model must be selected"}), 400

    discussion, summary = run_discussion(topic, rounds, valid_models)
    return jsonify({
        "discussion": discussion,
        "summary": summary,
        "topic": topic,
        "timestamp": datetime.now(datetime.UTC).isoformat(),
    })


@app.route("/save", methods=["POST"])
def save():
    data = request.get_json()
    timestamp = datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"discussion_{timestamp}.json"
    filepath = os.path.join(DISCUSSIONS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return jsonify({"filename": filename})


@app.route("/history")
def history():
    files = []
    for fname in sorted(os.listdir(DISCUSSIONS_DIR), reverse=True):
        if fname.endswith(".json"):
            fpath = os.path.join(DISCUSSIONS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                files.append({
                    "filename": fname,
                    "topic": data.get("topic", "Unknown"),
                    "timestamp": data.get("timestamp", ""),
                })
            except Exception:
                pass
    return jsonify(files)


@app.route("/history/<filename>")
def history_file(filename):
    safe_name = os.path.basename(filename)
    fpath = os.path.join(DISCUSSIONS_DIR, safe_name)
    if not os.path.exists(fpath):
        return jsonify({"error": "Not found"}), 404
    with open(fpath, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/stop", methods=["POST"])
def stop():
    os.kill(os.getpid(), signal.SIGTERM)
    return jsonify({"status": "stopping"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
