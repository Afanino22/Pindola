#!/usr/bin/env python3
"""
Pindola AI Ad Localization Pipeline -- MVP
==========================================
End-to-end pipeline: video in -> localized video out.

Workflow:
  1. Video Upload / Input
  2. Audio Extraction (ffmpeg)
  3. Speech Transcription (OpenAI Whisper API, or fallback to script)
  4. Script Localization (Gemini/xKiro/OpenAI/Anthropic LLM, or demo fallback)
  5. Voice Generation / TTS (Edge/ElevenLabs/OpenAI, or placeholder)
  6. Video + Audio Combination (ffmpeg)

Usage:
    python main.py --input video.mp4 --target-lang es
    python main.py --input video.mp4 --target-lang fr --output-dir output/fr/
    python main.py --demo                 # Run all 4 demo languages
    python main.py --script-only          # Script-only mode (no video)

Environment variables (see .env.example):
    GEMINI_API_KEY       - Primary LLM (Google Gemini) for localization
    GEMINI_MODEL         - Gemini model name (default: gemini-2.0-flash)
    XKIRO_API_KEY        - xKiro LLM fallback (OpenAI-compatible)
    OPENAI_API_KEY       - For GPT-4o translation + TTS + Whisper
    ELEVENLABS_API_KEY   - Optional, for higher-quality TTS
    ANTHROPIC_API_KEY    - Optional, for alternative LLM translation
"""

import argparse
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEMO_OUTPUT_DIR = BASE_DIR / "output" / "demo"
SAMPLE_SCRIPT = BASE_DIR / "sample_script.txt"

# Try to load .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# Import demo localizations
from demo_localizations import get_demo_localization, LANGUAGE_MAP as DEMO_LANG_MAP


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Pindola Ad Localization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", type=Path,
        help="Path to input video file (MP4, MOV, WebM)",
    )
    parser.add_argument(
        "--script", type=Path, default=None,
        help="Path to English ad script (bypasses transcription). Used when --input not provided.",
    )
    parser.add_argument(
        "--target-lang", default=os.getenv("TARGET_LANGUAGE", "es"),
        help="Target language code (default: es). Use 'en' for English pass-through.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Output directory (default: output/<lang>/)",
    )
    parser.add_argument(
        "--tts", choices=["openai", "elevenlabs", "edge", "auto"], default=os.getenv("TTS_PROVIDER", "auto"),
        help="TTS provider (default: auto)",
    )
    parser.add_argument(
        "--llm", choices=["openai", "anthropic", "xkiro", "gemini", "auto"], default=os.getenv("LLM_PROVIDER", "auto"),
        help="LLM provider for localization (default: auto; auto order: gemini -> xkiro -> openai -> demo)",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run demo mode: localize to en, es, fr, de using placeholder video",
    )
    parser.add_argument("--no-tts", action="store_true", help="Demo visuals and localized scripts only; skip TTS/audio merge.")
    parser.add_argument(
        "--script-only", action="store_true",
        help="Script-only mode: skip video input, just localize text + generate audio",
    )
    parser.add_argument(
        "--keep-audio", action="store_true",
        help="Keep the extracted original audio file",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------
LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "pt-BR": "Brazilian Portuguese",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)", "ar": "Arabic", "hi": "Hindi",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian",
}

def lang_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper())


