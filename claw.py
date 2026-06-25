"""
Ashby ATS "Claw" Console
------------------------
Answers questions about the Ashby API by:
  1. Fetching Ashby's own AI-agent index (llms.txt) — a maintained list of
     every endpoint with a one-line description and a direct .md doc URL.
  2. Asking an LLM to pick the most relevant endpoint(s) from that index.
  3. Fetching the clean markdown (+ OpenAPI schema) for those endpoints.
  4. Asking the LLM to answer the user's question using only that content.

Why this approach instead of guessing URL slugs:
  Ashby's reference site is a JS-rendered ReadMe.com site, so scraping the
  HTML reference pages directly returns mostly empty nav chrome. Ashby
  publishes a stable, agent-friendly index at /llms.txt specifically to
  avoid this problem — we use it instead of reverse-engineering slugs.

Model backend:
  Uses GitHub Models (gpt-4o-mini) via the OpenAI-compatible endpoint, the
  same pattern as the semantic-kernel travel agent example. This needs a
  fine-grained GitHub PAT with "Models" read access in GITHUB_TOKEN.

  Pass --local to use a local GGUF model via gpt4all instead (no API key
  needed, but much weaker at picking the right endpoint / parsing JSON).
"""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LLMS_TXT_URL = "https://developers.ashbyhq.com/llms.txt"
CACHE_DIR = Path(".cache") / "ashby_docs"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
INDEX_CACHE_PATH = CACHE_DIR / "llms_index.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

MAX_DOCS_PER_QUESTION = 2
DOC_CHAR_LIMIT = 3500  # per doc, when stuffing into the prompt (keeps total request well under the 8000-token model limit)


# ---------------------------------------------------------------------------
# Step 1: Load Ashby's own endpoint index (replaces slug-permutation guessing)
# ---------------------------------------------------------------------------

