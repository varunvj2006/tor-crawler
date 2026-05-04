import base64
import hashlib
import json
import math
import os
import random
import re
import threading
import time
import urllib.parse
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib.parse import quote_plus
from urllib3.util.retry import Retry

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

# ==============================
# CONFIG
# ==============================
MAX_PAGES = int(os.environ.get("MAX_PAGES", "120"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
SEED_WORKERS = int(os.environ.get("SEED_WORKERS", "4"))

DELAY_MIN = float(os.environ.get("DELAY_MIN", "0.5"))
DELAY_MAX = float(os.environ.get("DELAY_MAX", "1.5"))

SIM_THRESHOLD = float(os.environ.get("SIM_THRESHOLD", "0.40"))
REVIEW_THRESHOLD = float(os.environ.get("REVIEW_THRESHOLD", "0.34"))

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "180"))
MIN_CHUNK_WORDS = int(os.environ.get("MIN_CHUNK_WORDS", "25"))
MAX_CHUNKS_PER_PAGE = int(os.environ.get("MAX_CHUNKS_PER_PAGE", "12"))
MAX_CHUNKS_TO_SCORE = int(os.environ.get("MAX_CHUNKS_TO_SCORE", "40"))
CONTEXT_NEIGHBORS = int(os.environ.get("CONTEXT_NEIGHBORS", "1"))

REQUEST_TIMEOUT_CONNECT = int(os.environ.get("REQUEST_TIMEOUT_CONNECT", "15"))
REQUEST_TIMEOUT_READ = int(os.environ.get("REQUEST_TIMEOUT_READ", "30"))

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "crawler_runs"))
CRAWLER_PROMPT = os.environ.get("CRAWLER_PROMPT", "").strip()
query_input = CRAWLER_PROMPT if CRAWLER_PROMPT else input("Enter search prompt: ").strip()
query_lc = query_input.lower().strip() or "secure boot"
query_input = query_input or query_lc

# Save mainly/only when prompt appears.
# Default is strict because that is what you asked for.
REQUIRE_PROMPT_MATCH = os.environ.get("REQUIRE_PROMPT_MATCH", "1") == "1"

USE_FIXED_SEEDS = os.environ.get("USE_FIXED_SEEDS", "1") == "1"
USE_KERNEL_SEEDS = os.environ.get("USE_KERNEL_SEEDS", "1") == "1"
USE_DUCKDUCKGO = os.environ.get("USE_DUCKDUCKGO", "1") == "1"
USE_BING_FALLBACK = os.environ.get("USE_BING_FALLBACK", "1") == "1"
SEARCH_MAX_RESULTS = int(os.environ.get("SEARCH_MAX_RESULTS", "40"))
ALLOW_SEARCH_EXTERNAL_DOMAINS = os.environ.get("ALLOW_SEARCH_EXTERNAL_DOMAINS", "1") == "1"

# Embeddings are optional now.
# If Ollama is down, the crawler automatically uses lexical scoring.
USE_OLLAMA = os.environ.get("USE_OLLAMA", "1") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

USE_TOR = os.environ.get("USE_TOR", "0") == "1"
TOR_PROXY = os.environ.get("TOR_PROXY", "socks5h://127.0.0.1:9050")

print(f"Searching for: {query_input}", flush=True)
print(f"Require prompt match: {REQUIRE_PROMPT_MATCH}", flush=True)
print(f"Use fixed seeds: {USE_FIXED_SEEDS}", flush=True)
print(f"Use kernel seeds: {USE_KERNEL_SEEDS}", flush=True)


DEFAULT_ALLOWED_DOMAINS = {
    "docs.kernel.org",
    "developer.arm.com",
    "community.st.com",
    "www.st.com",
    "www.nxp.com",
    "www.ti.com",
    "interrupt.memfault.com",
    "wiki.osdev.org",
    "trustedfirmware.org",
    "docs.zephyrproject.org",
    "docs.mcuboot.com",
    "docs.u-boot.org",
    "source.android.com",
    "www.freertos.org",
    "zephyr-docs.listenai.com",
}

