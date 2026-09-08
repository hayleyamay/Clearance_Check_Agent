"""
Clearance Check Agent - Streamlit web interface.

Minimal web UI wrapping the ADK agent (agent.py): paste or upload a
script, run the agent, see which mentions were flagged vs. clear
(with reasoning), and manually trigger research on any clear mention.
"""

import asyncio
import streamlit as st

from agent import run_clearance_check, rerun_mention

st.set_page_config(page_title="Clearance Check Agent", page_icon="🎬", layout="wide")

# --- Custom styling -------------------------------------------------------
st.markdown(
    """
    <style>
    /* medium blue background for the whole app */
    [data-testid="stAppViewContainer"] {
        background-color: #a8cdef;
    }

    /* Bigger, bold labels for the file uploader and text area
       (2x the default ~14px, but smaller than headers) */
    [data-testid="stWidgetLabel"] p {
        font-size: 1.75rem !important;
        font-weight: 700 !important;
    }

     /* Captions (the descriptive text under the title, etc.) default to
       a light grey - make them black for better readability against
       the blue background */
    [data-testid="stCaptionContainer"] {
        color: #000000 !important;
    }
    [data-testid="stCaptionContainer"] p {
        color: #000000 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎬 Clearance Check Agent")
st.caption(
    "Paste a script below (or upload a .txt file). The agent will identify "
    "real-world brands, songs, people, and locations, decide which ones "
    "are worth researching, and produce a first-pass clearance risk report."
)

# --- Input ------------------------------------------------------------

DEFAULT_SCRIPT = """INT. DOWNTOWN APARTMENT - KITCHEN - MORNING

RENA (28, still in pajamas) stands at the counter, scrolling
her iPhone with one hand while pouring coffee with the other.
A half-eaten bagel sits on a paper towel.

Her roommate, DESH (30), stumbles in, bleary-eyed, wearing a
faded Golden State Warriors t-shirt.

                              DESH
                    Please tell me there's coffee left.

                              RENA
                    (not looking up)
                    Barely. You were out late.

                              DESH
                    The concert ran long. They played
                    "Bohemian Rhapsody" as the encore,
                    and the whole crowd lost it.

Desh grabs a chipped mug from the pantry and pours the last
of the coffee from the pot Rena set down, into it.

                              RENA
                    Of course they did. That's every
                    cover band's encore.

                              DESH
                    It wasn't a cover band, Rena, it was --

He stops, checks his phone, and frowns.

                              DESH (CONT'D)
                    Ugh. Olivia Rodrigo tweeted something
                    about her Daisy Chain Fields festival
                    again. I don't even know why I still
                    have her notifications on.

                              RENA
                    Turn them off, then.

Rena grabs her bag, slings it over one shoulder, and heads
for the door. She pauses, glancing back at the Warriors shirt.

                              RENA (CONT'D)
                    Warriors lost again last night, by
                    the way.

                              DESH
                    What?! Spoil sport!

She smiles, opens the door.

                              RENA
                    I'm grabbing a Dutch Bros on the way
                    in. Want anything?

                              DESH
                    Just what you need. More coffee. But
                    yeah, sure, surprise me.

RENA exits. DESH slumps into a chair, phone still in hand.

                                                  CUT TO:
"""

st.caption(
    "💡 The paste box below has no meaningful length limit — feel free to "
    "paste a full scene or script. File uploads support up to 200MB, far "
    "more than any script will need."
)

uploaded_file = st.file_uploader("Upload a .txt script (optional)", type=["txt"])

if uploaded_file is not None:
    script_text = uploaded_file.read().decode("utf-8")
else:
    script_text = st.text_area(
        "Or paste your full script here:",
        value=DEFAULT_SCRIPT,
        height=350,
    )

run_button = st.button("Run Clearance Check", type="primary")

# --- Session state to persist results across reruns (e.g. after a
# "check anyway" button click, which triggers a Streamlit rerun) --------

if "report" not in st.session_state:
    st.session_state.report = None

if run_button and script_text.strip():
    with st.spinner("Agent is reading the script and researching flagged mentions..."):
        st.session_state.report = asyncio.run(run_clearance_check(script_text))

# --- Display results ----------------------------------------------------

if st.session_state.report:
    flagged_count = sum(1 for m in st.session_state.report if m.get("status") == "researched")
    clear_count = sum(1 for m in st.session_state.report if m.get("status") == "skipped")

    st.divider()
    st.subheader(f"Results: {flagged_count} flagged for review, {clear_count} clear")

    for i, m in enumerate(st.session_state.report, start=1):
        status = m.get("status")

        with st.container(border=True):
            st.markdown(f"### Mention #{i}: {m['mention']}")

            if status == "researched":
                st.markdown("**Status:** 🟠 Flagged for review")
                st.warning(m.get("risk_note", ""))
                if m.get("note"):
                    st.caption(f"ℹ️ {m['note']}")

            elif status == "skipped":
                st.markdown("**Status:** 🟢 Clear")
                st.success(m.get("reason", ""))
                if st.button("Check this anyway", key=f"rerun_{i}_{m['mention']}"):
                    with st.spinner(f"Researching '{m['mention']}'..."):
                        new_result = rerun_mention(m["mention"])
                    st.session_state.report[i - 1] = new_result
                    st.rerun()

            else:  # error / parse failure
                st.markdown("**Status:** ⚠️ Error")
                st.error(m.get("reason", "Unknown error"))

    with st.expander("Raw JSON output"):
        st.json(st.session_state.report)