# ---------------------------------------------------------------------------
# Step 0: Create placeholder demo video
# ---------------------------------------------------------------------------
def create_demo_source_video(output_path: Path, script_text: str = "", duration: int = 30):
    """Render a polished 30-second LumaSkin motion-graphics ad with FFmpeg."""
    import subprocess
    from PIL import Image, ImageDraw
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent / "_lumaskin_assets"
    work.mkdir(exist_ok=True)
    # Generate amber serum bottle asset
    bottle = work / "bottle.png"
    if not bottle.exists():
        im = Image.new("RGBA", (420, 760), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle((85, 190, 335, 685), radius=42, fill=(187, 106, 37, 255), outline=(246, 204, 118, 255), width=7)
        d.rectangle((130, 125, 290, 205), fill=(205, 145, 65, 255), outline=(250, 220, 145, 255), width=5)
        d.rounded_rectangle((165, 45, 255, 145), radius=28, fill=(33, 26, 38, 255), outline=(228, 185, 94, 255), width=5)
        d.ellipse((205, 5, 215, 55), fill=(245, 205, 110, 230))
        d.rounded_rectangle((124, 350, 296, 520), radius=16, fill=(255, 242, 211, 235))
        d.text((151, 390), "LUMA", fill=(75, 43, 35, 255))
        d.text((153, 430), "SKIN", fill=(75, 43, 35, 255))
        d.line((112, 235, 112, 620), fill=(255, 221, 156, 150), width=14)
        im.save(bottle)

    font_b = '/home/team/shared/demo-video/assets/Poppins-Bold.ttf'
    font_s = '/home/team/shared/demo-video/assets/Poppins-SemiBold.ttf'
    scenes = [work / f'scene{i}.mp4' for i in range(1, 5)]
    durations = [5, 7, 10, 8]

    # Build each scene as a lavfi filtergraph string.
    # ffmpeg -f lavfi -i "<filtergraph>" -t <dur> -an sceneN.mp4
    # IMPORTANT: do NOT wrap numeric expressions in single quotes — only text= values.
    scene_filters = [
        # Scene 1 (0–5s): HOOK — dark purple, light sweep, particles, kinetic typography
        (
            "color=c=0x120b22:s=1920x1080:r=30:d=5,"
            "drawbox=x=-500+500*t:y=0:w=520:h=1080:color=0x9b64d8@0.12:t=fill,"
            "drawbox=x=mod(300*t\\,1920):y=130:w=4:h=4:color=white@0.8:t=fill,"
            "drawbox=x=mod(800*t+300\\,1920):y=360:w=7:h=7:color=0xf3c98b@0.7:t=fill,"
            "drawbox=x=mod(1200*t+700\\,1920):y=760:w=5:h=5:color=white@0.65:t=fill,"
            f"drawtext=fontfile={font_b}:text='TIRED':fontsize=170:fontcolor=white:"
            "x=(w-text_w)/2-500+500*t:y=290:enable='between(t,0.2,2.8)':"
            "alpha=min(1\\,(t-0.2)*3)*min(1\\,(3.2-t)*3),"
            f"drawtext=fontfile={font_b}:text='PROMISES':fontsize=126:fontcolor=0xf0c58a:"
            "x=(w-text_w)/2+500-500*t:y=465:enable='between(t,1.7,4.2)':"
            "alpha=min(1\\,(t-1.7)*3)*min(1\\,(4.7-t)*3),"
            f"drawtext=fontfile={font_b}:text='NOTHING.':fontsize=142:fontcolor=0xe58d9d:"
            "x=(w-text_w)/2:y=650:enable='between(t,3.1,5)':alpha=min(1\\,(t-3.1)*4),"
            "format=yuv420p"
        ),
        # Scene 2 (5–12s): PROBLEM — warm bronze, floating cards, strike-throughs
        (
            "color=c=0x20151b:s=1920x1080:r=30:d=7,"
            "drawbox=x=220+30*sin(t):y=170:w=1480:h=720:color=0x8f5b45@0.18:t=fill,"
            "drawbox=x=350+80*sin(t*0.8):y=280:w=1220:h=120:color=0xf3c98b@0.12:t=fill,"
            "drawbox=x=420+60*sin(t*0.7):y=475:w=1080:h=120:color=0xf3c98b@0.12:t=fill,"
            "drawbox=x=300+90*sin(t*0.6):y=670:w=1300:h=120:color=0xf3c98b@0.12:t=fill,"
            f"drawtext=fontfile={font_s}:text='12-STEP ROUTINES':fontsize=62:fontcolor=white:"
            "x=420+60*sin(t*0.7):y=308,"
            f"drawtext=fontfile={font_s}:text='$200 CREAMS':fontsize=62:fontcolor=white:"
            "x=520+45*sin(t*0.8):y=503,"
            f"drawtext=fontfile={font_s}:text='VIRAL HACKS':fontsize=62:fontcolor=white:"
            "x=520+70*sin(t*0.6):y=698,"
            "drawbox=x=380:y=335:w=min(1300\\,1300*(t/2)):h=9:color=0xe06b70:t=fill,"
            "drawbox=x=460:y=530:w=min(1100\\,1100*((t-1)/2)):h=9:color=0xe06b70:t=fill,"
            "drawbox=x=430:y=725:w=min(1200\\,1200*((t-2)/2)):h=9:color=0xe06b70:t=fill,"
            f"drawtext=fontfile={font_b}:text='✕':fontsize=110:fontcolor=0xe06b70:"
            "x=1510:y=270+80*sin(t):alpha=0.8,"
            "format=yuv420p"
        ),
        # Scene 3 (12–22s): SOLUTION — bright white/gold, bottle, count-up
        (
            "color=c=0xfffbf4:s=1920x1080:r=30:d=10,"
            "drawbox=x=960+700*sin(t*0.7):y=0:w=22:h=1080:color=0xe8b85c@0.10:t=fill,"
            f"drawtext=fontfile={font_s}:text='LUMASKIN':fontsize=54:fontcolor=0x9c682f:x=90:y=80,"
            f"drawtext=fontfile={font_b}:text='50,000 WOMEN':fontsize=104:fontcolor=0x3a2630:"
            "x=80+20*sin(t):y=230:alpha=min(1\\,t*2),"
            f"drawtext=fontfile={font_s}:text='Clinically Proven':fontsize=58:fontcolor=0x6e4d3e:"
            "x=90:y=410:enable='between(t,3,10)',"
            f"drawtext=fontfile={font_s}:text='Results in 7 Days':fontsize=58:fontcolor=0x9b682f:"
            "x=90:y=515:enable='between(t,4,10)',"
            f"drawtext=fontfile={font_s}:text='No false promises':fontsize=58:fontcolor=0x9b682f:"
            "x=90:y=620:enable='between(t,5,10)',"
            "drawbox=x=1300+40*sin(t):y=300:w=260:h=430:color=0xb86a25@0.95:t=fill,"
            "drawbox=x=1370+40*sin(t):y=235:w=120:h=80:color=0xd39a4d:t=fill,"
            "drawbox=x=1410+40*sin(t):y=175:w=40:h=70:color=0x211a26:t=fill,"
            "format=yuv420p"
        ),
        # Scene 4 (22–30s): CTA — premium gradient, badge, button, glow pulse
        (
            "color=c=0x25132f:s=1920x1080:r=30:d=8,"
            "drawbox=x=0:y=0:w=1920:h=1080:color=0x6f3f80@0.22:t=fill,"
            f"drawtext=fontfile={font_b}:text='LUMASKIN':fontsize=54:fontcolor=0xf4cf98:x=90:y=80,"
            f"drawtext=fontfile={font_b}:text='30 DAY RISK FREE':fontsize=130:fontcolor=white:"
            "x=(w-text_w)/2:y=285+18*sin(t*1.5),"
            f"drawtext=fontfile={font_s}:text='Money Back Guarantee':fontsize=58:fontcolor=0xf4cf98:"
            "x=(w-text_w)/2:y=470,"
            "drawbox=x=650:y=620:w=620:h=150:color=0xf0b85d@0.85:t=fill,"
            f"drawtext=fontfile={font_b}:text='LINK IN BIO  →':fontsize=62:fontcolor=0x321b32:"
            "x=(w-text_w)/2:y=660,"
            f"drawtext=fontfile={font_s}:text='Your skin is waiting.':fontsize=42:fontcolor=0xffffff@0.75:"
            "x=(w-text_w)/2:y=865,"
            "format=yuv420p"
        ),
    ]

    for i, (filt, path) in enumerate(zip(scene_filters, scenes), 1):
        dur = durations[i - 1]
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", filt,
               "-c:v", "libx264", "-preset", "medium", "-crf", "23",
               "-an", "-t", str(dur), str(path)]
        print(f"[VIDEO] Rendering scene {i}/{len(scenes)} ({dur}s)...")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"FFmpeg scene {i} failed:\n{r.stderr[-1200:]}")

    # Assemble with crossfades
    fc = (
        "[0:v][1:v]xfade=transition=fade:duration=0.6:offset=4.4[v1];"
        "[v1][2:v]xfade=transition=fade:duration=0.6:offset=10.8[v2];"
        "[v2][3:v]xfade=transition=fade:duration=0.6:offset=20.2[v]"
    )
    cmd = ["ffmpeg", "-y"] + sum((["-i", str(x)] for x in scenes), []) + [
        "-filter_complex", fc, "-map", "[v]",
        "-t", "30", "-r", "30", "-s", "1920x1080",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(output_path)
    ]
    print("[VIDEO] Assembling final video with xfade transitions...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"FFmpeg concat failed:\n{r.stderr[-1200:]}")

    size_mb = output_path.stat().st_size / 1048576
    print(f"[VIDEO] Demo source created: {output_path} ({size_mb:.1f} MB)")
    return output_path


# ---------------------------------------------------------------------------
# Step 1: Video Input & Audio Extraction
# ---------------------------------------------------------------------------
def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """Extract audio from video using ffmpeg."""
    audio_path = output_dir / "extracted_audio.wav"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[AUDIO] Extracting audio from {video_path.name}...")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[AUDIO] ffmpeg error: {result.stderr[:300]}")
        raise RuntimeError(f"Failed to extract audio from {video_path}")

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"[AUDIO] Extracted: {audio_path} ({size_mb:.1f} MB)")
    return audio_path


