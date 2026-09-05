"""
Clearance Check Agent - ADK agent definition.

This is the agentic version of the clearance-check pipeline. Instead of a
fixed sequence (extract everything -> research everything -> summarize
everything), this agent reads the script itself and DECIDES which mentions
are actually worth researching, using its own judgment - that's the real
difference between "an LLM pipeline" and "an agent."

The agent's report is structured JSON (not free text) so a future UI can:
  - Show which mentions were researched vs. skipped, and WHY each was
    skipped (the "fail logic" / reasoning requirement)
  - Offer a "check this anyway" button on skipped mentions, which calls
    rerun_mention() below to research just that one mention on demand,
    without re-running the whole agent over the full script again

Runs on Google Cloud (Gemini Enterprise Agent Platform, formerly Vertex AI)
via Application Default Credentials - same setup as main.py.
"""

import json
import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agent_tools import research_clearance_risk
from main import get_gemini_client, call_gemini_with_retry, load_script_text

load_dotenv()

# ADK reads these automatically to authenticate against Google Cloud
# (Gemini Enterprise Agent Platform) instead of an AI Studio API key.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
# GOOGLE_CLOUD_PROJECT must already be set in .env

APP_NAME = "clearance_check_agent"
USER_ID = "local_user"


AGENT_INSTRUCTION = """You are a production legal assistant that reviews
film and TV scripts for clearance-relevant real-world mentions before
filming or release.

Your job, given a script:

1. Read through the script carefully and identify every SPECIFIC real-world
   brand, product, song title, real person's name, or specific real
   location mentioned. Ignore generic or fictional things (e.g. "a phone",
   "a coffee shop", a made-up character name).

2. For each specific real-world mention you find, use your own judgment to
   decide whether it's actually worth researching. Use the
   research_clearance_risk tool ONLY for mentions that seem genuinely
   worth checking - for example:
     - Named brands or products (e.g. "iPhone", "Starbucks")
     - Copyrighted songs or titles (e.g. "Bohemian Rhapsody")
     - Real, identifiable people (e.g. a named celebrity or public figure)
     - Specific real locations that carry trademark/permit implications

   SKIP researching mentions that are too generic, incidental, or
   obviously low-risk to be worth a research call - for example, a passing
   mention of a common city name with no other context, or a very famous
   public-domain-adjacent term. Use your judgment; you do not need to
   research every single real-world word you find. Skipping low-risk
   mentions is a GOOD thing - it shows good judgment, not laziness.

3. For each mention you DID research, write a short, clear risk note
   (3-5 sentences) covering: whether this looks like it needs formal
   clearance, any relevant precedent found in the research, and a
   recommended next step (e.g. "consult legal", "likely fine to use",
   "seek licensing").

4. For each mention you SKIPPED, write a brief, specific reason why it
   didn't need research (e.g. "generic location with no distinguishing
   detail", "purely incidental background mention", "not a protected/
   trademarked term"). Do not just say "low risk" - explain WHY briefly.

5. Respond with ONLY valid JSON (no markdown fences, no extra text)
   matching this exact structure:

{
  "mentions": [
    {
      "mention": "the exact mention text",
      "status": "researched",
      "risk_note": "the risk note text"
    },
    {
      "mention": "the exact mention text",
      "status": "skipped",
      "reason": "brief specific reason it was skipped"
    }
  ]
}

Every mention must have "mention" and "status" ("researched" or "skipped").
Researched mentions must have "risk_note". Skipped mentions must have
"reason". Do not include any text outside this JSON object.
"""


root_agent = Agent(
    name="clearance_check_agent",
    model="gemini-3.5-flash",
    instruction=AGENT_INSTRUCTION,
    description=(
        "Reviews film/TV scripts for real-world clearance-relevant "
        "mentions, researches the ones that matter, and produces a "
        "clearance risk report."
    ),
    tools=[research_clearance_risk],
)


def _parse_agent_report(raw_text: str) -> list[dict]:
    """
    Parses the agent's JSON report into a Python list. Strips markdown
    code fences if the model added them despite instructions not to,
    since LLMs sometimes do this anyway.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        return parsed.get("mentions", [])
    except json.JSONDecodeError:
        # If parsing fails, return the raw text as a single fallback
        # entry so the caller doesn't crash - a UI can display the raw
        # text and the user can still see the agent's output.
        return [{"mention": "PARSE_ERROR", "status": "error", "reason": raw_text}]


async def run_clearance_check(script_text: str) -> list[dict]:
    """
    Runs the clearance check agent on a given script and returns a
    structured list of mention results (each with "mention", "status",
    and either "risk_note" or "reason"). Handles the ADK session/runner
    boilerplate needed to actually invoke the agent.
    """
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)

    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )

    user_message = types.Content(
        role="user",
        parts=[types.Part(text=f"Here is the script to review:\n\n{script_text}")],
    )

    final_response = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=user_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_response = "".join(
                part.text or "" for part in event.content.parts
            )

    return _parse_agent_report(final_response)


def rerun_mention(mention: str) -> dict:
    """
    Manually researches a single mention that the agent previously chose
    to skip - e.g. a user reviewing the report clicks "check this anyway"
    on a skipped mention. Bypasses the full agent entirely: calls the
    same research tool directly, then synthesizes a risk note, without
    re-reading the whole script or re-running the agent's decision loop.

    This is intentionally a plain function (not an agent call) since
    there's no judgment call to make here - the user has already decided
    this specific mention should be researched.

    Returns a dict in the same shape as a "researched" entry from the
    agent's report, so it can be merged into an existing report.
    """
    tool_result = research_clearance_risk(mention)

    if tool_result["status"] == "error":
        return {
            "mention": mention,
            "status": "error",
            "reason": f"Research failed: {tool_result.get('error_message', 'unknown error')}",
        }

    client = get_gemini_client()
    prompt = f"""You are helping a production legal team do a first-pass
clearance check on a script. Below is web research about a mention of
"{mention}" in the script.

Research findings:
{tool_result['findings']}

Write a short risk note (3-5 sentences) covering:
1. Whether this looks like it needs formal clearance
2. Any relevant precedent found
3. A recommended next step (e.g. "consult legal", "likely fine to use", "seek licensing")
"""

    response = call_gemini_with_retry(client, "gemini-3.5-flash", prompt)

    return {
        "mention": mention,
        "status": "researched",
        "risk_note": response.text,
        "note": "manually researched on user request (originally skipped by agent)",
    }


if __name__ == "__main__":
    import asyncio

    script_text = load_script_text()

    print("Running Clearance Check Agent...\n")
    result = asyncio.run(run_clearance_check(script_text))
    for entry in result:
        print(json.dumps(entry, indent=2))

    # Example of the manual re-run capability (not executed automatically):
    # rerun_result = rerun_mention("New York")
    # print(json.dumps(rerun_result, indent=2))