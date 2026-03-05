# LLM Discussion

A locally-hosted web app that poses a question to Claude, ChatGPT, and Gemini simultaneously, then orchestrates a multi-round discussion between them — displayed in a clean, color-coded browser interface.

---

## What This Is

LLM Discussion lets you pick a topic or question, select which AI models participate, choose how many discussion rounds to run, and watch the three models respond to each other in real time. Results can be saved locally and revisited via the History panel.

---

## Prerequisites

- Python 3.9 or later
- `pip`
- API accounts for:
  - [Anthropic](https://console.anthropic.com) (Claude)
  - [OpenAI](https://platform.openai.com) (ChatGPT)
  - [Google AI Studio](https://aistudio.google.com) (Gemini)

---

## Installation

1. **Clone the repo**
   ```
   git clone https://github.com/yourusername/llm-discussion.git
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
| Google Gemini | https://aistudio.google.com → Get API Key |

---

## Running the App

**Windows:** Double-click `start.bat`. A minimized terminal window will open running Flask, and your browser will open to `http://localhost:5000` automatically.

**Mac/Linux:**
```
python app.py
```
Then open `http://localhost:5000` in your browser.

---

## Usage

1. Type a topic or question in the text box
2. Select the number of discussion rounds (1–3)
3. Check which models you want to include
4. Click **Start Discussion**
5. Wait for all responses (typically 30–90 seconds)
6. Click **Save Discussion** to store the results locally

---

## Costs

Each discussion makes multiple API calls (one per model per round, plus initial responses). Approximate costs:

- 1 round, 3 models: ~$0.05–$0.10
- 2 rounds, 3 models: ~$0.10–$0.20
- 3 rounds, 3 models: ~$0.20–$0.40

Costs vary based on response length and current API pricing.

---

## Stopping the Server

- Click the **Stop Server** button at the bottom of the app
- Double-click `stop.bat`
- Or close the minimized terminal window

---

## Saved Discussions

Discussions are saved as JSON files in the `discussions/` folder. They are not committed to git (listed in `.gitignore`). You can view past discussions in the **Saved Discussions** panel in the app.

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you'd like to change.

---

## License

MIT