# ---------------------------------------------------------------------------
# Step 2: Speech Transcription
# ---------------------------------------------------------------------------
def transcribe_audio(audio_path: Path, script_fallback: str = None, return_segments: bool = False):
    """Transcribe speech, optionally returning Whisper timestamped segments."""
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            print("[WHISPER] Transcribing via OpenAI Whisper API...")
            with open(audio_path, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=f, response_format="verbose_json"
                )
            text = transcript if isinstance(transcript, str) else transcript.text
            segments = [] if isinstance(transcript, str) else (getattr(transcript, "segments", None) or [])
            if return_segments:
                return text, [dict(s) if isinstance(s, dict) else {"start": s.start, "end": s.end, "text": s.text} for s in segments]
            print(f"[WHISPER] Transcript: {len(text)} chars")
            return text
        except Exception as e:
            print(f"[WHISPER] API error: {e}. Falling back...")

    # Fallback
    if script_fallback:
        print("[WHISPER] Using provided script as transcription fallback.")
        return (script_fallback, []) if return_segments else script_fallback

    print("[WHISPER] No API key or fallback. Using minimal placeholder transcript.")
    text = "This is a placeholder transcript. Set OPENAI_API_KEY for live transcription."
    return (text, []) if return_segments else text


# ---------------------------------------------------------------------------
# Step 3: Script Localization
# ---------------------------------------------------------------------------
LOCALIZATION_PROMPT = """You are an expert ad copywriter and cultural localization specialist for {target_language}-speaking markets.

Your task: Take the following English ad script and localize it for a {target_language}-speaking audience.

CRITICAL RULES:
1. DO NOT translate literally. Rewrite the script so it sounds like it was originally written by a native {target_language} copywriter.
2. Preserve the emotional impact: the hook must grab attention, the problem must feel relatable, the solution must feel aspirational.
3. Adapt idioms, cultural references, and metaphors to ones that resonate in {target_language}-speaking culture.
4. Keep the CTA (call-to-action) urgent and compelling -- but phrased naturally for the market.
5. Maintain the original timing/pacing markers: [HOOK], [PROBLEM], [SOLUTION], [CTA] and time ranges like [0-5s].
6. Preserve brand names (e.g., "LumaSkin") and product-specific terms exactly as-is.
7. Output ONLY the localized script -- no explanations, no notes, no preamble.

Here is the English script:

{source_script}"""


