"""
Rights & Clearance Pre-Check — Day 2.

Day 1 proved the Parallel -> Gemini pipeline works for one hardcoded mention.
Day 2 goal: take a real script snippet, have Gemini extract the clearance-
relevant mentions itself, then run each one through the pipeline and produce
one combined report.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from parallel import Parallel
from google import genai

load_dotenv()

PARALLEL_API_KEY = os.environ["PARALLEL_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# How many mentions to process at once. Higher = faster but more load on
# both APIs (and more chance of hitting the McAfee interception issue on
# many simultaneous connections) - 3 is a reasonable balance.
MAX_CONCURRENT_MENTIONS = 3


def call_gemini_with_retry(client, model: str, prompt: str, max_attempts: int = 5):
    """
    Wraps a Gemini generate_content call with retry + backoff.
    We're seeing intermittent forcibly-closed connections on rapid
    back-to-back calls, so retry with a short pause rather than crashing
    the whole run over a transient network blip.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(model=model, contents=prompt)
        except Exception as e:
            last_error = e
            print(f"  (Gemini call failed, attempt {attempt}/{max_attempts}: {e})")
            time.sleep(3 * attempt)  # 3s, 6s, 9s, 12s, 15s backoff
    raise last_error

# --- Step 1: Parallel research call -----------------------------------

def research_clearance_risk(mention: str) -> str:
    """
    Given a brand/song/real-person mention pulled from a script,
    ask Parallel to find real-world context on clearance/trademark risk.
    """
    client = Parallel(api_key=PARALLEL_API_KEY)

    # Correct call shape per Parallel docs: client.search(...) is top-level,
    # not client.beta.search(...). objective = natural-language goal,
    # search_queries = 2-3 short keyword queries (no full sentences).
    search = client.search(
        objective=(
            f"Find information about trademark, licensing, or clearance "
            f"issues related to using '{mention}' in a film or TV script. "
            f"Look for precedent cases, lawsuits, or licensing requirements."
        ),
        search_queries=[
            f"{mention} trademark film clearance lawsuit",
            f"{mention} licensing requirements film TV",
        ],
    )

    # Flatten results into a plain-text block we can hand to Gemini.
    findings = []
    for result in search.results:
        findings.append(f"Source: {result.title} ({result.url})")
        for excerpt in result.excerpts:
            findings.append(f"  - {excerpt[:300]}")
    return "\n".join(findings)

# --- Step 1.5: Gemini extraction call -----------------------------------

def extract_mentions(script_text: str) -> list[str]:
    """
    Ask Gemini to read a script snippet and pull out anything that might
    need clearance: real brands/products, real people, song titles, or
    specific real-world locations. Returns a plain list of short strings.
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""You are helping a production legal team scan a script for
anything that might need rights clearance before filming or release.

Read the script snippet below and list every real-world brand, product,
song title, real person's name, or specific real location mentioned.
Ignore generic/fictional things (e.g. "a phone", "a coffee shop") -
only list SPECIFIC real-world things that would need clearance.

Script snippet:
{script_text}

Respond with ONLY a plain list, one item per line, nothing else.
If nothing needs clearance, respond with exactly: NONE
"""

    response = call_gemini_with_retry(client, "gemini-3.6-flash", prompt)
    text = response.text.strip()
    if text == "NONE" or not text:
        return []

    # Split into lines, strip bullets/numbering Gemini might add anyway.
    mentions = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*0123456789. ").strip()
        if cleaned:
            mentions.append(cleaned)
    return mentions

# --- Step 2: Gemini synthesis call --------------------------------------

def summarize_risk(mention: str, research_findings) -> str:
    """
    Feed Parallel's raw findings into Gemini and get back a structured
    plain-English risk note.
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""You are helping a production legal team do a first-pass
clearance check on a script. Below is web research about a mention of
"{mention}" in the script.

Research findings:
{research_findings}

Write a short risk note (3-5 sentences) covering:
1. Whether this looks like it needs formal clearance
2. Any relevant precedent found
3. A recommended next step (e.g. "consult legal", "likely fine to use", "seek licensing")
"""

    response = call_gemini_with_retry(client, "gemini-3.6-flash", prompt)
    return response.text

# --- Sample script snippet (swap this for a real one later) -------------

SAMPLE_SCRIPT = """
INT. COFFEE SHOP - DAY

MAYA sits at a corner table, scrolling on her iPhone. She's playing
"Bohemian Rhapsody" through her earbuds, loud enough that JAKE can hear
it from across the room.

JAKE
Is that Queen? Nice.

MAYA
(not looking up)
Yeah. Anyway - did you see what Elon Musk tweeted this morning?

She takes a sip from a Starbucks cup.
"""

# --- Per-mention pipeline (runs concurrently, one per mention) ---------

def process_mention(mention: str) -> tuple[str, str]:
    """
    Runs the full research -> synthesis pipeline for a single mention.
    Returns (mention, risk_note). Designed to be called from a thread pool
    so multiple mentions can be in-flight at once instead of waiting on
    each other sequentially.
    """
    findings = research_clearance_risk(mention)
    risk_note = summarize_risk(mention, findings)
    return mention, risk_note

# --- Main pipeline --------------------------------------------------------

if __name__ == "__main__":
    print("[1/2] Extracting clearance-relevant mentions from script...\n")
    mentions = extract_mentions(SAMPLE_SCRIPT)

    if not mentions:
        print("No clearance-relevant mentions found.")
    else:
        print(f"Found {len(mentions)} mention(s): {mentions}\n")
        print(f"[2/2] Processing all mentions (up to {MAX_CONCURRENT_MENTIONS} at a time)...\n")

        start_time = time.time()
        results = {}  # mention -> risk_note, filled in as each completes

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_MENTIONS) as executor:
            futures = {executor.submit(process_mention, m): m for m in mentions}
            for future in as_completed(futures):
                mention = futures[future]
                try:
                    _, risk_note = future.result()
                    results[mention] = risk_note
                    print(f"  Done: {mention}")
                except Exception as e:
                    results[mention] = f"ERROR processing this mention: {e}"
                    print(f"  Failed: {mention} ({e})")

        elapsed = time.time() - start_time
        print(f"\nAll mentions processed in {elapsed:.1f}s\n")

        # Preserve original script order in the final report, even though
        # they may have finished out of order.
        report = [f"=== {m} ===\n{results[m]}\n" for m in mentions]

        print("=" * 60)
        print("CLEARANCE PRE-CHECK REPORT")
        print("=" * 60 + "\n")
        print("\n".join(report))