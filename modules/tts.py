import asyncio
import os
import re

import edge_tts

OPENAI_VOICE = "onyx"
OPENAI_MODEL = "tts-1-hd"

# Mood → (voice, speed) — verschiedene Stimme + Tempo pro Story-Typ
_MOOD_VOICE: dict[str, tuple[str, float]] = {
    "drama":    ("onyx",    0.92),   # tief, ernst, etwas langsamer
    "funny":    ("shimmer", 1.08),   # leicht, spielerisch, etwas schneller
    "sad":      ("nova",    0.88),   # sanft, empathisch, langsamer
    "suspense": ("fable",   0.95),   # mysteriöser Erzähler, etwas langsamer
}


def _tts_openai(text: str, audio_path: str, api_key: str,
                voice: str = OPENAI_VOICE, speed: float = 1.0) -> list[dict]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    response = client.audio.speech.create(
        model=OPENAI_MODEL,
        voice=voice,
        input=text,
        speed=speed,
    )
    with open(audio_path, "wb") as f:
        f.write(response.content)

    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    return [{"word": w.word.strip(), "start": w.start, "end": w.end} for w in (transcript.words or [])]


async def _tts_edge_async(text: str, audio_path: str, voice_name: str) -> list[dict]:
    communicate  = edge_tts.Communicate(text, voice_name, boundary="WordBoundary")
    word_timings = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                dur   = chunk["duration"] / 1e7
                word_timings.append({"word": chunk["text"], "start": start, "end": start + dur})
    return word_timings


def text_to_speech(text: str, output_path: str, topic: str = "",
                   mood: str = "") -> tuple[str, list[dict]]:
    """
    OpenAI TTS (stimmungsabhängige Stimme + Tempo) → Edge TTS Fallback.
    mood: 'drama' | 'funny' | 'sad' | 'suspense' | ''
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if openai_key:
        voice, speed = _MOOD_VOICE.get(mood, (OPENAI_VOICE, 1.0))
        try:
            print(f"   OpenAI TTS [{voice} @ {speed}x] ...")
            timings = _tts_openai(text, output_path, openai_key, voice=voice, speed=speed)
            return output_path, timings
        except Exception as e:
            print(f"   OpenAI TTS Fehler: {e} — Edge TTS Fallback")

    voice_name = "de-DE-FlorianMultilingualNeural"
    print(f"   Edge TTS Fallback: {voice_name}")
    timings = asyncio.run(_tts_edge_async(text, output_path, voice_name))
    return output_path, timings


def get_sentence_timings(text: str, word_timings: list[dict]) -> list[tuple]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not word_timings:
        return [(s, i * 3.0, (i + 1) * 3.0) for i, s in enumerate(sentences)]
    result, word_idx = [], 0
    for sentence in sentences:
        n  = len(re.findall(r'\w+', sentence))
        si = min(word_idx, len(word_timings) - 1)
        ei = min(word_idx + n - 1, len(word_timings) - 1)
        result.append((sentence, max(0, word_timings[si]["start"] - 0.1), word_timings[ei]["end"] + 0.2))
        word_idx += n
    return result
