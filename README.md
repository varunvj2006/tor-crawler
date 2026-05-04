AI Semantic Web Crawler 

A semantic crawler for embedded systems and security research that combines search engines, web crawling, and AI embeddings to extract relevant technical content based on a user prompt.

Requirements

Python packages:
pip install requests beautifulsoup4 numpy duckduckgo-search

Ollama (required for embeddings):

ollama pull nomic-embed-text
ollama serve
Usage

Run normally:
python testscraper.py

You will be prompted:

Enter search prompt:
Run with environment variable

Windows PowerShell:
$env:CRAWLER_PROMPT="lc108"
python testscraper.py
Advanced example
$env:CRAWLER_PROMPT="secure boot"
$env:REQUIRE_PROMPT_MATCH="1"
$env:MAX_PAGES="200"
python testscraper.py
Configuration

Environment variables:
CRAWLER_PROMPT → main search term
REQUIRE_PROMPT_MATCH → only save content containing the prompt (0 or 1)
USE_FIXED_SEEDS → crawl known documentation sites (1 or 0)
MAX_PAGES → number of pages to crawl
MAX_WORKERS → number of threads
USE_DUCKDUCKGO → enable DuckDuckGo search
USE_BING_FALLBACK → enable Bing fallback
USE_TOR → enable Tor proxy
Output

Results are saved to:
crawler_data.jsonl

Each line is a JSON object:

{
  "url": "...",
  "title": "...",
  "content": "relevant extracted text..."
}


How It Works
Search engines provide initial seed URLs
Pages are crawled and parsed
Text is extracted and split into chunks
Each chunk is embedded using Ollama
Similarity scoring determines relevance
Only useful chunks are saved
Prompt Behavior

Default mode:

Prompt influences scoring
Allows broader discovery
REQUIRE_PROMPT_MATCH=0

Strict mode:

Only content containing your prompt is saved
REQUIRE_PROMPT_MATCH=1
Known Issues
DuckDuckGo may rate-limit (Bing fallback is used)
Very short prompts can be ambiguous
Some websites block scraping (403 errors)
Occasional SSL issues on certain domains
Tips



If you get no results:

$env:USE_FIXED_SEEDS="1"
Tor Usage (Optional)

Start Tor:
tor

Then run:
$env:USE_TOR="1"
python testscraper.py
