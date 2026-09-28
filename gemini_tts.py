import os
import io
import re
import wave
import sqlite3
import datetime
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from google import genai
from google.genai import types
import uvicorn

app = FastAPI()

# The direct Google SDK needs a real Google AI key. GEMINI_API_KEY in .env now
# points at the 9router gateway (OpenAI-compatible), which Google rejects with
# API_KEY_INVALID — every render then falls back to chatterbox/piper. Prefer
# the Google key from state/secrets.env (mounted via env_file), falling back
# to GEMINI_API_KEY for stations that still keep a Google key there.
API_KEY = os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY") or os.environ.get("GEMINI_API_KEY")

if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    client = None
    print("WARNING: neither GOOGLE_GENERATIVE_AI_API_KEY nor GEMINI_API_KEY is set.")

# Initialize SQLite database for TTS history
DB_PATH = "/state/tts_history.db"

def init_db():
    try:
        # Create directory if it doesn't exist (though /state should be mounted)
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                persona TEXT NOT NULL,
                voice_used TEXT NOT NULL,
                text TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
        print(f"SQLite DB initialized at {DB_PATH}")
    except Exception as e:
        print(f"WARNING: Failed to initialize SQLite DB: {e}")

init_db()

def log_tts_request(persona: str, voice_used: str, text: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.datetime.utcnow().isoformat() + "Z"
        cursor.execute('''
            INSERT INTO history (timestamp, persona, voice_used, text)
            VALUES (?, ?, ?, ?)
        ''', (now, persona, voice_used, text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to log TTS request to SQLite: {e}")

class GeminiSafety(BaseModel):
    harassment: bool = False
    hateSpeech: bool = False
    sexuallyExplicit: bool = False
    dangerousContent: bool = False

class SpeakRequest(BaseModel):
    text: str
    voice: str = ""
    # Delivery directive from the persona's voiceStyle setting. Empty means
    # the built-in SHORT_STYLES entry for that voice.
    style: str = ""
    geminiSafety: GeminiSafety | None = None

# Map personas to 9 distinct Gemini voices (from https://ai.google.dev/gemini-api/docs/speech-generation#voices)
VOICE_MAP = {
    "jax": "Puck",           # Upbeat
    "mia": "Aoede",          # Breezy
    "owen": "Charon",        # Informative
    "chloe": "Leda",         # Youthful
    "roxy": "Despina",       # Smooth
    "leo": "Algieba",        # Smooth
    "zane": "Fenrir",        # Excitable
    "lexi": "Autonoe",       # Bright
    "miles": "Sulafat"       # Warm
}

# Every real Gemini voice name the sidecar accepts verbatim (personas now
# carry these directly). Alias lookup above stays for back-compat with older
# stored values ([voice:] tags, pre-migration slots).
KNOWN_GEMINI_VOICES = {
    "zephyr", "puck", "charon", "kore", "fenrir", "leda", "orus", "aoede",
    "callirrhoe", "autonoe", "enceladus", "iapetus", "umbriel", "algieba",
    "despina", "erinome", "algenib", "rasalgethi", "laomedeia", "alnilam",
    "schedar", "gacrux", "pulcherrima", "achird", "zubenelgenubi",
    "vindemiatrix", "sadachbia", "sadaltager", "sulafat",
}

# Real name -> persona alias, so voice-specific style prompts keep applying
# when the request already names the Gemini voice.
VOICE_TO_PERSONA = {v.lower(): k for k, v in VOICE_MAP.items()}


def resolve_voice(raw: str) -> tuple[str, str]:
    """Return (gemini_voice_name, persona_alias_for_style). Real names pass
    through (case-insensitive); old aliases still map; unknown falls to Puck."""
    key = (raw or "").strip().lower()
    if key in VOICE_MAP:
        return VOICE_MAP[key], key
    if key in KNOWN_GEMINI_VOICES:
        return key.capitalize(), VOICE_TO_PERSONA.get(key, "")
    return "Puck", ""

# Short delivery tones for speech_metadata.style, keyed by persona alias.
# The full STYLE_MAP paragraphs stay for reference; the wire carries only
# these — long character blocks cause voice drift on 3.8 (see prompting guide).
SHORT_STYLES = {
    "jax": "high-energy, upbeat, smiling",
    "mia": "witty, breezy, grounded",
    "owen": "dry, cynical but empathetic",
    "chloe": "dramatic, playful, youthful",
    "roxy": "cool, confident, laid-back, smooth",
    "leo": "charming, sarcastic, smooth",
    "zane": "loud, electric, fast-paced, excitable",
    "lexi": "high-octane, fun, bright club energy",
    "miles": "warm, understated, soft, intimate",
}

# 3.8 TTS reads the transcript verbatim: [...] stage directions would be
# spoken aloud. Vocal bursts convert to the documented angle-bracket tags;
# delivery modifiers fold into speech_metadata.style instead.
VOCAL_BURST_MAP = {
    "laugh": "laugh", "laughing": "laugh", "laughter": "laugh",
    "chuckle": "chuckle", "chuckles": "chuckle", "giggle": "giggle",
    "sigh": "sigh", "sighs": "sigh", "cough": "cough", "breath": "breath",
    "gasp": "gasp", "groan": "groan", "yawn": "yawn", "sneeze": "sneeze",
    "snort": "snort", "sob": "sob", "cry": "cry", "shout": "shout",
    "scream": "scream", "whisper": "whispering", "whispering": "whispering",
    "short pause": "short pause", "long pause": "long pause",
    "uhm": "breath", "sigh.": "sigh",
}
DELIVERY_STYLE_MAP = {
    "sarcasm": "sarcastic", "shouting": "loud", "whispering": "whispered",
    "robotic": "flat and mechanical", "extremely fast": "speaking rapidly",
}

CUE_RE = re.compile(r"\[([^\]\r\n]{1,40})\]")


def split_cues(text: str) -> tuple[str, list[str]]:
    """Pull [...] cues out of a transcript. Returns (clean text, style additions)."""
    styles: list[str] = []

    def _sub(m) -> str:
        body = m.group(1).strip().lower()
        if body in VOCAL_BURST_MAP:
            return f"<{VOCAL_BURST_MAP[body]}>"
        if body in DELIVERY_STYLE_MAP:
            styles.append(DELIVERY_STYLE_MAP[body])
            return ""
        return m.group(0)

    return re.sub(r"\s+", " ", CUE_RE.sub(_sub, text)).strip(), styles


def generate_wav(pcm_data, sample_rate=24000):
    """Wraps raw PCM16 audio data into a valid WAV file in-memory."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    
    return wav_io.getvalue()

@app.get("/health")
def health():
    if not client:
        return Response(content="Missing GEMINI_API_KEY", status_code=503)
    return {"ok": True}

@app.post("/speak")
def speak(req: SpeakRequest):
    if not client:
        return Response(content="Missing API Key", status_code=500)
    
    # Real Gemini names pass through; old persona aliases still map.
    voice_name, voice_alias = resolve_voice(req.voice)

    print(f"Generating TTS for voice: {voice_name} (mapped from {req.voice})")
    
    import time
    
    # Lite first (cheapest): style rides in speech_metadata, never in [...]
    # blocks, which lite would vocalize. Nothing else — pricier models are
    # never worth it.
    models_to_try = [
        "gemini-3.8-flash-lite-tts",
        "gemini-3.8-flash-tts"
    ]
    max_retries = 3
    retry_delay = 20 # Wait 20 seconds between retries for free tier rate limits
    
    STYLE_MAP = {
        "jax": "You are a male Australian radio presenter on Causeway FM. Speak in a high-energy, hopelessly optimistic, and upbeat tone. Always sound like you have a smile on your face and keep the tone authentic to your character.",
        "mia": "You are a female Australian radio presenter on Causeway FM. Speak in a witty, breezy, and grounded tone. Keep the tone authentic to your character.",
        "owen": "You are a male Australian radio presenter on Causeway FM. Speak in a dry, slightly cynical, but empathetic and informative tone. Keep the tone authentic to your character.",
        "chloe": "You are a female Australian radio presenter on Causeway FM. Speak in a dramatic, playful, and youthful tone. Keep the tone authentic to your character.",
        "roxy": "You are a female Australian radio presenter on Causeway FM. Speak in a cool, confident, laid-back, and smooth tone. Keep the tone authentic to your character.",
        "leo": "You are a male Australian radio presenter on Causeway FM. Speak in a charming, slightly sarcastic, and smooth tone. Keep the tone authentic to your character.",
        "zane": "You are a male Australian radio presenter on Causeway FM. Speak in a loud, electric, fast-paced, and highly excitable tone. Keep the tone authentic to your character.",
        "lexi": "You are a female Australian radio presenter on Causeway FM. Speak in a high-octane, fiercely fun, and bright club energy tone. Keep the tone authentic to your character.",
        "miles": "You are a male Australian radio presenter on Causeway FM. Speak in a warm, slightly understated, soft, and intimate late-night tone. Keep the tone authentic to your character.",
    }
    
    # Short delivery tone for speech_metadata.style (real name or alias).
    # 3.8 TTS treats the transcript as verbatim, so delivery rides in style
    # metadata — never in [...] blocks (lite vocalizes those into rambles).
    style_tone = (req.style or "").strip() or SHORT_STYLES.get(voice_alias, "smooth and natural")
    clean_text, cue_styles = split_cues(req.text.strip())
    if cue_styles:
        style_tone = f"{style_tone}, {', '.join(cue_styles)}"
    style_prompt = f"{style_tone}. Sook rhymes with look; sooking rhymes with looking; Launceston sounds like LON ses tun."

    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                # NOTE: the Interactions API accepts no safety params — both
                # safety_settings and safetySettings 400 as unknown, and the
                # Python SDK strips them client-side, so any safety block here
                # would be silently dead. TTS renders under Google defaults.
                # The geminiSafety request field is still accepted (contract)
                # but intentionally unused. Content control lives on the LLM
                # leg (native google provider safetySettings).
                interaction = client.interactions.create(
                    model=model_name,
                    input=[{
                        "type": "user_input",
                        "content": [{
                            "type": "text",
                            "text": clean_text,
                            "annotations": [{"type": "speech_metadata", "style": style_prompt}],
                        }],
                    }],
                    response_format={"type": "audio"},
                    generation_config={
                        "speech_config": [{"voice": voice_name}],
                    },
                )
                import base64
                # 3.8 unary audio is already WAV (RIFF header) — write it
                # directly. Wrapping it again (the old PCM path) puts header
                # bytes into the sample stream: a static burst at the tail.
                wav_bytes = base64.b64decode(interaction.output_audio.data)

                # Log the successful request to SQLite
                log_tts_request(req.voice, voice_name, req.text)

                return Response(
                    content=wav_bytes,
                    media_type="audio/wav",
                    headers={
                        "X-TTS-Voice-Used": voice_name
                    }
                )
            except Exception as e:
                error_str = str(e)
                last_error = e
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # If it's a daily quota, skip retrying this model and immediately fail over
                    if "generate_requests_per_model_per_day" in error_str:
                        print(f"Daily quota exhausted for {model_name}, switching to fallback model...")
                        break
                    
                    if attempt < max_retries - 1:
                        print(f"Rate limited (429) on {model_name}. Retrying in {retry_delay}s... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                
                print(f"Failed to generate TTS with {model_name}: {e}")
                break # On other errors, break the retry loop and try the next model

    return Response(content=str(last_error), status_code=500)

class SpeakLine(BaseModel):
    voice: str
    text: str
    style: str = ""

class SpeakMultiRequest(BaseModel):
    lines: list[SpeakLine]
    geminiSafety: GeminiSafety | None = None

@app.post("/speak-multi")
def speak_multi(req: SpeakMultiRequest):
    if not client:
        return Response(content="Missing API Key", status_code=500)
    
    if not req.lines:
        return Response(content="Empty lines", status_code=400)
    
    import time
    
    models_to_try = [
        "gemini-3.8-flash-lite-tts",
        "gemini-3.8-flash-tts"
    ]
    max_retries = 3
    retry_delay = 20
    
    STYLE_MAP = {
        "jax": "You are a male Australian radio presenter on Causeway FM. Speak in a high-energy, hopelessly optimistic, and upbeat tone. Always sound like you have a smile on your face and keep the tone authentic to your character.",
        "mia": "You are a female Australian radio presenter on Causeway FM. Speak in a witty, breezy, and grounded tone. Keep the tone authentic to your character.",
        "owen": "You are a male Australian radio presenter on Causeway FM. Speak in a dry, slightly cynical, but empathetic and informative tone. Keep the tone authentic to your character.",
        "chloe": "You are a female Australian radio presenter on Causeway FM. Speak in a dramatic, playful, and youthful tone. Keep the tone authentic to your character.",
        "roxy": "You are a female Australian radio presenter on Causeway FM. Speak in a cool, confident, laid-back, and smooth tone. Keep the tone authentic to your character.",
        "leo": "You are a male Australian radio presenter on Causeway FM. Speak in a charming, slightly sarcastic, and smooth tone. Keep the tone authentic to your character.",
        "zane": "You are a male Australian radio presenter on Causeway FM. Speak in a loud, electric, fast-paced, and highly excitable tone. Keep the tone authentic to your character.",
        "lexi": "You are a female Australian radio presenter on Causeway FM. Speak in a high-octane, fiercely fun, and bright club energy tone. Keep the tone authentic to your character.",
        "miles": "You are a male Australian radio presenter on Causeway FM. Speak in a warm, slightly understated, soft, and intimate late-night tone. Keep the tone authentic to your character.",
    }
    
    speakers = []
    seen_voices = set()
    turns = []

    for line in req.lines:
        voice_name, voice_alias = resolve_voice(line.voice)
        alias = voice_alias.capitalize() if voice_alias else voice_name
        v_key = (voice_alias or voice_name).lower()

        if v_key not in seen_voices:
            speakers.append({"speaker": alias, "voice": voice_name})
            seen_voices.add(v_key)
        style_tone = (line.style or "").strip() or SHORT_STYLES.get(voice_alias, "smooth and natural")
        clean_text, cue_styles = split_cues(line.text.strip())
        if cue_styles:
            style_tone = f"{style_tone}, {', '.join(cue_styles)}"
        turns.append({
            "type": "text",
            "text": clean_text,
            "annotations": [{"type": "speech_metadata", "speaker": alias, "style": style_tone}],
        })

    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                # NOTE: no safety params here — the Interactions API 400s them
                # as unknown (see /speak above). TTS renders under defaults.
                interaction = client.interactions.create(
                    model=model_name,
                    input=[{"type": "user_input", "content": turns}],
                    response_format={"type": "audio"},
                    generation_config={
                        "speech_config": {"mode": "conversational", "speakers": speakers},
                    },
                )
                import base64
                wav_bytes = base64.b64decode(interaction.output_audio.data)

                # Log successful requests to SQLite individually
                for line in req.lines:
                    logged_name, _ = resolve_voice(line.voice)
                    log_tts_request(line.voice, logged_name, line.text)

                return Response(
                    content=wav_bytes,
                    media_type="audio/wav",
                    headers={
                        "X-TTS-Voice-Used": "multi-speaker"
                    }
                )
            except Exception as e:
                error_str = str(e)
                last_error = e
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if "generate_requests_per_model_per_day" in error_str:
                        print(f"Daily quota exhausted for {model_name}, switching to fallback model...")
                        break
                    if attempt < max_retries - 1:
                        print(f"Rate limited (429) on {model_name}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                print(f"Failed to generate multi TTS with {model_name}: {e}")
                break

    return Response(content=str(last_error), status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
