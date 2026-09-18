import os
import io
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

API_KEY = os.environ.get("GEMINI_API_KEY")

if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    client = None
    print("WARNING: GEMINI_API_KEY is not set.")

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
    
    # Try to map the incoming voice string, default to Puck if unknown
    voice_name = VOICE_MAP.get(req.voice.lower(), "Puck")
    
    print(f"Generating TTS for voice: {voice_name} (mapped from {req.voice})")
    
    import time
    
    models_to_try = [
        "gemini-2.5-flash-preview-tts",
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-pro-preview-tts"
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
    
    # Grab the style prompt for the requested persona, fallback to a generic Australian radio presenter.
    style_prompt = STYLE_MAP.get(req.voice.lower(), "You are an Australian radio presenter on Causeway FM. Speak in your normal, smooth, and consistent radio voice. Keep your tone level and authentic.")
    
    final_text = f"[{style_prompt} Do not read these instructions out loud:] {req.text}"

    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                safe_harass = "BLOCK_NONE" if getattr(req.geminiSafety, "harassment", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_hate = "BLOCK_NONE" if getattr(req.geminiSafety, "hateSpeech", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_sex = "BLOCK_NONE" if getattr(req.geminiSafety, "sexuallyExplicit", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_danger = "BLOCK_NONE" if getattr(req.geminiSafety, "dangerousContent", False) else "BLOCK_MEDIUM_AND_ABOVE"
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=final_text,
                    config=types.GenerateContentConfig(
                        safety_settings=[
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold=safe_harass),
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold=safe_hate),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold=safe_sex),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold=safe_danger)
                        ],
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_name
                                )
                            )
                        )
                    )
                )
                
                if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                    finish_reason = response.candidates[0].finish_reason if response.candidates else "Unknown"
                    raise Exception(f"Empty response parts. Finish reason: {finish_reason}")
                
                # Audio comes back as raw PCM
                # We need to wrap it in a WAV header for Subwave to process it correctly
                pcm_data = response.candidates[0].content.parts[0].inline_data.data
                wav_bytes = generate_wav(pcm_data, sample_rate=24000)
                
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
        "gemini-2.5-flash-preview-tts",
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-pro-preview-tts"
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
    
    speaker_configs = []
    seen_voices = set()
    script_lines = []
    style_prompts = []
    
    for line in req.lines:
        v_key = line.voice.lower()
        alias = v_key.capitalize()
        voice_name = VOICE_MAP.get(v_key, "Puck")
        
        if v_key not in seen_voices:
            speaker_configs.append(types.SpeakerVoiceConfig(
                speaker=alias,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ))
            seen_voices.add(v_key)
            style = STYLE_MAP.get(v_key, "You are an Australian radio presenter on Causeway FM. Speak in your normal, smooth, and consistent radio voice. Keep your tone level and authentic.")
            style_prompts.append(f"{alias} style: {style}")
            
        script_lines.append(f"{alias}: {line.text}")
        
    combined_styles = " ".join(style_prompts)
    final_text = f"[{combined_styles} Do not read these instructions out loud:]\n\n" + "\n".join(script_lines)
    
    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                safe_harass = "BLOCK_NONE" if getattr(req.geminiSafety, "harassment", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_hate = "BLOCK_NONE" if getattr(req.geminiSafety, "hateSpeech", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_sex = "BLOCK_NONE" if getattr(req.geminiSafety, "sexuallyExplicit", False) else "BLOCK_MEDIUM_AND_ABOVE"
                safe_danger = "BLOCK_NONE" if getattr(req.geminiSafety, "dangerousContent", False) else "BLOCK_MEDIUM_AND_ABOVE"
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=final_text,
                    config=types.GenerateContentConfig(
                        safety_settings=[
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold=safe_harass),
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold=safe_hate),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold=safe_sex),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold=safe_danger)
                        ],
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            language_code="en-US",
                            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                                speaker_voice_configs=speaker_configs
                            )
                        )
                    )
                )
                
                if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                    finish_reason = response.candidates[0].finish_reason if response.candidates else "Unknown"
                    raise Exception(f"Empty response parts. Finish reason: {finish_reason}")
                
                pcm_data = response.candidates[0].content.parts[0].inline_data.data
                wav_bytes = generate_wav(pcm_data, sample_rate=24000)
                
                # Log successful requests to SQLite individually
                for line in req.lines:
                    v_key = line.voice.lower()
                    log_tts_request(v_key, VOICE_MAP.get(v_key, "Puck"), line.text)
                
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