EXTRA_ALLOWED_DOMAINS = {
    d.strip().lower()
    for d in os.environ.get("EXTRA_ALLOWED_DOMAINS", "").split(",")
    if d.strip()
}

ALLOWED_DOMAINS = DEFAULT_ALLOWED_DOMAINS | EXTRA_ALLOWED_DOMAINS

START_URLS = [
    "https://docs.kernel.org/",
    "https://docs.kernel.org/admin-guide/",
    "https://docs.kernel.org/devicetree/",
    "https://developer.arm.com/documentation/",
    "https://trustedfirmware.org/",
    "https://docs.zephyrproject.org/latest/",
    "https://docs.mcuboot.com/",
    "https://interrupt.memfault.com/",
    "https://community.st.com/",
    "https://docs.u-boot.org/",
    "https://source.android.com/",
]

KERNEL_SEARCH_URLS = [
    "https://docs.kernel.org/search.html?q={query}",
    "https://docs.kernel.org/admin-guide/",
    "https://docs.kernel.org/devicetree/",
    "https://docs.kernel.org/security/",
    "https://docs.kernel.org/driver-api/",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X)",
]

GENERIC_SECURITY_TERMS = [
    "documentation", "datasheet", "manual", "firmware", "driver",
    "embedded", "security", "secure boot", "bootloader", "flash",
    "uart", "jtag", "swd", "spi", "i2c", "debug", "root of trust",
    "signature", "certificate", "attestation", "trustzone", "tee",
]

TECHNICAL_SIGNALS = [
    "0x", "->", "::", "()", "{", "}", ";", "register", "api",
    "driver", "firmware", "bootloader", "console", "uart", "jtag",
    "swd", "spi", "i2c", "flash", "rom", "soc", "datasheet",
]

QUERY_TEMPLATE = """
{user_topic}
{user_topic} documentation
{user_topic} datasheet
{user_topic} firmware
{user_topic} driver
{user_topic} security
{user_topic} embedded
hardware security embedded systems firmware secure boot bootloader
uart jtag swd spi i2c flash rom debug datasheet documentation
"""
QUERY_TEXT = QUERY_TEMPLATE.format(user_topic=query_lc).strip()

thread_local = threading.local()


def get_headers() -> dict:
    return {"User-Agent": random.choice(USER_AGENTS)}


def create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=30, pool_maxsize=30)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    if USE_TOR:
        session.proxies.update({"http": TOR_PROXY, "https": TOR_PROXY})

    return session


def get_session() -> requests.Session:
    if not hasattr(thread_local, "session"):
        thread_local.session = create_session()
    return thread_local.session


print(f"Using Tor proxy: {TOR_PROXY}" if USE_TOR else "Using direct connection (Tor disabled)", flush=True)


_embedding_cache: Dict[str, np.ndarray] = {}
_embedding_lock = threading.Lock()
OLLAMA_AVAILABLE = False
QUERY_EMBED = None


def check_ollama() -> bool:
    if not USE_OLLAMA:
        print("Ollama disabled. Using lexical scoring.", flush=True)
        return False

    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        print("Available Ollama models:", models[:20], flush=True)

        if not any(EMBED_MODEL in m for m in models):
            print(f"Model '{EMBED_MODEL}' is not installed. Using lexical scoring.", flush=True)
            print(f"Optional fix: ollama pull {EMBED_MODEL}", flush=True)
            return False
        return True
    except Exception as exc:
        print("Could not reach Ollama. Using lexical scoring instead:", exc, flush=True)
        return False


def embed(text: str) -> np.ndarray:
    key = text.strip()

    with _embedding_lock:
        cached = _embedding_cache.get(key)
        if cached is not None:
            return cached

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": key},
            timeout=60,
        )
        if r.ok:
            data = r.json()
            vec = np.array(data["embeddings"][0], dtype=np.float32)
            with _embedding_lock:
                _embedding_cache[key] = vec
            return vec
    except requests.RequestException:
        pass

    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": key},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    vec = np.array(data["embedding"], dtype=np.float32)

    with _embedding_lock:
        _embedding_cache[key] = vec

    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_+.-]+", text.lower())


