import os
import io
import json
import base64
import signal
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
import anthropic
import openai
from google import genai
from google.genai import types as genai_types
import config

logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

# Initialize API clients
anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
openai_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

DISCUSSIONS_DIR = os.path.join(os.path.dirname(__file__), "discussions")
os.makedirs(DISCUSSIONS_DIR, exist_ok=True)

MAX_TOPIC_LENGTH = 2000
API_TIMEOUT = 60  # seconds per model call
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}

LENGTH_INSTRUCTIONS = {
    "concise": "\n\nKeep your response concise — 2 to 3 short paragraphs maximum.",
    "standard": "",
    "detailed": "\n\nBe thorough and detailed in your response.",
}


def extract_pdf_text(base64_data):
    from pypdf import PdfReader
    pdf_bytes = base64.b64decode(base64_data)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def validate_attachment(attachment):
    if not attachment:
        return None, None
    mime = attachment.get("mime_type", "")
    data = attachment.get("data", "")
    if mime not in ALLOWED_MIME_TYPES:
        return None, f"Unsupported file type: {mime}"
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None, "Invalid attachment data"
    if len(raw) > MAX_ATTACHMENT_BYTES:
        return None, "Attachment too large (max 20MB)"
    return {"mime_type": mime, "data": data}, None


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


def call_claude(prompt, attachment=None):
    try:
        content = []
        if attachment:
            if attachment["mime_type"] == "application/pdf":
                content.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": attachment["data"]},
                })
            else:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": attachment["mime_type"], "data": attachment["data"]},
                })
        content.append({"type": "text", "text": prompt})
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            timeout=API_TIMEOUT,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    except Exception as e:
        logging.error("Claude API error: %s", e)
        raise


def call_chatgpt(prompt, attachment=None):
    try:
        if attachment:
            if attachment["mime_type"] == "application/pdf":
                pdf_text = extract_pdf_text(attachment["data"])
                msg_content = f"[Attached PDF content]\n{pdf_text}\n\n{prompt}"
            else:
                msg_content = [
                    {"type": "image_url", "image_url": {"url": f"data:{attachment['mime_type']};base64,{attachment['data']}"}},
                    {"type": "text", "text": prompt},
                ]
        else:
            msg_content = prompt
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1000,
            timeout=API_TIMEOUT,
            messages=[{"role": "user", "content": msg_content}],
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error("ChatGPT API error: %s", e)
        raise


def call_gemini(prompt, attachment=None):
    try:
        if attachment:
            contents = [
                genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=attachment["mime_type"],
                        data=base64.b64decode(attachment["data"]),
                    )
                ),
                genai_types.Part(text=prompt),
            ]
        else:
            contents = prompt
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=4000,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return response.text
    except Exception as e:
        logging.error("Gemini API error: %s", e)
        raise


def _call_models_parallel(models, prompts_by_key, round_num, attachment=None):
    """Call models concurrently. prompts_by_key maps model_key -> prompt."""
    results = {}
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {
            executor.submit(MODEL_DISPATCH[model_key][1], prompts_by_key[model_key], attachment): model_key
            for model_key in models
        }
        for future in as_completed(futures):
            model_key = futures[future]
            model_name = MODEL_DISPATCH[model_key][0]
            try:
                results[model_key] = {"model": model_name, "round": round_num, "text": future.result()}
            except Exception as e:
                results[model_key] = {"model": model_name, "round": round_num, "text": str(e), "error": True}
    return results


MODEL_DISPATCH = {
    "claude": ("Claude", call_claude),
    "chatgpt": ("ChatGPT", call_chatgpt),
    "gemini": ("Gemini", call_gemini),
}


def run_discussion(topic, rounds, models, response_length="standard", attachment=None):
    history = []
    length_instr = LENGTH_INSTRUCTIONS.get(response_length, "")

    # Round 0: all models called in parallel (independent prompts), attachment included here only
    initial_prompt = build_initial_prompt(topic) + length_instr
    results = _call_models_parallel(models, {m: initial_prompt for m in models}, round_num=0, attachment=attachment)
    for model_key in models:
        history.append(results[model_key])

    # Rounds 1+: build prompts from snapshot, then call in parallel
    for round_num in range(1, rounds + 1):
        snapshot = list(history)
        prompts = {
            m: build_followup_prompt(topic, snapshot, MODEL_DISPATCH[m][0]) + length_instr
            for m in models
        }
        results = _call_models_parallel(models, prompts, round_num)
        for model_key in models:
            history.append(results[model_key])

    # Summary: use Claude if available, otherwise first selected model
    summary_fn = call_claude if "claude" in models else MODEL_DISPATCH[models[0]][1]
    try:
        summary_text = summary_fn(build_summary_prompt(topic, history))
    except Exception as e:
        logging.error("Summary generation error: %s", e)
        summary_text = f"[Summary generation failed: {e}]"

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


def run_followup(topic, original_history, prior_followups, question, rounds, models, response_length="standard", attachment=None):
    followup_history = []
    length_instr = LENGTH_INSTRUCTIONS.get(response_length, "")

    # Round 0: all models called in parallel, attachment included here only
    prompts = {
        m: build_followup_initial_prompt(topic, original_history, prior_followups, question, MODEL_DISPATCH[m][0]) + length_instr
        for m in models
    }
    results = _call_models_parallel(models, prompts, round_num=0, attachment=attachment)
    for model_key in models:
        followup_history.append(results[model_key])

    # Rounds 1+: build prompts from snapshot, then call in parallel
    for round_num in range(1, rounds + 1):
        snapshot = list(followup_history)
        prompts = {
            m: build_followup_round_prompt(topic, original_history, prior_followups, question, snapshot, MODEL_DISPATCH[m][0]) + length_instr
            for m in models
        }
        results = _call_models_parallel(models, prompts, round_num)
        for model_key in models:
            followup_history.append(results[model_key])

    # Summary covering the full conversation
    all_history = list(original_history)
    for fu in prior_followups:
        all_history.extend(fu["discussion"])
    all_history.extend(followup_history)

    all_questions = [fu["question"] for fu in prior_followups] + [question]
    summary_topic = f"{topic} (follow-ups: {'; '.join(all_questions)})"
    summary_fn = call_claude if "claude" in models else MODEL_DISPATCH[models[0]][1]
    try:
        summary_text = summary_fn(build_summary_prompt(summary_topic, all_history))
    except Exception as e:
        logging.error("Summary generation error: %s", e)
        summary_text = f"[Summary generation failed: {e}]"

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

    attachment, att_err = validate_attachment(data.get("attachment"))
    if att_err:
        return jsonify({"error": att_err}), 400

    response_length = data.get("response_length", "standard")
    followup_history, summary = run_followup(
        topic, original_history, prior_followups, question, rounds, valid_models, response_length, attachment
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

    attachment, att_err = validate_attachment(data.get("attachment"))
    if att_err:
        return jsonify({"error": att_err}), 400

    response_length = data.get("response_length", "standard")
    discussion, summary = run_discussion(topic, rounds, valid_models, response_length, attachment)
    return jsonify({
        "discussion": discussion,
        "summary": summary,
        "topic": topic,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/save", methods=["POST"])
def save():
    data = request.get_json()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
