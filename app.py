import os
import random
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st
import openai
from PIL import Image, UnidentifiedImageError
from streamlit_mic_recorder import mic_recorder
from PIL import Image

# ----------------------------
# Config
# ----------------------------
APP_DIR = Path(__file__).resolve().parent
IMAGE_DIR = APP_DIR / "image"
ROUNDS = 3

openai.api_key = st.secrets.get("OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY", None)
if not openai.api_key:
    st.error("Missing OPENAI_API_KEY (set it in .streamlit/secrets.toml or env var).")
    st.stop()

# ----------------------------
# Image loading + validation
# ----------------------------
def list_candidate_images(image_dir: Path):
    return sorted(list(image_dir.glob("*.png")) + list(image_dir.glob("*.PNG")))

def is_valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except (UnidentifiedImageError, OSError):
        return False

if not IMAGE_DIR.exists():
    st.error(f"Image folder not found: {IMAGE_DIR}")
    st.stop()

candidates = list_candidate_images(IMAGE_DIR)
valid_images = [p for p in candidates if is_valid_image(p)]

if len(candidates) == 0:
    st.error(f"No .png images found in: {IMAGE_DIR}")
    st.stop()

if len(valid_images) == 0:
    st.error("Found .png files, but none could be opened as images.")
    st.write("Files found:")
    st.code("\n".join(str(p.name) for p in candidates))
    st.stop()

def pick_random_image() -> Path:
    return random.choice(valid_images)

# ----------------------------
# Helpers
# ----------------------------
def speak_text(text: str):
    safe = text.replace("\\", "\\\\").replace("'", "\\'")
    st.components.v1.html(
        f"""
        <script>
          const utterance = new SpeechSynthesisUtterance('{safe}');
          window.speechSynthesis.cancel();
          window.speechSynthesis.speak(utterance);
        </script>
        """,
        height=0,
    )

def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    with NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()
        with open(tmp.name, "rb") as f:
            result = openai.Audio.transcribe("whisper-1", f)
    return result.get("text", "") if isinstance(result, dict) else ""

def get_prompt_text(round_num: int) -> str:
    if round_num == 1:
        return "What else can this be?"
    return "Great job! What else can this be?"

# ----------------------------
# Session state
# ----------------------------
if "round" not in st.session_state:
    st.session_state.round = 1
if "responses" not in st.session_state:
    st.session_state.responses = []
if "spoken_round" not in st.session_state:
    st.session_state.spoken_round = 0
if "last_transcript" not in st.session_state:
    st.session_state.last_transcript = None  # {"round": int, "text": str} | None

# This controls the image for THIS user session.
if "selected_image_path" not in st.session_state:
    st.session_state.selected_image_path = str(pick_random_image())

SELECTED_IMAGE_PATH = Path(st.session_state.selected_image_path)

# ----------------------------
# UI
# ----------------------------
st.title("What Else Can This Be?")

st.write(
    "In this improv game, you’re shown a simple prop and asked: **“What else can this be?”** "
    "Respond with a new use - logic or abstract. "
    "The goal isn’t to be perfect; it’s to answer quickly, accept the prompt, and keep moving without overthinking. "
    "You’ll play for 3 rounds, then you can start over with a new random prop."
)

st.image(str(SELECTED_IMAGE_PATH), width="stretch")

# End screen (combined result)
if st.session_state.round > ROUNDS:
    st.subheader("Your Responses (All Rounds)")
    for item in st.session_state.responses:
        st.write(f"**Round {item['round']}:** {item['response']}")

    if st.button("Start Over"):
        st.session_state.round = 1
        st.session_state.responses = []
        st.session_state.spoken_round = 0
        st.session_state.last_transcript = None
        st.session_state.selected_image_path = str(pick_random_image())
        st.rerun()

    st.stop()

# Round UI
prompt_text = get_prompt_text(st.session_state.round)

st.subheader(f"Round {st.session_state.round} of {ROUNDS}")

AVATAR_IMAGE = Image.open(IMAGE_DIR / "avatar.png")

col_avatar, col_text = st.columns([1, 15], vertical_alignment="center")
with col_avatar:
    st.image(AVATAR_IMAGE, width=72)  # increase/decrease width as desired
with col_text:
    st.markdown(f"**{prompt_text}**")

if st.session_state.spoken_round != st.session_state.round:
    speak_text(prompt_text)
    st.session_state.spoken_round = st.session_state.round

st.write("Click Record to record your response then click Stop to submit for transcription:")

audio = mic_recorder(
    start_prompt="Record",
    stop_prompt="Stop",
    just_once=True,
    key=f"mic_round_{st.session_state.round}",
)

st.write(
    "**Note**: The prop image stays the same during your 3 rounds. "
    "It may change when you click **Start Over** after 3 rounds or when the app/server is restarted."
)

# Show the per-round result area DURING the game (persists via session_state)
st.divider()
st.subheader("Results")

if st.session_state.last_transcript is not None:
    st.success(
        f"Round {st.session_state.last_transcript['round']} transcribed: "
        f"{st.session_state.last_transcript['text']}"
    )

if st.session_state.responses:
    for item in st.session_state.responses:
        st.write(f"**Round {item['round']}:** {item['response']}")
else:
    st.write("No responses yet - record your first answer.")

# When audio arrives, transcribe and store result, then rerun (so it shows in Results so far)
if audio and isinstance(audio, dict) and audio.get("bytes"):
    st.info("Transcribing...")
    try:
        text = transcribe_wav_bytes(audio["bytes"]).strip()
        if not text:
            st.error("Transcription was empty—try again with a clearer recording.")
        else:
            # store so it shows immediately on the next rerun
            st.session_state.last_transcript = {"round": st.session_state.round, "text": text}

            st.session_state.responses.append({"round": st.session_state.round, "response": text})
            st.session_state.round += 1
            st.rerun()
    except Exception as e:
        st.error(f"Transcription error: {e}")