QUERY_TOKENS = tokenize(QUERY_TEXT)
QUERY_COUNTER = Counter(QUERY_TOKENS)
IMPORTANT_QUERY_TERMS = set(tokenize(query_lc)) | set(tokenize(" ".join(GENERIC_SECURITY_TERMS)))


def lexical_similarity(text: str) -> float:
    """Simple cosine similarity over token counts. Returns roughly 0..1."""
    tokens = tokenize(text)
    if not tokens or not QUERY_COUNTER:
        return 0.0

    counter = Counter(tokens)
    common = set(counter) & set(QUERY_COUNTER)
    dot = sum(counter[t] * QUERY_COUNTER[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in counter.values()))
    norm_b = math.sqrt(sum(v * v for v in QUERY_COUNTER.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    score = dot / (norm_a * norm_b)

    # Small boost for exact important terms.
    important_hits = sum(1 for t in IMPORTANT_QUERY_TERMS if t in counter)
    score += min(important_hits * 0.015, 0.15)

    return min(float(score), 1.0)


def relevance(text: str) -> float:
    if OLLAMA_AVAILABLE and QUERY_EMBED is not None:
        return cosine_similarity(embed(text), QUERY_EMBED)
    return lexical_similarity(text)


OLLAMA_AVAILABLE = check_ollama()
if OLLAMA_AVAILABLE:
    QUERY_EMBED = embed(QUERY_TEXT)
    print(f"Loaded query embedding with model: {EMBED_MODEL}", flush=True)
else:
    print("Loaded lexical scorer. No Ollama required.", flush=True)


def slugify(text: str, max_len: int = 70) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "prompt"


def make_output_paths(prompt: str) -> Tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(prompt)
    run_dir = OUTPUT_DIR / f"{stamp}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "results.jsonl", run_dir / "run_meta.json"


def normalize_url(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href)


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", parsed.params, parsed.query, "")
    )


def prompt_matches(text: str) -> bool:
    return bool(query_lc and query_lc in text.lower())


def is_probably_binary(url: str) -> bool:
    lower = url.lower()
    bad_exts = (
        ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".mp4", ".mp3", ".bin", ".exe", ".dmg", ".iso", ".tar",
        ".gz", ".7z", ".rar"
    )
    return lower.endswith(bad_exts)


def is_low_value_url(url: str) -> bool:
    u = url.lower()
    bad_parts = [
        "/tag", "/tags", "/author", "/authors", "/page/", "/pages/",
        "/category", "/categories", "/archive", "/archives",
        "/login", "/signup", "/register", "/account", "/genindex",
    ]
    return any(part in u for part in bad_parts)


def is_allowed_url(url: str, allow_external: bool = False) -> bool:
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False
    if is_probably_binary(url):
        return False
    if is_low_value_url(url):
        return False
    if allow_external and ALLOW_SEARCH_EXTERNAL_DOMAINS:
        return True

    return parsed.netloc.lower() in ALLOWED_DOMAINS


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return re.sub(r"\s+", " ", title).strip()


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "aside"]):
        tag.extract()

    text = soup.get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, size: int = CHUNK_SIZE) -> List[str]:
    words = text.split()
    return [" ".join(words[i:i + size]).strip() for i in range(0, len(words), size) if words[i:i + size]]


def has_technical_signal(text: str) -> bool:
    t = text.lower()
    return any(signal in t for signal in TECHNICAL_SIGNALS)


def soft_signal_score(text: str, url: str = "", title: str = "") -> float:
    combined = f"{url} {title} {text}".lower()
    score = 0.0

    if prompt_matches(combined):
        score += 0.45

    if has_technical_signal(text):
        score += 0.04

    score += min(sum(term in combined for term in GENERIC_SECURITY_TERMS) * 0.008, 0.04)
    return score


