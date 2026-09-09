# Clearance Check Agent

**Google Cloud Agentic Cinema Hackathon — Parallel Track**

An AI agent that reads a film or TV script, uses its own judgment to decide which real-world mentions (brands, songs, real people, locations) are actually worth a legal clearance check, researches only those using live web data, and produces a clearance risk report — all through a simple web interface.

**🔗 Try it now (no setup required):** https://clearance-check-agent-782258433387.us-central1.run.app

**📂 Repo:** this repository

> The fastest way to evaluate this project is the live link above — it's the actual deployed agent, running on Google Cloud Run, publicly accessible with no login. The "Running it locally" section further down is for inspecting or running the source directly.

---

## The problem

Before a script can be shot, someone has to manually comb through it for anything that might need legal clearance — brand names, song titles, real people, trademarked locations — and research whether each one is actually a risk. It's slow, easy to miss things on, and easy to over-flag things that don't matter.

## What this agent does

You give it a script. It reads the whole thing and, using its own judgment, decides:

- **Which mentions are genuinely worth researching** (a specific trademarked brand, a real person's likeness being portrayed) — for these, it calls a live web-search tool and writes a clearance risk note with real citations and next steps.
- **Which mentions it can safely skip** (a generic city name, a background reference already covered by a related mention) — and it explains *why* it skipped each one, in plain language.
- **A human can override any skip** — if you want a "New York" or a minor name checked anyway, one click reruns the research for just that mention, without re-running the whole script.

This decision-making is the core of the project: an earlier version of this tool researched every single mention unconditionally (a fixed pipeline, not an agent). See `main.py` for the original fixed-pipeline version, kept in the repo for that before/after comparison.

## How it works

```
Script text
    ↓
ADK Agent (Gemini, via Google Cloud) reads the script and decides,
mention by mention: research it, or skip it (with reasoning)
    ↓
For mentions it chooses to research → Parallel Search API tool
(real-time web search for precedent, lawsuits, licensing requirements)
    ↓
Agent synthesizes findings into a structured clearance risk note
    ↓
Streamlit UI displays each mention as Flagged (researched) or
Clear (skipped) — with a "check anyway" override button on skips
```

## Tech stack

- **[Google Gemini](https://ai.google.dev/)** (`gemini-3.5-flash`) — the reasoning model
- **[Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/)** — the agent framework; gives the model real tool-calling judgment instead of a hardcoded sequence
- **Google Cloud / Gemini Enterprise Agent Platform** (formerly Vertex AI) — hosts and authenticates the Gemini calls
- **[Parallel Search API](https://parallel.ai/)** — the partner integration; real-time web research, called live by the agent as a tool
- **[Streamlit](https://streamlit.io/)** — the web interface
- **Docker + Google Cloud Run** — containerized deployment, publicly hosted

## Project structure

| File | What it is |
|---|---|
| `app.py` | **The actual product.** Streamlit web UI — paste or upload a script, run the agent, view results, override skips. |
| `agent.py` | The ADK agent itself — its instructions, its tool, and the async runner that invokes it. |
| `agent_tools.py` | The Parallel Search API wrapped as an ADK-compatible tool the agent can choose to call. |
| `main.py` | The **original fixed pipeline** (extract → research everything → summarize), kept for the agent-vs-pipeline comparison described above. Not part of the deployed app. |
| `sample_script.txt` | An original, non-copyrighted test scene (no real production's script) with realistic brand/song/real-person mentions, used as the default input. |
| `Dockerfile` / `.dockerignore` | Container definition used to deploy to Cloud Run. |
| `requirements.txt` | Python dependencies. |
| `LICENSE` | MIT. |

## Running it locally (optional — for reviewing the source)

*Skip this section if you just want to use the app — the live link above requires nothing.*

**1. Clone and set up a virtual environment**

```bash
git clone <this-repo-url>
cd clearance-check-agent
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Set up Google Cloud credentials**

This project calls Gemini through Google Cloud (not a plain API key). You'll need:

- A Google Cloud project with the Vertex AI / Gemini Enterprise Agent Platform API enabled
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated:
  ```bash
  gcloud init
  gcloud auth application-default login
  ```

**3. Set environment variables**

Create a `.env` file in the project root:

```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_LOCATION=global
PARALLEL_API_KEY=your-parallel-api-key
```

(Get a Parallel key at [platform.parallel.ai](https://platform.parallel.ai).)

**4. Run the app**

```bash
streamlit run app.py
```

This opens the app in your browser at `localhost:8501`. Paste a script, or use the pre-loaded sample, and click **Run Clearance Check**.

**Optional — run the original fixed-pipeline version for comparison:**

```bash
python main.py                     # uses the built-in sample script
python main.py your_script.txt     # analyzes a script file directly
```

## Deploying your own copy

The live version is deployed to Cloud Run directly from source:

```bash
gcloud run deploy clearance-check-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="^:^GOOGLE_CLOUD_PROJECT=your-project-id:PARALLEL_API_KEY=your-key:GOOGLE_GENAI_USE_VERTEXAI=TRUE:GOOGLE_CLOUD_LOCATION=global"
```

(The `^:^` prefix tells `gcloud` to use `:` instead of `,` as the variable separator — needed because Cloud Run's default comma-separated `--set-env-vars` parsing can silently mangle multi-variable values.)

## Testing notes

The extraction and reasoning logic was validated against both:
- An original sample script (`sample_script.txt`, included in this repo)
- A real, messily-formatted screenplay excerpt pulled from [IMSDb](https://imsdb.com) (used locally for testing only — not included in this repo, to respect copyright)

Both tests confirmed the agent handles realistic screenplay formatting (scene numbers, parentheticals, inconsistent spacing) without extraction errors, and that its skip/research decisions hold up on a harder, more varied set of real names.

## What I'd build next

- PDF / `.fdx` script upload support (currently `.txt` only)
- Multi-agent breakdown (a dedicated research agent + a legal-writing agent) rather than one agent doing both
- Persistent report history / exportable PDF reports
- Higher-tier Gemini quota for faster large-script runs

## License

MIT — see `LICENSE`.