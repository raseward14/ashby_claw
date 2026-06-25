# ashby_claw

Meet Lisa, my personal Ashby API consultant. She answers questions, sends requests, and troubleshoots errors. Uses Microsoft Agent Framework.

•[Ashby Docs: For AI agents. Picked up by web_fetch tool call on https://developers.ashbyhq.com/](https://developers.ashbyhq.com/llms.txt)

•[Meet your agent harness and claw](https://devblogs.microsoft.com/agent-framework/meet-your-agent-harness-and-claw/)

•[Ashby Knowledge Base](https://docs.ashbyhq.com/)

•[Ashby API Documentation](https://developers.ashbyhq.com/)

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/ashby_claw.git
cd ashby_claw
```

### 2. Get an Ashby API key

1. Log in to your Ashby admin account.
2. Go to **Admin → API Keys**.
3. Create a new API key and copy it — you'll need it for `.env` below.
4. By default, a new key has **no permissions**. Check the boxes for whichever modules you want Lisa to be able to read or write (e.g. Candidates, Applications) — otherwise live requests will fail with a `missing_endpoint_permission` error even with a valid key.

### 3. Create a GitHub PAT with Models access

Lisa uses GitHub Models (`gpt-4o-mini`) to reason about which Ashby endpoint answers your question.

1. Go to [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new).
2. Choose **Fine-grained personal access token** (classic tokens don't support this).
3. Under **Account permissions**, set **Models** to **Read-only**.
4. Generate the token and copy it.

### 4. Set up your `.env` file

Create a `.env` file in the project root:

```
GITHUB_TOKEN=your_github_pat_here
ASHBY_API_KEY=your_ashby_api_key_here
```

### 5. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # on macOS/Linux
# venv\Scripts\activate    # on Windows
```

### 6. Install dependencies

```bash
pip3 install openai python-dotenv requests
```

(Optional) If you want to run fully offline with a local model instead of GitHub Models, also install:

```bash
pip3 install gpt4all
```

and place a `.gguf` model file in `./models` or `~/gpt4all_models/`.

### 7. Run Lisa

```bash
python3 claw.py
```

Or, to use a local model instead of GitHub Models:

```bash
python3 claw.py --local
```

## Sample Prompts

Once Lisa is running, try asking things like:

```
You: Is there an endpoint to add a tag to a candidate?
You: How do I create a new candidate?
You: What permission does application.info require?
You: How do I list all open jobs?
You: What fields are required to submit interview feedback?
You: How do I cancel an interview schedule?
```

### Sending live requests

If `ASHBY_API_KEY` is set, Lisa can also turn a question into a real API call against your Ashby workspace — after showing you the exact request and asking for confirmation before anything is sent:

```
You: Add the tag "strong-candidate" to candidate ID abc123
Claw: [answers the question, then asks] Would you like Claw to send this as a live Ashby API request? (y/n)
```

Lisa will refuse to send anything if required fields (like an ID she can't infer from your question) are missing — she'll tell you what's needed so you can rephrase and try again. Nothing is ever sent without an explicit "y" confirmation.

Type `quit` or `exit` to end the session.

## Commands

Run Lisa:

```bash
python3 claw.py
```

Run Lisa (uses local LLM):

```bash
python3 claw.py --local
```

Forces a fresh pull, refreshing cache:

```bash
python3 claw.py --refresh-index
```