def localize_with_openai(script: str, target_lang: str) -> str:
    """Use OpenAI GPT-4o to translate and culturally localize the script."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    lang = lang_name(target_lang)
    print(f"[LLM] Calling OpenAI GPT-4o for {lang} localization...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": f"You are a world-class {lang} copywriter who specializes in ad localization."},
            {"role": "user", "content": LOCALIZATION_PROMPT.format(target_language=lang, source_script=script)},
        ],
        temperature=0.7, max_tokens=2048,
    )
    localized = response.choices[0].message.content.strip()
    print(f"[LLM] Localized script received ({len(localized)} chars)")
    return localized


def localize_with_gemini(script: str, target_lang: str) -> str:
    """Localize with Google Gemini (default: gemini-2.0-flash, fast free tier)."""
    import google.generativeai as genai
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    genai.configure(api_key=key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(model_name)
    lang = lang_name(target_lang)
    print(f"[LLM] Calling Gemini {model_name} for {lang} localization...")
    response = model.generate_content(
        f"You are a world-class {lang} copywriter who specializes in ad localization.\n\n"
        + LOCALIZATION_PROMPT.format(target_language=lang, source_script=script),
        request_options={"timeout": 30},  # seconds; Gemini is generally fast
    )
    localized = (response.text or "").strip()
    if not localized:
        raise RuntimeError("Gemini returned an empty response")
    print(f"[LLM] Gemini localized script received ({len(localized)} chars)")
    return localized


def localize_with_xkiro(script: str, target_lang: str) -> str:
    """Localize with xKiro, retrying once on the configured backup model."""
    from openai import OpenAI
    key = os.getenv("XKIRO_API_KEY")
    if not key:
        raise RuntimeError("XKIRO_API_KEY is not configured")
    primary = os.getenv("XKIRO_MODEL", "minimax/minimax-m2.1")
    backup = os.getenv("XKIRO_BACKUP_MODEL", "mistralai/ministral-3b")
    models = [primary] + ([backup] if backup != primary else [])
    client = OpenAI(api_key=key, base_url=os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1"), timeout=15, max_retries=0)
    lang = lang_name(target_lang)
    messages = [
        {"role": "system", "content": f"You are a world-class {lang} copywriter who specializes in ad localization."},
        {"role": "user", "content": LOCALIZATION_PROMPT.format(target_language=lang, source_script=script)},
    ]
    last_error = None
    for index, model in enumerate(models):
        try:
            print(f"[LLM] Calling xKiro {model} for {lang} localization...")
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0.7, max_tokens=2048
            )
            localized = (response.choices[0].message.content or "").strip()
            if not localized:
                raise RuntimeError("xKiro returned an empty response")
            print(f"[LLM] xKiro localized script received ({len(localized)} chars)")
            return localized
        except Exception as error:
            last_error = error
            if index + 1 < len(models):
                print(f"[LLM] xKiro {model} failed ({error}); retrying with backup {models[index + 1]}...")
    raise RuntimeError(f"xKiro localization failed for {', '.join(models)}: {last_error}")


def localize_with_anthropic(script: str, target_lang: str) -> str:
    """Use Anthropic Claude to localize the script."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    lang = lang_name(target_lang)
    print(f"[LLM] Calling Anthropic Claude for {lang} localization...")
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048, temperature=0.7,
        system=f"You are a world-class {lang} copywriter who specializes in ad localization.",
        messages=[{"role": "user", "content": LOCALIZATION_PROMPT.format(target_language=lang, source_script=script)}],
    )
    localized = message.content[0].text.strip()
    print(f"[LLM] Localized script received ({len(localized)} chars)")
    return localized


