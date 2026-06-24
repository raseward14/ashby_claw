import html
import hashlib
import os
import re
from pathlib import Path
from itertools import permutations, combinations
from dotenv import load_dotenv
import requests
import asyncio

from gpt4all import GPT4All

# 1. Load your local .env file variables
load_dotenv()
ASHBY_API_KEY = os.getenv("ASHBY_API_KEY")

# Local model detection
MODEL_DIRS = [Path("models"), Path.home() / ".cache" / "gpt4all", Path.home() / ".gpt4all"]
DOC_CACHE_DIR = Path(".cache") / "ashby_docs"
DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def find_local_model() -> str | None:
    for d in MODEL_DIRS:
        if not d.exists():
            continue
        for pattern in ("**/*.gguf", "**/*ggml*.bin", "**/*.bin", "**/*.bin.gz", "**/*ggml*"):
            for p in d.glob(pattern):
                if p.is_file() and p.stat().st_size > 0:
                    return str(p)
    return None


def html_to_text(html_content: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", html_content, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def cache_path_for_url(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return DOC_CACHE_DIR / f"{key}.txt"


def fetch_doc_text(url: str) -> str:
    cache_path = cache_path_for_url(url)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    text = html_to_text(response.text)
    cache_path.write_text(text, encoding="utf-8")
    return text


def search_docs_urls(query: str) -> list[dict[str, str]]:
    """
    Generate candidate Ashby endpoint slugs from the query and verify they exist.
    Ashby endpoints follow the pattern: https://developers.ashbyhq.com/reference/{slug}
    where slug is the lowercase method name (e.g., candidateaddtag, applicationfeedbacksubmit).
    """
    if not query.strip():
        return []

    import time
    
    # Extract potential endpoint names from query
    # Remove punctuation and convert to lowercase
    text = re.sub(r"[^\w\s]", " ", query.lower())
    
    # Remove common stop words
    stop_words = {"is", "there", "an", "the", "to", "a", "and", "or", "endpoint", "api", "request", "method", "endpoint"}
    words = [w for w in text.split() if w not in stop_words and w.strip()]
    
    if not words:
        return []
    
    candidates = set()
    
    # Try contiguous subsequences first (most likely to be correct)
    for length in range(min(4, len(words)), 1, -1):  # Start with longest
        for i in range(len(words) - length + 1):
            slug = "".join(words[i:i+length])
            candidates.add(slug)
    
    # Then try permutations of smaller subsets
    for length in range(min(3, len(words)), 1, -1):
        for combo in combinations(words, length):
            for perm in permutations(combo):
                slug = "".join(perm)
                candidates.add(slug)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    results = []
    tested = set()
    
    # Sort candidates by length (longer = more specific = more likely)
    sorted_candidates = sorted(candidates, key=lambda s: (-len(s), s))
    
    for slug in sorted_candidates:
        if slug in tested or len(results) >= 3:
            continue
        tested.add(slug)
        
        url = f"https://developers.ashbyhq.com/reference/{slug}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # Extract title from page
                title_match = re.search(r'<title>([^<]+)</title>', resp.text)
                title = title_match.group(1) if title_match else slug
                results.append({"title": title, "url": url})
            # Small delay to avoid rate limiting
            time.sleep(0.3)
        except Exception:
            pass
    
    return results


class LocalModel:
    def __init__(self, model_path: str):
        self.gpt = GPT4All(model_name=Path(model_path).name, model_path=Path(model_path).parent, allow_download=False)

    def generate(self, prompt: str) -> str:
        return self.gpt.generate(prompt)


def load_local_model() -> LocalModel:
    model_path = find_local_model()
    if model_path is None:
        raise RuntimeError(
            "No local model found. Place a GGUF/ggml model in ./models or ~/.cache/gpt4all/."
        )
    return LocalModel(model_path)


def build_prompt(question: str, docs: list[dict[str, str]]) -> str:
    instructions = (
        "You are an Ashby API assistant. Use only the Ashby docs text below. "
        "Answer with Yes/No, endpoint, HTTP method, and required body params. "
        "Do not invent anything, do not add planning steps, and do not add extra explanation."
    )

    prompt_parts = [instructions, "\n--- Ashby docs context ---\n"]
    for idx, doc in enumerate(docs, start=1):
        prompt_parts.append(f"[Document {idx}] {doc['url']}\n")
        prompt_parts.append(doc["text"][:3000])
        prompt_parts.append("\n---\n")

    prompt_parts.append("\nQuestion: ")
    prompt_parts.append(question)
    prompt_parts.append("\nAnswer:")
    return "\n".join(prompt_parts)


def answer_question(model: LocalModel, question: str) -> str:
    urls = search_docs_urls(question)
    if not urls:
        return "No Ashby docs results found for that query."

    print("\nSelected Ashby docs URLs:")
    for item in urls[:3]:
        title = item.get("title") or "(no title)"
        print(f" - {title}: {item['url']}")

    docs = []
    for item in urls[:3]:
        try:
            text = fetch_doc_text(item["url"])
        except Exception as exc:
            text = f"Could not fetch {item['url']}: {exc}"
        docs.append({"url": item["url"], "text": text})

    prompt = build_prompt(question, docs)
    return model.generate(prompt)


async def main() -> None:
    model = load_local_model()
    print("🤖 Ashby ATS Claw Console Initialized.")
    print("Type your request below (or type 'quit' to exit):")
    print("-" * 50)

    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ["quit", "exit"]:
            break
        if not user_input.strip():
            continue

        print("\nClaw thinking...")
        try:
            answer = answer_question(model, user_input)
            print(f"\nClaw: {answer}")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
