"""
Rights & Clearance Pre-Check — Day 2.

Day 1 proved the Parallel -> Gemini pipeline works for one hardcoded mention.
Day 2 goal: take a real script snippet, have Gemini extract the clearance-
relevant mentions itself, then run each one through the pipeline and produce
one combined report.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Semaphore
from dotenv import load_dotenv
from parallel import Parallel
from google import genai

load_dotenv()

PARALLEL_API_KEY = os.environ["PARALLEL_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# How many mentions to process at once. Kept low because the Gemini free
# tier only allows 5 requests/minute for this model - going higher just
# means more threads sitting in retry/backoff waiting on quota anyway.
MAX_CONCURRENT_MENTIONS = 2

# Gemini free tier is 5 req/min = roughly 1 request every 12s to stay safe.
# This semaphore-based pacer makes every Gemini call (across all threads)
# wait its turn rather than bursting and immediately hitting 429s.
_gemini_pace_lock = Semaphore(1)
_last_gemini_call_time = [0.0]
MIN_SECONDS_BETWEEN_GEMINI_CALLS = 13


def _wait_for_gemini_turn():
    """
    Global pacer shared across all threads: ensures we never call Gemini
    more often than MIN_SECONDS_BETWEEN_GEMINI_CALLS, no matter how many
    threads are trying to call it at once. This keeps us under the free
    tier's 5-requests-per-minute quota instead of bursting and hitting 429s.
    """
    with _gemini_pace_lock:
        now = time.time()
        elapsed = now - _last_gemini_call_time[0]
        if elapsed < MIN_SECONDS_BETWEEN_GEMINI_CALLS:
            time.sleep(MIN_SECONDS_BETWEEN_GEMINI_CALLS - elapsed)
        _last_gemini_call_time[0] = time.time()


def call_gemini_with_retry(client, model: str, prompt: str, max_attempts: int = 5):
    """
    Wraps a Gemini generate_content call with pacing + retry + backoff.
    Paces every call globally to respect free-tier rate limits, and on
    failure, respects Google's suggested retry delay (from 429 errors)
    rather than guessing our own backoff.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        _wait_for_gemini_turn()
        try:
            return client.models.generate_content(model=model, contents=prompt)
        except Exception as e:
            last_error = e
            # If this was a quota error, Google tells us exactly how long
            # to wait (e.g. "retryDelay": "38s") - use that instead of a
            # fixed backoff so we don't hammer the API while still limited.
            wait_seconds = 3 * attempt
            match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", str(e))
            if match:
                wait_seconds = int(match.group(1)) + 1  # +1s buffer
            print(f"  (Gemini call failed, attempt {attempt}/{max_attempts}: {e})")
            print(f"  (waiting {wait_seconds}s before retry)")
            time.sleep(wait_seconds)
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

# --- Script input --------------------------------------------------------

def load_script_text() -> str:
    """
    Loads the script text to analyze.

    Usage:
        python main.py                  -> uses the built-in sample script
        python main.py path/to/file.txt -> reads and analyzes that file

    Keeping this simple on purpose: plain .txt input only for now. Real
    script formats (.pdf, .fdx) can come later once the core extraction
    is validated against messier real-world text.
    """
    if len(sys.argv) > 1:
        script_path = sys.argv[1]
        if not os.path.exists(script_path):
            print(f"Error: file not found: {script_path}")
            sys.exit(1)
        with open(script_path, "r", encoding="utf-8") as f:
            print(f"Loaded script from: {script_path}\n")
            return f.read()
    else:
        print("No file provided, using built-in sample script.\n")
        print("(Tip: run `python main.py path/to/script.txt` to analyze your own script.)\n")
        return SAMPLE_SCRIPT

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

def process_mention(mention: str) -> tuple[str, str, str]:
    """
    Runs the full research -> synthesis pipeline for a single mention.
    Returns (mention, findings, risk_note) - we keep the raw findings too
    so they can be saved separately for transparency/verification, even
    though the clean risk_note is what's meant for end users to read.
    """
    findings = research_clearance_risk(mention)
    risk_note = summarize_risk(mention, findings)
    return mention, findings, risk_note

# --- Main pipeline --------------------------------------------------------

if __name__ == "__main__":
    script_text = load_script_text()

    print("[1/2] Extracting clearance-relevant mentions from script...\n")
    mentions = extract_mentions(script_text)

    if not mentions:
        print("No clearance-relevant mentions found.")
    else:
        print(f"Found {len(mentions)} mention(s): {mentions}\n")
        print(f"[2/2] Processing all mentions (up to {MAX_CONCURRENT_MENTIONS} at a time)...\n")

        start_time = time.time()
        results = {}  # mention -> {"findings": ..., "risk_note": ...}

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_MENTIONS) as executor:
            futures = {executor.submit(process_mention, m): m for m in mentions}
            for future in as_completed(futures):
                mention = futures[future]
                try:
                    _, findings, risk_note = future.result()
                    results[mention] = {"findings": findings, "risk_note": risk_note}
                    print(f"  Done: {mention}")
                except Exception as e:
                    results[mention] = {"findings": "", "risk_note": f"ERROR processing this mention: {e}"}
                    print(f"  Failed: {mention} ({e})")

        elapsed = time.time() - start_time
        print(f"\nAll mentions processed in {elapsed:.1f}s\n")

        # Preserve original script order in the final report, even though
        # they may have finished out of order.
        report = [f"=== {m} ===\n{results[m]['risk_note']}\n" for m in mentions]

        print("=" * 60)
        print("CLEARANCE PRE-CHECK REPORT")
        print("=" * 60 + "\n")
        print("\n".join(report))

        # --- Save two output files ---------------------------------------
        # 1. clean report: mention -> risk_note only. This is what a real
        #    user (or the future web UI) actually wants to read.
        # 2. detailed report: mention -> findings + risk_note. Kept for
        #    transparency - lets judges/reviewers verify Parallel actually
        #    did real research grounding each note, not just decoration.

        os.makedirs("output", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        clean_report = {m: results[m]["risk_note"] for m in mentions}
        clean_path = f"output/clearance_report_{timestamp}.json"
        with open(clean_path, "w", encoding="utf-8") as f:
            json.dump(clean_report, f, indent=2, ensure_ascii=False)

        detailed_report = {
            m: {"findings": results[m]["findings"], "risk_note": results[m]["risk_note"]}
            for m in mentions
        }
        detailed_path = f"output/clearance_report_detailed_{timestamp}.json"
        with open(detailed_path, "w", encoding="utf-8") as f:
            json.dump(detailed_report, f, indent=2, ensure_ascii=False)

        print(f"\nSaved clean report to: {clean_path}")
        print(f"Saved detailed report (with research findings) to: {detailed_path}")