def localize_script(script: str, target_lang: str, llm_provider: str) -> str:
    """Translate and culturally localize the ad script. Falls back to demo if no keys.

    Auto priority: Gemini -> xKiro -> OpenAI -> Anthropic (if set) -> demo.
    """
    providers = []
    if llm_provider == "gemini" or (llm_provider == "auto" and os.getenv("GEMINI_API_KEY")):
        providers.append(("Gemini", localize_with_gemini))
    if llm_provider == "xkiro" or (llm_provider == "auto" and os.getenv("XKIRO_API_KEY")):
        providers.append(("xKiro", localize_with_xkiro))
    if llm_provider in ("openai", "auto") and os.getenv("OPENAI_API_KEY"):
        providers.append(("OpenAI", localize_with_openai))
    if llm_provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        providers.append(("Anthropic", localize_with_anthropic))
    for name, fn in providers:
        try:
            return fn(script, target_lang)
        except Exception as e:
            print(f"[LLM] {name} failed: {e}. Trying fallback...")
            if llm_provider != "auto":
                raise
    if llm_provider != "auto" and not providers:
        raise RuntimeError(f"{llm_provider} provider is not configured")
    demo = get_demo_localization(target_lang)
    print(f"[LLM] No LLM provider available; using demo localization for {lang_name(target_lang)}.")
    return demo


