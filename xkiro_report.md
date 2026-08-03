# xKiro discovery report

Tested 2026-08-02 using the configured `XKIRO_API_KEY` (never recorded here).

## Endpoints

| Endpoint | Result |
|---|---|
| `GET /v1/models` | **200 OK**; 55 models returned. |
| `POST /v1/chat/completions` | Works for permitted/free models (OpenAI-compatible SDK). Premium models return 403 on the current free account; some models can be slow/time out. |
| `GET /v1/audio/voices` | **200 OK**; 145 voices returned. This is a voice catalogue endpoint, not proof of OpenAI TTS compatibility. |
| `POST /v1/audio/speech` | **404 Not Found**. xKiro does not expose the requested OpenAI-compatible TTS endpoint. |

## Models and quality

The catalogue includes OpenAI, Anthropic, GLM, MiniMax, DeepSeek, Qwen, Mistral and NVIDIA model IDs. On the current account, `minimax/minimax-m2.1` accepted a chat request; `openai/gpt-5.5`, `z-ai/glm-5-turbo`, and `z-ai/glm-4.6` returned 403 premium/paid-plan errors. A short Spanish translation request was accepted by the permitted model, but the response was slow in testing. Use `XKIRO_MODEL` to select an account-permitted model; default is `minimax/minimax-m2.1`.

Because model access is account-plan dependent, the integration reports API errors and falls back rather than claiming every catalogue model works. Translation prompt preserves markers and asks for native ad localization.

## TTS

xKiro TTS is **not supported at the documented OpenAI-compatible route**: `/audio/speech` returned 404. `/audio/voices` returned a catalogue, but no usable speech-generation route was discoverable in this test. Therefore Pindola does not expose `--tts xkiro`; `--tts auto` uses Edge TTS first, then ElevenLabs/OpenAI as configured.

## Limits / key scope

No explicit rate-limit headers or quota response were observed. The same key authenticates `/models`, chat completions, and `/audio/voices`; TTS generation could not be tested because the endpoint is absent. Premium-model 403s and occasional long response times are the main observed limitations.
