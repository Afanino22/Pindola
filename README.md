# Pindola AI Ad Localization Pipeline -- MVP

End-to-end pipeline that takes a video ad → transcribes speech → culturally localizes the script → generates voice-over → produces a localized video.

```
Video Input  ──►  [Extract Audio]  ──►  [Whisper Transcription]  ──►  [LLM Localization]  ──►  [TTS Voice]  ──►  Localized Video
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install system dependency (required for video processing)
sudo apt-get install ffmpeg

# Run the full demo (all 4 languages with placeholder video)
python main.py --demo --llm xkiro --tts edge

# Localize to a single language with the sample script
python main.py --target-lang es

# Localize a video file
python main.py --input my_ad.mp4 --target-lang fr

# Script-only mode (no video)
python main.py --script-only --target-lang de
```

## Demo Output

After running `python main.py --demo`, check `output/demo/`:

```
output/demo/
├── placeholder_source.mp4      # Auto-generated 30s demo video
├── MASTER_COMPARISON.txt       # All 4 localizations side-by-side
├── en/                         # English
│   ├── script_en.txt           # Localized script
│   ├── voiceover_en.wav        # Voice-over audio
│   ├── localized_en.mp4        # Final localized video
│   └── comparison.txt          # EN side-by-side comparison
├── es/                         # Spanish
│   ├── script_es.txt
│   ├── voiceover_es.wav
│   ├── localized_es.mp4
│   └── comparison.txt
├── fr/                         # French
│   ├── script_fr.txt
│   ├── voiceover_fr.wav
│   ├── localized_fr.mp4
│   └── comparison.txt
└── de/                         # German
    ├── script_de.txt
    ├── voiceover_de.wav
    ├── localized_de.mp4
    └── comparison.txt
```

## Pipeline Steps

### 1. Video Input
Accepts MP4, MOV, WebM files via `--input`. If no video is provided, falls back to `sample_script.txt`.

### 2. Audio Extraction
Extracts audio track from video using ffmpeg (16kHz mono WAV for optimal transcription).

### 3. Speech Transcription
- Uses OpenAI Whisper API (`whisper-1` model) when `OPENAI_API_KEY` is set
- Falls back to the provided script if no API key is available
- For the demo, uses `sample_script.txt` as the transcription

### 4. Script Localization
- Sends the script to an LLM (xKiro, GPT-4o or Claude) with a detailed prompt
- The prompt instructs the model to **localize, not translate** -- adapting idioms, cultural references, emotional tone, and CTAs
- Falls back to high-quality handcrafted demo localizations (EN, ES, FR, DE) when no API key

### 5. Voice Generation (TTS)
- Edge TTS (free neural voices) is the first `auto` fallback
- ElevenLabs (multilingual v2, voice: Rachel)
- OpenAI TTS (voice: Nova) as alternative
- Python-generated placeholder audio (modulated sine wave) as final fallback
- xKiro TTS is not available: its `/v1/audio/speech` endpoint returned 404

### 6. Video + Audio Combination
- Merges original video with localized audio using ffmpeg
- Preserves original video quality (stream copy) where possible
- Falls back to re-encoding if needed

## API Keys

The pipeline works **without any API keys** using demo localizations and placeholder audio. For production quality:

```bash
export XKIRO_API_KEY=...              # xKiro OpenAI-compatible LLM
export XKIRO_MODEL=minimax/minimax-m2.1  # choose an account-permitted model
export OPENAI_API_KEY=sk-...          # GPT-4o translation + TTS + Whisper
export ELEVENLABS_API_KEY=...         # Higher-quality TTS (optional)
export ANTHROPIC_API_KEY=sk-ant-...   # Alternative LLM (optional)
```

Or copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

## CLI Options

```
python main.py [--input PATH] [--script PATH] [--target-lang CODE]
               [--output-dir PATH] [--tts PROVIDER] [--llm PROVIDER]
               [--demo] [--script-only] [--keep-audio]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (none) | Input video file (MP4, MOV, WebM) |
| `--script` | `sample_script.txt` | English source script (bypasses transcription) |
| `--target-lang` | `es` | Target language code |
| `--output-dir` | `output/<lang>/` | Custom output directory |
| `--tts` | `auto` | TTS provider: edge, elevenlabs, openai, auto (xKiro TTS unavailable) |
| `--llm` | `auto` | LLM provider: xkiro, openai, anthropic, auto |
| `--demo` | (flag) | Run all 4 demo languages with placeholder video |
| `--script-only` | (flag) | Skip video, just localize script + generate audio |
| `--keep-audio` | (flag) | Keep extracted original audio file |

## Supported Languages

The demo includes handcrafted localizations for:
- 🇺🇸 English (en)
- 🇪🇸 Spanish (es)
- 🇫🇷 French (fr)
- 🇩🇪 German (de)

With API keys, the LLM can localize to any language: Italian, Portuguese, Japanese, Korean, Chinese, Arabic, Hindi, Dutch, Polish, Turkish, Thai, Vietnamese, Indonesian, and more.

## Sample Script

The included `sample_script.txt` is a fictional 30-second e-commerce ad for "GlowMatrix" -- a skincare serum:

- **[HOOK]** -- Attention-grabbing opening (0-5s)
- **[PROBLEM]** -- Relatable pain point (5-12s)
- **[SOLUTION]** -- Product introduction and benefits (12-22s)
- **[CTA]** -- Call-to-action with urgency (22-30s)

## Dependencies

- **Python**: `openai`, `requests`, `python-dotenv` (see `requirements.txt`)
- **System**: `ffmpeg` (for audio extraction and video combination)

## Architecture

```
main.py                 # Main pipeline orchestrator + CLI
demo_localizations.py   # Handcrafted demo translations (EN, ES, FR, DE)
sample_script.txt       # GlowMatrix 30s ad script
output/demo/            # Demo output files
```

## Next Steps for Production

1. Add web UI (Flask/FastAPI) with drag-and-drop upload
2. Add subtitle generation (SRT/VTT) using Whisper timestamps
3. Add multi-language batch processing queue
4. Add lip-sync support for talking-head videos
5. Add A/B test analytics for localized ad performance

## xKiro providers

Set `XKIRO_API_KEY` (source the project venv if using the supplied setup). xKiro uses the OpenAI Python SDK with `https://api.xkiro.com/v1`.

| Provider | Explicit flag | Auto order |
|---|---|---|
| LLM xKiro | `--llm xkiro` | 1 (when key set) |
| TTS Edge | `--tts edge` | 1 |
| ElevenLabs | `--tts elevenlabs` | after Edge |
| OpenAI | `--tts openai` | after ElevenLabs |

Examples:

```bash
source venv/bin/activate
python main.py --demo --llm xkiro --tts edge
python main.py --script-only --target-lang es --llm auto --tts auto
```

Discovery details, model access observations, and the xKiro TTS endpoint result are in `xkiro_report.md`. `--llm auto` tries xKiro first, then configured OpenAI, then the built-in demo localization.