# ---------------------------------------------------------------------------
# Step 4: Voice Generation (TTS)
# ---------------------------------------------------------------------------
def _clean_script_for_tts(text: str) -> str:
    """Remove markup markers for cleaner TTS input."""
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\d+-\d+s", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_tts_openai(text: str, target_lang: str) -> bytes:
    """Generate voice-over using OpenAI TTS."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    voice = os.getenv("OPENAI_TTS_VOICE", "nova")
    print(f"[TTS] Calling OpenAI TTS (voice={voice}, lang={target_lang})...")
    clean_text = _clean_script_for_tts(text)
    response = client.audio.speech.create(
        model="tts-1", voice=voice, input=clean_text, response_format="mp3",
    )
    audio_bytes = response.content
    print(f"[TTS] Audio generated ({len(audio_bytes)} bytes)")
    return audio_bytes


def generate_tts_elevenlabs(text: str, target_lang: str) -> bytes:
    """Generate voice-over using ElevenLabs TTS."""
    import requests
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_map = {"es": "EXAVITQu4vr4xnSDxMaL", "fr": "pFZP5JQ8GlZ7KJ1hQfQ", "de": "TxGEqnHWrfWFTfGW9XjX", "en": "21m00Tcm4TlvDq8ikWAM"}
    try:
        voice_map.update(json.loads(os.getenv("ELEVENLABS_VOICES", "{}")))
    except json.JSONDecodeError:
        print("[TTS] Invalid ELEVENLABS_VOICES JSON; using defaults")
    voice_id = voice_map.get(target_lang, os.getenv("ELEVENLABS_VOICE_ID", "Rachel"))
    clean_text = _clean_script_for_tts(text)
    print(f"[TTS] Calling ElevenLabs TTS (voice={voice_id}, lang={target_lang})...")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {
        "text": clean_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    audio_bytes = resp.content
    print(f"[TTS] Audio generated ({len(audio_bytes)} bytes)")
    return audio_bytes


def generate_tts_edge(text: str, target_lang: str) -> bytes:
    """Generate free natural speech with Microsoft Edge TTS."""
    import asyncio
    import edge_tts
    voices = {"en": "en-US-JennyNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural"}
    voice = os.getenv("EDGE_TTS_VOICE", voices.get(target_lang, "en-US-JennyNeural"))
    out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    out.close()
    print(f"[TTS] Calling Edge TTS (voice={voice}, lang={target_lang})...")
    async def run():
        await edge_tts.Communicate(_clean_script_for_tts(text), voice).save(out.name)
    asyncio.run(run())
    data = Path(out.name).read_bytes()
    Path(out.name).unlink(missing_ok=True)
    print(f"[TTS] Edge audio generated ({len(data)} bytes)")
    return data


def generate_placeholder_audio(text: str, target_lang: str) -> bytes:
    """Generate a placeholder WAV using Python stdlib (modulated sine wave)."""
    print("[TTS] No API keys found. Generating placeholder audio (sine wave).")
    print("[TTS]    Set OPENAI_API_KEY or ELEVENLABS_API_KEY for natural voice-over.")

    word_count = len(text.split())
    duration_sec = max(3, word_count / 2.5)
    sample_rate = 24000
    num_samples = int(sample_rate * duration_sec)

    freq1, freq2 = 220, 280
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = math.sin(2 * math.pi * freq1 * t) if int(t * 6) % 2 == 0 else math.sin(2 * math.pi * freq2 * t)
        fade = min(1.0, t / 0.1, (duration_sec - t) / 0.3)
        val *= fade * 0.3
        samples.append(int(val * 32767))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    audio_bytes = buf.getvalue()
    print(f"[TTS] Placeholder audio: {len(audio_bytes)} bytes, {duration_sec:.1f}s")
    return audio_bytes


def generate_voiceover(text: str, target_lang: str, tts_provider: str) -> bytes:
    """Generate voice-over audio. Falls back to placeholder if no API keys."""
    if tts_provider == "xkiro":
        raise RuntimeError("xKiro TTS is unavailable: /v1/audio/speech returned 404")
    providers = []
    if tts_provider == "edge" or tts_provider == "auto":
        providers.append(("Edge TTS", generate_tts_edge))
    if tts_provider in ("elevenlabs", "auto") and os.getenv("ELEVENLABS_API_KEY"):
        providers.append(("ElevenLabs", generate_tts_elevenlabs))
    if tts_provider in ("openai", "auto") and os.getenv("OPENAI_API_KEY"):
        providers.append(("OpenAI", generate_tts_openai))
    for name, fn in providers:
        try: return fn(text, target_lang)
        except Exception as e: print(f"[TTS] {name} failed: {e}. Trying fallback...")
    return generate_placeholder_audio(text, target_lang)


# ---------------------------------------------------------------------------
# Step 5: Combine Video + Localized Audio
# ---------------------------------------------------------------------------
def combine_video_audio(
    video_path: Path, audio_bytes: bytes, output_path: Path, target_lang: str,
    preset: str = "9x16",
):
    """Combine audio and scale/crop to an export preset."""
    sizes = {"9x16": "1080:1920", "16x9": "1920:1080", "1x1": "1080:1080"}
    if preset not in sizes:
        raise ValueError(f"Unknown export preset: {preset}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write audio bytes to temp file
    if audio_bytes[:4] == b"RIFF":
        audio_ext = ".wav"
    elif audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb":
        audio_ext = ".mp3"
    else:
        audio_ext = ".mp3"

    temp_audio = output_path.parent / f"_temp_audio_{target_lang}{audio_ext}"
    temp_audio.write_bytes(audio_bytes)

    print(f"[COMBINE] Merging video + {lang_name(target_lang)} audio...")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(temp_audio),
        "-vf", f"scale={sizes[preset]}:force_original_aspect_ratio=decrease,pad={sizes[preset]}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Try re-encoding video if stream copy fails
        print("[COMBINE] Stream copy failed, re-encoding...")
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(temp_audio),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True)
        if result2.returncode != 0:
            print(f"[COMBINE] ffmpeg error: {result2.stderr[:300]}")
            raise RuntimeError("Failed to combine video and audio")

    # Clean up temp audio
    temp_audio.unlink(missing_ok=True)

    size_mb = output_path.stat().st_size / (1024 * 1024) if output_path.exists() else 0
    print(f"[COMBINE] Localized video: {output_path} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------
def _srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(localized_script: str, segments=None) -> str:
    """Create SRT, scaling each source segment duration by localized word ratio."""
    clean = _clean_script_for_tts(localized_script)
    words = clean.split()
    segments = segments or [{"start": 0.0, "end": max(3.0, len(words) / 2.5), "text": ""}]
    source_words = [len(str(s.get("text", "")).split()) for s in segments]
    if not any(source_words): source_words = [max(1, len(words)) for _ in segments]
    total_source = sum(source_words) or 1
    total_duration = max(float(s.get("end", 0)) for s in segments)
    ratio = max(0.5, len(words) / total_source)
    chunks, pos = [], 0
    for count in source_words:
        n = max(1, round(len(words) * count / total_source))
        chunks.append(" ".join(words[pos:pos+n])); pos += n
    if pos < len(words): chunks[-1] += " " + " ".join(words[pos:])
    out = []
    for i, (seg, text) in enumerate(zip(segments, chunks), 1):
        start = float(seg.get("start", 0)); end = start + max(0.2, (float(seg.get("end", start)) - start) * ratio)
        out += [str(i), f"{_srt_time(start)} --> {_srt_time(min(end, total_duration * ratio))}", text, ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Step 6: Save all outputs
# ---------------------------------------------------------------------------
def save_outputs(
    output_dir: Path,
    target_lang: str,
    source_script: str,
    localized_script: str,
    audio_bytes: bytes,
):
    """Save localized script, audio, and comparison report."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Localized script
    script_path = output_dir / f"script_{target_lang}.txt"
    script_path.write_text(localized_script, encoding="utf-8")
    print(f"[SAVE] Script -> {script_path}")

    # Determine audio extension
    if audio_bytes[:4] == b"RIFF":
        ext = ".wav"
    elif audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb":
        ext = ".mp3"
    else:
        ext = ".mp3"

    # Audio
    audio_path = output_dir / f"voiceover_{target_lang}{ext}"
    audio_path.write_bytes(audio_bytes)
    print(f"[SAVE] Audio -> {audio_path} ({len(audio_bytes)} bytes)")

    # Comparison report
    compare_path = output_dir / "comparison.txt"
    compare_path.write_text(
        f"=== PINDOLA AD LOCALIZATION REPORT ===\n\n"
        f"Target language: {lang_name(target_lang)} ({target_lang})\n\n"
        f"--- ORIGINAL (English) ---\n{source_script}\n\n"
        f"--- LOCALIZED ({lang_name(target_lang)}) ---\n{localized_script}\n",
        encoding="utf-8",
    )
    print(f"[SAVE] Comparison -> {compare_path}")


