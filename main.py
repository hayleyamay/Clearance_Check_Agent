"""
Rights & Clearance Pre-Check — Day 1 smoke test.

Goal: prove Parallel (research) -> Gemini (synthesis) pipeline works.
Nothing fancy yet. Hardcoded test input. Just confirm both APIs respond
and that we can pass Parallel's output into Gemini as context.
"""

import os
from dotenv import load_dotenv
from parallel import Parallel
from google import genai

load_dotenv()

PARALLEL_API_KEY = os.environ["PARALLEL_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# --- Step 1: Parallel research call -----------------------------------

def research_clearance_risk(mention: str) -> str:
    """
    Given a brand/song/real-person mention pulled from a script,
    ask Parallel to find real-world context on clearance/trademark risk.
    """
    client = Parallel(api_key=PARALLEL_API_KEY)

    result = client.beta.search(
        objective=(
            f"Find information about trademark, licensing, or clearance "
            f"issues related to using '{mention}' in a film or TV script. "
            f"Look for precedent cases, lawsuits, or licensing requirements."
        ),
        search_queries=[
            f"{mention} trademark film clearance lawsuit",
            f"{mention} licensing requirements film TV use",
        ],
        max_results=5,
    )
    return result

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

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

# --- Smoke test ----------------------------------------------------------

if __name__ == "__main__":
    test_mention = "iPhone"  # swap this for anything - a brand, song title, real person's name

    print(f"\n[1/2] Researching clearance risk for: '{test_mention}'...\n")
    findings = research_clearance_risk(test_mention)
    print("Parallel raw findings:")
    print(findings)

    print(f"\n[2/2] Asking Gemini to synthesize a risk note...\n")
    risk_note = summarize_risk(test_mention, findings)
    print("Gemini risk note:")
    print(risk_note)