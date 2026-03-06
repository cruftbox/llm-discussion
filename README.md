# LLM Discussion

A locally-hosted web app that poses a question to Claude, ChatGPT, and Gemini simultaneously, then orchestrates a multi-round discussion between them — displayed in a clean, color-coded browser interface. You can control response length, ask follow-up questions, and save discussions locally. After each discussion, Claude generates a summary of key points, areas of consensus, and a synthesized answer.

---

## What This Is

LLM Discussion lets you pick a topic or question, select which AI models participate, choose how many discussion rounds to run, and control response length (Concise, Standard, or Detailed). Watch the three models respond to each other in real time, ask follow-up questions to dig deeper, and save the full conversation locally. When the discussion finishes, a summary card highlights consensus and disagreements across the models.

---

## Prerequisites

**Comfort level:** This app requires some comfort with the command line. You should be able to open a terminal, run Python commands, install packages with `pip`, and edit a plain text file. You do not need to be a developer, but if you have never used a terminal before, you may want to familiarize yourself with the basics first.

**API accounts:** This app calls three external AI services, each of which requires you to create an account, agree to their terms of service, and generate an API key. Each service charges per use (see [Costs](#costs) below). You will need to set up billing for at least one of them before the app will work.

- Python 3.9 or later
- `pip`
- API accounts for:
  - [Anthropic](https://console.anthropic.com) (Claude)
  - [OpenAI](https://platform.openai.com) (ChatGPT)
  - [Google AI Studio](https://aistudio.google.com) (Gemini) — requires billing enabled (see note below)

---

## Installation

1. **Clone the repo**
   ```
   git clone https://github.com/cruftbox/llm-discussion.git
   cd llm-discussion
   ```

2. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

3. **Add your API keys**
   ```
   copy config.example.py config.py
   ```
   Open `config.py` and replace the placeholder values with your actual API keys.

---

## Getting API Keys

| Service | Where to get it |
|---------|----------------|
| Anthropic (Claude) | https://console.anthropic.com → API Keys |
| OpenAI (ChatGPT) | https://platform.openai.com → API Keys |
| Google Gemini (`gemini-2.5-flash`, thinking disabled) | https://aistudio.google.com → Get API Key |

**Note on Gemini billing:** The Gemini API free tier has a quota limit of 0 for `gemini-2.5-flash`. You must enable billing on your Google Cloud project for Gemini calls to succeed. To do this:
1. Go to https://console.cloud.google.com/billing
2. Create or link a billing account to the project associated with your API key

Until billing is enabled, uncheck Gemini in the UI — Claude and ChatGPT will work fine independently.

---

## Running the App

**Windows:** Double-click `start.bat`. A minimized terminal window will open running Flask. The script polls until the server is ready, then opens your browser to `http://localhost:5000` automatically — no more blank page on startup.

**Mac/Linux:**
```
python app.py
```
Then open `http://localhost:5000` in your browser.

---

## Usage

1. Type a topic or question in the text box
2. Select the number of discussion rounds (1–3)
3. Select a **Response length**:
   - **Concise** — 2 to 3 short paragraphs per model
   - **Standard** — default, no length constraint
   - **Detailed** — models are asked to be thorough
4. Check which models you want to include
5. Click **Start Discussion**
6. Wait for all responses (typically 30–90 seconds)
7. A **Summary & Consensus** card will appear at the end with key takeaways
8. Optionally type a follow-up question and click **Ask Follow-up** to continue the discussion — the models will respond with full context of the prior conversation. You can ask multiple follow-ups; each gets fresh round numbering and the summary updates each time
9. Click **Save Discussion** to store the results locally (follow-ups are included)

---

## Costs

Each discussion makes multiple API calls (one per model per round, plus initial responses). Approximate costs per discussion:

- 1 round, 3 models: ~$0.05–$0.10
- 2 rounds, 3 models: ~$0.10–$0.20
- 3 rounds, 3 models: ~$0.20–$0.40

Each follow-up question adds another set of API calls at roughly the same cost as a 1-round discussion. The summary is regenerated after each follow-up, which adds one additional Claude call.

Costs vary based on response length and current API pricing.

---

## Stopping the Server

- Click the **Stop Server** button at the bottom of the app
- Double-click `stop.bat`
- Or close the minimized terminal window

---

## Saved Discussions

Discussions are saved as JSON files in the `discussions/` folder. They are not committed to git (listed in `.gitignore`). Saved files include the full conversation — original discussion, all follow-up questions and responses, and the final summary. You can view and reload past discussions in the **Saved Discussions** panel in the app.

---

## Model Versions & Maintenance

The AI models used by this app change over time. If a model stops working or produces unexpected results, the model name in `app.py` may need to be updated.

### Current models (as of March 2026)

| Model | Variable in `app.py` |
|-------|----------------------|
| Claude | `claude-sonnet-4-20250514` |
| ChatGPT | `gpt-4o` |
| Gemini | `gemini-2.5-flash` |

### Known issues and changes

**Gemini model upgrades require extra care.** Newer Gemini models (2.5+) are "thinking" models — they use internal reasoning tokens that count against the `max_output_tokens` budget. This caused responses to be truncated mid-sentence when the token limit was set to 1000. The fix was to:
1. Disable thinking mode via `ThinkingConfig(thinking_budget=0)` — unnecessary for conversational discussion
2. Raise `max_output_tokens` to 4000

If you upgrade to a newer Gemini model and see truncated responses again, check whether it is a thinking model and apply the same fix.

**`google-generativeai` is deprecated.** The original `google-generativeai` package has been retired. This app uses the replacement `google-genai` package (`from google import genai`). Do not revert to the old package.

### How to update a model

Open `app.py` and change the model string in the relevant `call_*` function:
- `call_claude()` — line ~50
- `call_chatgpt()` — line ~61
- `call_gemini()` — line ~71

Check each provider's documentation for current model names:
- Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
- OpenAI: https://platform.openai.com/docs/models
- Google: https://ai.google.dev/gemini-api/docs/models

---

## Extending to Other LLMs

The app can be extended to support other LLMs with API access — for example, Grok (xAI), Mistral, Cohere, or any model available through OpenRouter. The code is structured to make this straightforward:

- Each model has a single `call_*` function in `app.py` (e.g. `call_claude`, `call_chatgpt`, `call_gemini`)
- Models are registered in the `MODEL_DISPATCH` dictionary with a key, display name, and call function
- The frontend checkboxes are independent of the backend — adding a new model requires a small addition in both `app.py` and `index.html`

**Using an LLM coding agent is recommended for this.** Tools like Claude Code, GitHub Copilot, or ChatGPT can make these changes quickly with minimal effort on your part. Simply describe the model you want to add, paste in the relevant API documentation, and the agent will handle the implementation.

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you'd like to change.

---

## License

MIT