def looks_like_index_page(text: str) -> bool:
    t = text.lower()
    triggers = ["latest posts", "authors", "tags", "categories", "related posts", "quick search", "contents"]
    return sum(trigger in t for trigger in triggers) >= 3


def is_low_value_page(text: str, url: str) -> bool:
    t = text.lower()
    if any(p in t for p in ["privacy policy", "terms of service", "404 not found", "access denied"]):
        return True
    if len(t.split()) < 80:
        return True
    if is_low_value_url(url):
        return True
    return False


def page_quality_score(url: str, title: str, text: str) -> float:
    combined = f"{url} {title} {text}".lower()
    score = 0.0

    if prompt_matches(combined):
        score += 0.50

    if len(text.split()) > 250:
        score += 0.08

    if has_technical_signal(text):
        score += 0.08

    if looks_like_index_page(text):
        score -= 0.25

    return score


def chunk_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def save_result(data: dict, file_handle) -> None:
    file_handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    file_handle.flush()


def build_search_query(user_topic: str) -> str:
    return f'"{user_topic}" OR {user_topic} datasheet documentation firmware driver embedded'


def duckduckgo_seed_urls(user_topic: str, max_results: int) -> List[str]:
    if not USE_DUCKDUCKGO or DDGS is None:
        if DDGS is None:
            print("duckduckgo_search not installed. Skipping DuckDuckGo.", flush=True)
        return []

    query = build_search_query(user_topic)
    print(f"DuckDuckGo search: {query}", flush=True)

    urls = []
    seen = set()

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for result in results:
                url = result.get("href") or result.get("url")
                if not url:
                    continue
                url = canonicalize_url(url)

                if url in seen:
                    continue

                if is_allowed_url(url, allow_external=True):
                    urls.append(url)
                    seen.add(url)
    except Exception as exc:
        print(f"DuckDuckGo search failed: {exc}", flush=True)

    print(f"DuckDuckGo added {len(urls)} seed URLs", flush=True)
    return urls


def decode_bing_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)

        if "u" not in qs:
            return url

        encoded = qs["u"][0]
        if encoded.startswith("a1"):
            encoded = encoded[2:]

        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8", errors="ignore")
        return decoded if decoded.startswith("http") else url
    except Exception:
        return url


def is_bad_search_result(url: str) -> bool:
    u = url.lower()
    domain = urllib.parse.urlparse(u).netloc.lower()

    bad_domains = ["bing.com", "microsoft.com", "go.microsoft.com", "hotukdeals.com"]
    bad_paths = ["/images/search", "/videos/search", "/maps", "/travel", "/news/search", "/search?", "/ck/a"]

    return any(bad in domain for bad in bad_domains) or any(bad in u for bad in bad_paths)


def bing_seed_urls(user_topic: str, max_results: int) -> List[str]:
    if not USE_BING_FALLBACK:
        return []

    query = build_search_query(user_topic)
    print(f"Bing fallback search: {query}", flush=True)

    urls = []
    seen = set()

    try:
        session = get_session()
        search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
        res = session.get(search_url, headers=get_headers(), timeout=(15, 30))
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        candidates = []
        candidates.extend(soup.select("li.b_algo h2 a[href]"))
        candidates.extend(soup.select("h2 a[href]"))

        for anchor in candidates:
            href = anchor.get("href", "").strip()
            if not href.startswith("http"):
                continue

            decoded_url = canonicalize_url(decode_bing_url(href))
            if decoded_url in seen or is_bad_search_result(decoded_url):
                continue

            if is_allowed_url(decoded_url, allow_external=True):
                urls.append(decoded_url)
                seen.add(decoded_url)

            if len(urls) >= max_results:
                break
    except Exception as exc:
        print(f"Bing fallback failed: {exc}", flush=True)

    print(f"Bing added {len(urls)} seed URLs", flush=True)
    return urls