# ---------------------------------------------------------------------------
# Core pipeline: one language
# ---------------------------------------------------------------------------
def process_one_language(
    video_path: Path,
    target_lang: str,
    output_dir: Path,
    source_script: str = None,
    llm_provider: str = "auto",
    tts_provider: str = "auto",
    keep_audio: bool = False,
    progress_callback=None,
) -> dict:
    """Run the full pipeline for one target language."""
    lang = lang_name(target_lang)
    print(f"\n{'='*60}")
    print(f"  Processing: {lang} ({target_lang})")
    print(f"{'='*60}")

    output_dir.mkdir(parents=True, exist_ok=True)

    result = {"lang": target_lang, "output_dir": output_dir, "segments": []}

    def step(name):
        if progress_callback:
            progress_callback(name)
    # Step 1: Extract audio or use provided script
    step("extracting")
    if source_script is None and video_path and video_path.exists():
        try:
            audio_path = extract_audio(video_path, output_dir)
            result["extracted_audio"] = str(audio_path)
            step("transcribing")
            source_script, result["segments"] = transcribe_audio(audio_path, return_segments=True)
            if not keep_audio:
                audio_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"[ERROR] Audio extraction failed: {e}")
            source_script = SAMPLE_SCRIPT.read_text(encoding="utf-8").strip()
            print("[INFO] Using sample script as fallback.")
    elif source_script is None:
        source_script = SAMPLE_SCRIPT.read_text(encoding="utf-8").strip()
        print("[INFO] No video provided. Using sample script.")

    result["source_script"] = source_script

    # Step 2: Localize
    step("localizing")
    localized = localize_script(source_script, target_lang, llm_provider)
    result["localized_script"] = localized

    # Save script immediately
    script_path = output_dir / f"script_{target_lang}.txt"
    script_path.write_text(localized, encoding="utf-8")

    # Step 3: Generate voice-over
    step("tts")
    audio = generate_voiceover(localized, target_lang, tts_provider)
    result["audio_bytes"] = len(audio)

    # Save audio
    ext = ".wav" if audio[:4] == b"RIFF" else ".mp3"
    audio_path = output_dir / f"voiceover_{target_lang}{ext}"
    audio_path.write_bytes(audio)
    result["audio_path"] = str(audio_path)

    # Step 4: Subtitles and export presets
    step("subtitles")
    srt_path = output_dir / f"localized_{target_lang}.srt"
    srt_path.write_text(generate_srt(localized, result.get("segments")), encoding="utf-8")
    result["srt_path"] = str(srt_path)
    step("exporting")
    if video_path and video_path.exists():
        result["video_paths"] = {}
        for preset in ("9x16", "16x9", "1x1"):
            video_out = output_dir / f"localized_{target_lang}_{preset}.mp4"
            try:
                combine_video_audio(video_path, audio, video_out, target_lang, preset)
                result["video_paths"][preset] = str(video_out)
            except Exception as e:
                print(f"[COMBINE] {preset} export failed: {e}")
        if result["video_paths"]:
            result["video_path"] = next(iter(result["video_paths"].values()))
    # Save comparison
    compare_path = output_dir / "comparison.txt"
    compare_path.write_text(
        f"=== PINDOLA AD LOCALIZATION REPORT ===\n\n"
        f"Target: {lang} ({target_lang})\n\n"
        f"--- ORIGINAL (English) ---\n{source_script}\n\n"
        f"--- LOCALIZED ({lang}) ---\n{localized}\n",
        encoding="utf-8",
    )

    print(f"[DONE] {lang} localization complete -> {output_dir}")
    return result