def fetch_llms_index(force_refresh: bool = False) -> list[dict[str, str]]:
    """
    Returns a list of {"name": ..., "url": ..., "description": ...} for every
    API Reference entry in Ashby's llms.txt. Cached locally so we don't
    re-fetch on every run.
    """
    if INDEX_CACHE_PATH.exists() and not force_refresh:
        return json.loads(INDEX_CACHE_PATH.read_text(encoding="utf-8"))

    resp = requests.get(LLMS_TXT_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    text = resp.text

    # Only parse the "## API Reference" section (skip Guides / Changelog).
    section_match = re.search(
        r"## API Reference\n(.*?)(?=\n## |\Z)", text, flags=re.S
    )
    section = section_match.group(1) if section_match else text

    # Lines look like:
    # - [application.info](https://developers.ashbyhq.com/reference/applicationinfo.md): Fetch application details...
    entries = []
    for line in section.splitlines():
        m = re.match(r"-\s*\[([^\]]+)\]\((https?://\S+?)\)(?::\s*(.*))?", line.strip())
        if not m:
            continue
        name, url, desc = m.group(1), m.group(2), (m.group(3) or "").strip()
        entries.append({"name": name, "url": url, "description": desc})

    INDEX_CACHE_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def cache_path_for_url(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.md"


def fetch_doc_markdown(url: str) -> str:
    """Fetch a single endpoint's .md doc page (clean markdown + OpenAPI json)."""
    cache_path = cache_path_for_url(url)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


# ---------------------------------------------------------------------------
# Step 2: Model backend (GitHub Models by default, local GGUF as a fallback)
# ---------------------------------------------------------------------------

class GitHubModelsBackend:
    """Hosted backend via GitHub Models (OpenAI-compatible endpoint)."""

    def __init__(self, model: str = "gpt-4o-mini"):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError(
                "GITHUB_TOKEN is not set. Create a fine-grained GitHub PAT with "
                "'Models' read permission and put it in your .env file as "
                "GITHUB_TOKEN=... (see https://github.com/settings/personal-access-tokens/new)"
            )
        self.client = OpenAI(
            api_key=token,
            base_url="https://models.inference.ai.azure.com/",
        )
        self.model = model

    def complete(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""


class LocalModelBackend:
    """Local GGUF backend via gpt4all. No network/API key needed, weaker reasoning."""

    def __init__(self):
        from gpt4all import GPT4All  # imported lazily so it's only required with --local

        model_path = self._find_local_model()
        if model_path is None:
            raise RuntimeError(
                "No local model found. Place a GGUF/ggml model in ./models, "
                "~/gpt4all_models/, or ~/.cache/gpt4all/."
            )
        self.gpt = GPT4All(
            model_name=Path(model_path).name,
            model_path=Path(model_path).parent,
            allow_download=False,
        )

    @staticmethod
    def _find_local_model() -> str | None:
        model_dirs = [
            Path("models"),
            Path.home() / "gpt4all_models",
            Path.home() / ".cache" / "gpt4all",
            Path.home() / ".gpt4all",
        ]
        for d in model_dirs:
            if not d.exists():
                continue
            for pattern in ("**/*.gguf", "**/*ggml*.bin", "**/*.bin"):
                for p in d.glob(pattern):
                    if p.is_file() and p.stat().st_size > 0:
                        return str(p)
        return None

    def complete(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n{user}"
        return self.gpt.generate(prompt)


# ---------------------------------------------------------------------------
# Step 3: Endpoint selection (LLM picks from the index, instead of brute force)
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "is", "there", "an", "the", "to", "a", "and", "or", "of", "for", "in",
    "on", "with", "how", "do", "i", "does", "can", "you", "what", "endpoint",
    "endpoints", "api", "request", "method", "call", "use", "add", "get",
}

SHORTLIST_SIZE = 15  # how many candidates to hand to the LLM after pre-filtering


def _keyword_score(entry: dict[str, str], words: set[str]) -> int:
    haystack = f"{entry['name']} {entry['description']}".lower()
    return sum(1 for w in words if w in haystack)


def shortlist_by_keywords(question: str, index: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Cheap, local, no-LLM narrowing step: score every catalog entry by how many
    question keywords it contains, return the top N. This keeps the prompt we
    eventually send to the LLM small enough to fit the model's token limit,
    instead of stuffing all ~200 endpoint descriptions into one request.
    """
    text = re.sub(r"[^\w\s]", " ", question.lower())
    words = {w for w in text.split() if w and w not in STOP_WORDS}
    if not words:
        return index[:SHORTLIST_SIZE]

    scored = [(e, _keyword_score(e, words)) for e in index]
    scored = [pair for pair in scored if pair[1] > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if not scored:
        return []  # nothing matched even loosely; let caller report "no match"
    return [e for e, _ in scored[:SHORTLIST_SIZE]]


def select_relevant_endpoints(
    model, question: str, index: list[dict[str, str]]
) -> list[dict[str, str]]:
    """
    Two-stage selection:
      1. shortlist_by_keywords() narrows ~200 endpoints down to ~15 using
         simple keyword overlap (no LLM call, no token limit risk).
      2. The LLM picks the final 1-3 from that much smaller shortlist.
    This replaces both the old permutation/combination slug-guessing AND
    avoids sending the entire catalog to the model in one request.
    """
    shortlist = shortlist_by_keywords(question, index)
    if not shortlist:
        return []

    catalog_lines = "\n".join(f"- {e['name']}: {e['description'][:200]}" for e in shortlist)

    system = (
        "You select API endpoints from a catalog. Respond with ONLY a JSON "
        "array of endpoint name strings (exact matches from the catalog), "
        f"at most {MAX_DOCS_PER_QUESTION}. No prose, no markdown fences."
    )
    user = (
        f"Catalog of candidate Ashby API endpoints:\n{catalog_lines}\n\n"
        f"Question: {question}\n\n"
        f"Which endpoint(s) (by exact name) are most relevant? "
        f"Return a JSON array of up to {MAX_DOCS_PER_QUESTION} names."
    )

    raw = model.complete(system, user).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()

    try:
        names = json.loads(raw)
        if not isinstance(names, list):
            return []
    except json.JSONDecodeError:
        # Fallback: try to pull quoted strings out of whatever came back
        names = re.findall(r'"([^"]+)"', raw)

    by_name = {e["name"]: e for e in shortlist}
    selected = [by_name[n] for n in names if n in by_name]
    return selected[:MAX_DOCS_PER_QUESTION]


# ---------------------------------------------------------------------------
# Step 4: Answer using only the fetched docs
# ---------------------------------------------------------------------------

def build_answer_prompt(question: str, docs: list[dict[str, str]]) -> tuple[str, str]:
    system = (
        "You are an Ashby API assistant. Use only the Ashby docs text provided. "
        "Answer with: Yes/No (if applicable), the endpoint name, HTTP method, "
        "URL, and required body params. Do not invent fields that aren't in "
        "the provided docs. Do not add unrelated explanation."
    )

    parts = []
    for i, doc in enumerate(docs, start=1):
        parts.append(f"[Document {i}] {doc['url']}\n{doc['text'][:DOC_CHAR_LIMIT]}\n---")
    user = "\n".join(parts) + f"\n\nQuestion: {question}\nAnswer:"
    return system, user


def answer_question(model, index: list[dict[str, str]], question: str) -> str:
    selected = select_relevant_endpoints(model, question, index)
    if not selected:
        return "No matching Ashby endpoint found in the docs index for that question."

    print("\nSelected Ashby endpoints:")
    for item in selected:
        print(f" - {item['name']}: {item['url']}")

    docs = []
    for item in selected:
        try:
            text = fetch_doc_markdown(item["url"])
        except Exception as exc:
            text = f"Could not fetch {item['url']}: {exc}"
        docs.append({"url": item["url"], "text": text})

    system, user = build_answer_prompt(question, docs)
    return model.complete(system, user)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ashby ATS API assistant")
    parser.add_argument(
        "--local", action="store_true",
        help="Use a local GGUF model via gpt4all instead of GitHub Models",
    )
    parser.add_argument(
        "--refresh-index", action="store_true",
        help="Force re-fetch of the Ashby llms.txt endpoint index",
    )
    args = parser.parse_args()

    model = LocalModelBackend() if args.local else GitHubModelsBackend()
    index = fetch_llms_index(force_refresh=args.refresh_index)

    print("Ashby ATS Claw Console Initialized.")
    print(f"Loaded {len(index)} endpoints from Ashby's docs index.")
    print("Type your request below (or type 'quit' to exit):")
    print("-" * 50)

    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input.strip():
            continue

        print("\nClaw thinking...")
        try:
            answer = answer_question(model, index, user_input)
            print(f"\nClaw: {answer}")
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    main()