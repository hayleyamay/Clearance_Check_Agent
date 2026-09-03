"""
ADK tool definitions for the Clearance Check Agent.

This file wraps our existing Parallel research logic as a proper ADK
FunctionTool - meaning it follows ADK's conventions so the agent's LLM can
understand when to call it and what it returns:
  - Descriptive docstring (this becomes the tool's description to the LLM)
  - Dict return type with a "status" key (ADK's preferred pattern)
  - Simple parameter types (just a string)

This is step 2 of the ADK migration: wrap the tool. Step 3 (next session)
is building the actual Agent that decides when to call it.
"""

import os
from dotenv import load_dotenv
from parallel import Parallel

load_dotenv()

PARALLEL_API_KEY = os.environ["PARALLEL_API_KEY"]


def research_clearance_risk(mention: str) -> dict:
    """
    Researches whether a specific real-world brand, song, person, or
    location mentioned in a film/TV script might need legal clearance
    before filming or release.

    Use this tool when you've identified a specific, genuinely real-world
    mention in a script (e.g. a named brand like "Starbucks", a song title
    like "Bohemian Rhapsody", a real person's name, or a specific real
    location) that seems worth checking for trademark, copyright, or
    right-of-publicity risk. Do not use this tool for generic or fictional
    things (e.g. "a coffee shop", "a phone") - only for specific real-world
    entities where clearance could plausibly be an issue.

    Args:
        mention (str): The specific real-world name to research (e.g.
            "Starbucks", "Bohemian Rhapsody", "Elon Musk").

    Returns:
        dict: A dictionary with:
            - "status": "success" or "error"
            - "mention": the mention that was researched
            - "findings": a text summary of real-world sources found
              about clearance/trademark history for this mention
              (empty string if none found or on error)
            - "error_message": present only if status is "error"
    """
    try:
        client = Parallel(api_key=PARALLEL_API_KEY)

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

        findings_lines = []
        for result in search.results:
            findings_lines.append(f"Source: {result.title} ({result.url})")
            for excerpt in result.excerpts:
                findings_lines.append(f"  - {excerpt[:300]}")

        return {
            "status": "success",
            "mention": mention,
            "findings": "\n".join(findings_lines),
        }

    except Exception as e:
        return {
            "status": "error",
            "mention": mention,
            "findings": "",
            "error_message": str(e),
        }