# ---------------------------------------------------------------------------
# Demo mode: batch process all 4 languages
# ---------------------------------------------------------------------------
def run_demo(output_base: Path, llm_provider: str, tts_provider: str, no_tts: bool = False):
    """Run the full demo: create placeholder video, localize to all 4 languages."""
    print("\n" + "="*60)
    print("  PINDOLA DEMO MODE")
    print("  Localizing LumaSkin ad to: EN, ES, FR, DE")
    print("="*60)

    output_base.mkdir(parents=True, exist_ok=True)

    # Load source script
    source_script = SAMPLE_SCRIPT.read_text(encoding="utf-8").strip()

    # Create placeholder video (30s ad)
    placeholder_video = output_base / "lumaskin_source.mp4"
    create_demo_source_video(placeholder_video, source_script, duration=30)

    demo_langs = ["en", "es", "fr", "de"]
    results = {}

    for lang in demo_langs:
        lang_dir = output_base / lang
        if no_tts:
            localized = localize_script(source_script, lang, llm_provider)
            lang_dir.mkdir(parents=True, exist_ok=True)
            (lang_dir / f"script_{lang}.txt").write_text(localized, encoding="utf-8")
            result = {"lang": lang, "output_dir": lang_dir, "localized_script": localized, "video_path": str(placeholder_video)}
            print(f"[NO-TTS] Saved localized script for {lang}")
        else:
            result = process_one_language(
                video_path=placeholder_video, target_lang=lang, output_dir=lang_dir,
                source_script=source_script, llm_provider=llm_provider,
                tts_provider=tts_provider, keep_audio=False,
            )
        results[lang] = result

    # Summary
    print("\n" + "="*60)
    print("  DEMO COMPLETE!")
    print("="*60)
    for lang, r in results.items():
        video_status = "YES" if r.get("video_path") else "NO"
        print(f"  {lang_name(lang):20s} ({lang})  Script: YES  Audio: YES  Video: {video_status}")

    print(f"\n  Output directory: {output_base}")
    print(f"  Files produced:")
    for lang in demo_langs:
        lang_dir = output_base / lang
        for f in sorted(lang_dir.iterdir()):
            size = f.stat().st_size
            print(f"    {f.relative_to(output_base)} ({size:,} bytes)")

    # Create a master comparison
    master = output_base / "MASTER_COMPARISON.txt"
    lines = ["="*60, "  PINDOLA AI LOCALIZATION - DEMO RESULTS", "="*60, ""]
    for lang in demo_langs:
        script_path = output_base / lang / f"script_{lang}.txt"
        if script_path.exists():
            lines.append(f"\n{'='*60}")
            lines.append(f"  {lang_name(lang).upper()} ({lang})")
            lines.append(f"{'='*60}")
            lines.append(script_path.read_text(encoding="utf-8"))
    master.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Master comparison: {master}")

    return results


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    # Demo mode
    if args.demo:
        run_demo(
            output_base=args.output_dir or DEMO_OUTPUT_DIR,
            llm_provider=args.llm,
            tts_provider=args.tts,
            no_tts=args.no_tts,
        )
        return

    # Script-only mode
    if args.script_only:
        script_path = args.script or SAMPLE_SCRIPT
        source_script = script_path.read_text(encoding="utf-8").strip() if script_path.exists() else None
        output_dir = args.output_dir or OUTPUT_DIR / args.target_lang
        process_one_language(
            video_path=None,
            target_lang=args.target_lang,
            output_dir=output_dir,
            source_script=source_script,
            llm_provider=args.llm,
            tts_provider=args.tts, no_tts=args.no_tts,
        )
        print("\n[DONE] Script-only mode complete.")
        return

    # Single language pipeline
    video_path = args.input
    output_dir = args.output_dir or OUTPUT_DIR / args.target_lang

    if video_path and video_path.exists():
        source_script = None  # Will be transcribed from video
    elif args.script and args.script.exists():
        source_script = args.script.read_text(encoding="utf-8").strip()
    else:
        source_script = SAMPLE_SCRIPT.read_text(encoding="utf-8").strip()
        print("[INFO] No input video or script provided. Using sample script.")

    result = process_one_language(
        video_path=video_path if video_path and video_path.exists() else None,
        target_lang=args.target_lang,
        output_dir=output_dir,
        source_script=source_script,
        llm_provider=args.llm,
        tts_provider=args.tts,
        keep_audio=args.keep_audio,
    )

    print("\n" + "="*60)
    print(f"  Pipeline complete! -> {output_dir}")
    print("="*60)
    for k, v in result.items():
        if k != "source_script" and k != "localized_script":
            print(f"  {k}: {v}")
    print("\nTo use live AI APIs:")
    print("  export OPENAI_API_KEY=sk-...")
    print("  export ELEVENLABS_API_KEY=...  # optional, for better voices")
    print()


if __name__ == "__main__":
    main()