def kernel_seed_urls(user_topic: str) -> List[str]:
    if not USE_KERNEL_SEEDS:
        return []

    print("Kernel docs seed discovery started", flush=True)
    seeds = []
    seen = set()

    for template in KERNEL_SEARCH_URLS:
        url = canonicalize_url(template.format(query=quote_plus(user_topic)))
        if url not in seen:
            seeds.append(url)
            seen.add(url)

    print(f"Kernel seed discovery added {len(seeds)} seed URLs", flush=True)
    return seeds


def fixed_seed_urls() -> List[str]:
    if not USE_FIXED_SEEDS:
        return []
    return [canonicalize_url(url) for url in START_URLS]


def collect_seed_urls() -> List[Tuple[str, bool]]:
    seed_jobs = {
        "fixed": fixed_seed_urls,
        "kernel": lambda: kernel_seed_urls(query_lc),
        "duckduckgo": lambda: duckduckgo_seed_urls(query_lc, SEARCH_MAX_RESULTS),
        "bing": lambda: bing_seed_urls(query_lc, SEARCH_MAX_RESULTS),
    }

    combined = []
    seen = set()

    with ThreadPoolExecutor(max_workers=SEED_WORKERS) as executor:
        futures = {executor.submit(fn): name for name, fn in seed_jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                urls = future.result()
            except Exception as exc:
                print(f"Seed source {name} failed: {exc}", flush=True)
                continue

            for url in urls:
                url = canonicalize_url(url)
                if url in seen:
                    continue

                allow_external_links = name in {"duckduckgo", "bing"}
                combined.append((url, allow_external_links))
                seen.add(url)

    print(f"Total unique seed URLs: {len(combined)}", flush=True)
    return combined


def extract_links(html: str, base: str, allow_external_links: bool = False) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    skip_parts = ["privacy", "terms", "cookie", "login", "signup", "mailto:", "javascript:", "#", "tel:"]

    for anchor_tag in soup.select("a[href]"):
        href = anchor_tag.get("href", "").strip()
        if not href or any(part in href.lower() for part in skip_parts):
            continue

        url = canonicalize_url(normalize_url(base, href))
        if url in seen:
            continue

        if not is_allowed_url(url, allow_external=allow_external_links):
            continue

        anchor = anchor_tag.get_text(" ", strip=True)
        links.append((url, anchor))
        seen.add(url)

    return links


def rank_links(links: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    ranked = []

    for link, anchor in links:
        combined = f"{link} {anchor}".lower()
        score = 0

        if query_lc in combined:
            score += 80

        score += sum(term in combined for term in GENERIC_SECURITY_TERMS)
        score -= sum(term in combined for term in ["index.html", "/index", "/genindex", "/tag", "/category"])
        ranked.append((score, link, anchor))

    ranked.sort(reverse=True, key=lambda item: item[0])
    return [(link, anchor) for _, link, anchor in ranked]


def process_url(url: str, parent_url: str, anchor_text: str, allow_external_links: bool) -> dict:
    print(f"Visiting: {url}", flush=True)

    result = {
        "url": url,
        "records": [],
        "links": [],
        "page_saved": 0,
        "strong_hits": 0,
        "review_hits": 0,
        "quality": 0.0,
        "error": None,
        "allow_external_links": allow_external_links,
    }

    try:
        session = get_session()
        res = session.get(url, headers=get_headers(), timeout=(REQUEST_TIMEOUT_CONNECT, REQUEST_TIMEOUT_READ))
        content_type = res.headers.get("Content-Type", "").lower()

        if res.status_code != 200:
            result["error"] = f"HTTP {res.status_code}"
            return result

        if "text/html" not in content_type:
            result["error"] = "non-HTML content"
            return result

        html = res.text
        title = extract_title(html)
        text = extract_text(html)

        result["links"] = rank_links(extract_links(html, url, allow_external_links=allow_external_links))

        quality = page_quality_score(url, title, text)
        result["quality"] = quality

        page_match_text = f"{url} {title} {text}"
        page_has_prompt = prompt_matches(page_match_text)

        if REQUIRE_PROMPT_MATCH and not page_has_prompt:
            result["error"] = "prompt not found on page"
            return result

        chunks = chunk_text(text)
        if len(chunks) > MAX_CHUNKS_TO_SCORE:
            chunks = chunks[:MAX_CHUNKS_TO_SCORE]

        scored_chunks = []
        chunk_scores = {}

        for i, chunk in enumerate(chunks):
            if len(chunk.split()) < MIN_CHUNK_WORDS:
                continue

            chunk_match_text = f"{url} {title} {chunk}"
            chunk_has_prompt = prompt_matches(chunk_match_text)

            if REQUIRE_PROMPT_MATCH and not chunk_has_prompt:
                continue

            try:
                base_score = relevance(chunk)
            except Exception as exc:
                print(f"  Scoring failed for chunk {i}: {exc}", flush=True)
                continue

            final_score = base_score + soft_signal_score(chunk, url, title) + (0.25 * max(quality, 0.0))
            scored_chunks.append((i, chunk, base_score, final_score))
            chunk_scores[i] = (base_score, final_score)

        strong_hits = [item for item in scored_chunks if item[3] >= SIM_THRESHOLD]
        review_hits = [item for item in scored_chunks if REVIEW_THRESHOLD <= item[3] < SIM_THRESHOLD]

        result["strong_hits"] = len(strong_hits)
        result["review_hits"] = len(review_hits)

        selected_indices = set()

        for i, _, _, _ in sorted(strong_hits, key=lambda item: item[3], reverse=True)[:MAX_CHUNKS_PER_PAGE]:
            start = max(0, i - CONTEXT_NEIGHBORS)
            end = min(len(chunks), i + CONTEXT_NEIGHBORS + 1)
            for j in range(start, end):
                if REQUIRE_PROMPT_MATCH and not prompt_matches(f"{url} {title} {chunks[j]}"):
                    continue
                selected_indices.add(j)

        if not strong_hits and quality >= 0.25 and not is_low_value_page(text, url):
            for i, _, _, _ in sorted(review_hits, key=lambda item: item[3], reverse=True)[:max(2, MAX_CHUNKS_PER_PAGE // 3)]:
                selected_indices.add(i)

        for i in sorted(selected_indices):
            if i not in chunk_scores:
                continue

            chunk = chunks[i]
            base_score, final_score = chunk_scores[i]

            result["records"].append({
                "prompt": query_input,
                "url": url,
                "parent_url": parent_url,
                "anchor_text": anchor_text,
                "title": title,
                "score": round(float(final_score), 4),
                "base_similarity": round(float(base_score), 4),
                "scoring_mode": "ollama" if OLLAMA_AVAILABLE else "lexical",
                "prompt_present": prompt_matches(f"{url} {title} {chunk}"),
                "content": chunk,
            })

        result["page_saved"] = len(result["records"])
        return result

    except Exception as exc:
        result["error"] = str(exc)
        return result


def enqueue_link(link, anchor, parent_url, queue, enqueued, allow_external, allow_external_links=False):
    if link in enqueued:
        return

    if not is_allowed_url(link, allow_external=allow_external):
        return

    queue.append((link, parent_url, anchor, allow_external_links))
    enqueued.add(link)


def main() -> None:
    print("\nStarting crawl...\n", flush=True)

    output_file, meta_file = make_output_paths(query_input)
    print(f"Output file: {output_file}", flush=True)
    print(f"Meta file: {meta_file}", flush=True)

    priority_queue = deque()
    normal_queue = deque()

    enqueued = set()
    visited = set()
    saved_chunk_hashes = set()

    page_count = 0
    results_saved = 0

    seed_urls = collect_seed_urls()

    for url, allow_external_links in seed_urls:
        enqueue_link(
            url,
            "seed",
            "",
            normal_queue,
            enqueued,
            allow_external=True,
            allow_external_links=allow_external_links,
        )

    if not normal_queue and not priority_queue:
        print("No seed URLs found. Try a broader prompt or set USE_FIXED_SEEDS=1.", flush=True)
        return

    start_time = datetime.now().isoformat(timespec="seconds")

    with open(output_file, "w", encoding="utf-8") as f_out:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}

            while (priority_queue or normal_queue or futures) and page_count < MAX_PAGES:
                while len(futures) < MAX_WORKERS and (priority_queue or normal_queue) and page_count + len(futures) < MAX_PAGES:
                    if priority_queue:
                        url, parent_url, anchor_text, allow_external_links = priority_queue.popleft()
                    else:
                        url, parent_url, anchor_text, allow_external_links = normal_queue.popleft()

                    if url in visited:
                        continue

                    visited.add(url)

                    if is_low_value_url(url):
                        print(f"Skipped low-value URL: {url}", flush=True)
                        continue

                    future = executor.submit(process_url, url, parent_url, anchor_text, allow_external_links)
                    futures[future] = (url, parent_url, anchor_text, allow_external_links)

                if not futures:
                    break

                for future in as_completed(list(futures.keys()), timeout=None):
                    url, parent_url, anchor_text, allow_external_links = futures.pop(future)

                    try:
                        result = future.result()
                    except Exception as exc:
                        print(f"Failed {url}: {exc}", flush=True)
                        continue

                    page_count += 1

                    if result["error"]:
                        print(f"  Skipped {url}: {result['error']}", flush=True)
                    else:
                        page_saved = 0

                        for record in result["records"]:
                            sig = chunk_hash(f"{record['url']}::{record['title']}::{record['content']}")
                            if sig in saved_chunk_hashes:
                                continue

                            save_result(record, f_out)
                            saved_chunk_hashes.add(sig)
                            results_saved += 1
                            page_saved += 1

                        high_priority = result["strong_hits"] >= 1 or page_saved >= 1 or result["quality"] >= 0.40

                        for link, link_anchor in reversed(result["links"]):
                            if link in visited:
                                continue

                            target_queue = priority_queue if high_priority else normal_queue
                            enqueue_link(
                                link,
                                link_anchor,
                                url,
                                target_queue,
                                enqueued,
                                allow_external=result["allow_external_links"],
                                allow_external_links=result["allow_external_links"],
                            )

                        print(
                            f"  Quality={result['quality']:.3f} "
                            f"StrongHits={result['strong_hits']} "
                            f"ReviewHits={result['review_hits']} "
                            f"Saved={page_saved}",
                            flush=True,
                        )

                    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                    break

    finished_time = datetime.now().isoformat(timespec="seconds")

    meta = {
        "prompt": query_input,
        "started_at": start_time,
        "finished_at": finished_time,
        "output_file": str(output_file),
        "pages_crawled": page_count,
        "total_chunks_saved": results_saved,
        "require_prompt_match": REQUIRE_PROMPT_MATCH,
        "max_pages": MAX_PAGES,
        "max_workers": MAX_WORKERS,
        "seed_workers": SEED_WORKERS,
        "scoring_mode": "ollama" if OLLAMA_AVAILABLE else "lexical",
        "ollama_url": OLLAMA_URL,
        "embed_model": EMBED_MODEL if OLLAMA_AVAILABLE else None,
        "allowed_domains": sorted(ALLOWED_DOMAINS),
    }

    with open(meta_file, "w", encoding="utf-8") as f_meta:
        json.dump(meta, f_meta, ensure_ascii=False, indent=2)

    print(f"\nCrawl finished. Pages crawled: {page_count}", flush=True)
    print(f"Total chunks saved: {results_saved}", flush=True)
    print(f"Saved results to: {output_file}", flush=True)
    print(f"Saved run metadata to: {meta_file}", flush=True)


if __name__ == "__main__":
    main()
