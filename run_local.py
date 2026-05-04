#!/usr/bin/env python3
"""
SynCin Reddit Story Bot DE — Lokaler Video-Generator
======================================================
Generiert ein Reddit-Story-Video und lädt es in die Bunny-Queue.
GitHub Actions postet es automatisch nach Schedule.

Usage:
  python run_local.py              # zufälliges Subreddit
  python run_local.py tifu
  python run_local.py aita 3       # 3 Videos generieren
"""

import json
import logging
import os
import random
import sys
import time
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "modules"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("redditbot-de")

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Trending Hashtag-Rotation (täglich, hält sie frisch) ─────────────────────
_TRENDING_POOL = [
    "#redditlesungen", "#redditgeschichten", "#redtok", "#storytok", "#musstsehen",
    "#unglaublich", "#verrückt", "#schockierend", "#viral2025", "#drama2025",
    "#geschichten", "#storytelling", "#wahregeschichte", "#reddit2025",
    "#fypシ", "#fypage", "#redditdeutsch", "#deutschreddit", "#stitch", "#duet",
    "#beziehungsdrama", "#alltagsstorys", "#täglicheredditor",
]

def _daily_trending(n: int = 3) -> list[str]:
    """Gibt n Hashtags aus dem Trending-Pool zurück, täglich rotierend."""
    seeded = _TRENDING_POOL.copy()
    rng = random.Random(date.today().toordinal())
    rng.shuffle(seeded)
    return seeded[:n]


def _cleanup_stale_files():
    """Löscht temp Audio/Video-Dateien älter als 20 Min, die Crashes hinterlassen haben."""
    cutoff = time.time() - 20 * 60
    for pattern in ["audio_*.mp3", "video_*.mp4"]:
        for f in OUTPUT_DIR.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    logger.info(f"🧹  Veraltete Datei gelöscht: {f.name}")
            except Exception:
                pass


def generate_and_queue(subreddit: str = None) -> bool:
    import certifi
    import requests

    from story_fetcher import fetch_story, SUBREDDITS
    from tts import text_to_speech
    from video_creator import create_video
    from quality_check import quality_check

    stamp      = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    audio_path = OUTPUT_DIR / f"audio_{stamp}.mp3"
    video_path = OUTPUT_DIR / f"video_{stamp}.mp4"

    try:
        # 1. Reddit Story holen
        logger.info(f"📖  Lade Reddit Story...")
        story_data = fetch_story(subreddit_override=subreddit)
        logger.info(f"    → r/{story_data['subreddit']}: {story_data['title'][:60]}")

        # 1b. KI-Qualitätsprüfung
        logger.info("🤖  KI-Qualitätsprüfung...")
        approved, reason = quality_check(
            title=story_data["title"],
            content=story_data["story"],
            context=f"r/{story_data['subreddit']}",
            lang="de",
        )
        logger.info(f"    → {reason}")
        if not approved:
            logger.info("    ❌  Abgelehnt — dieses Video wird übersprungen")
            return False

        # Mood früh holen — für Stimmenwahl + Caption
        from video_creator import SUBREDDIT_MOOD
        mood = SUBREDDIT_MOOD.get(story_data["subreddit"], "")

        # Teil-2-Cliffhanger: vorausgespaltene part1 (lange Storys) oder erzwungen (30%)
        is_part2_format = False
        if story_data.get("part2"):
            is_part2_format = True
            logger.info("    → Teil-2-Format (lange Story geteilt)")
        elif random.random() < 0.30:
            words_all = story_data["story"].split()
            cut_idx   = max(30, int(len(words_all) * 0.70))
            story_data["part2"] = " ".join(words_all[cut_idx:])
            story_data["story"] = " ".join(words_all[:cut_idx]) + "..."
            is_part2_format = True
            logger.info("    → Teil-2-Format (künstlicher Cliffhanger)")

        # 2. TTS + Word Timings
        logger.info("🎙️   Generiere Voiceover (OpenAI)...")
        if is_part2_format:
            _ctas = [
                "Folg uns — Teil 2 kommt morgen! Was glaubt ihr wie es ausgeht? 👇",
                "Stitch das mit eurer Reaktion! Teil 2 morgen 🔔",
                "Kommentiert eure Meinung — Teil 2 gibt es morgen!",
                "Was hättet ihr gemacht? Teil 2 folgt morgen 👇",
            ]
        else:
            _ctas = [
                "Was hättet ihr in dieser Situation gemacht? Schreibt es in die Kommentare! 👇",
                "Stitch das mit eurer Reaktion — ich will eure Meinung hören!",
                "Kommentiert: Wer hat hier recht? 👇",
                "Was denkt ihr darüber? Kommentiert jetzt! 🔥",
                "Schickt das jemandem der das kennt 👀 Kommentiert eure Meinung!",
                "Hättet ihr das auch so gemacht? Kommentiert! 👇",
            ]
        cta = random.choice(_ctas)
        tts_text = f"{story_data['title']}. {story_data['story']} {cta}"
        words = tts_text.split()
        MAX_WORDS = 165  # TikTok Monetization: 60+ Sekunden
        if len(words) > MAX_WORDS:
            tts_text = " ".join(words[:MAX_WORDS])
            for end_char in [". ", "! ", "? "]:
                idx = tts_text.rfind(end_char)
                if idx > 50:
                    tts_text = tts_text[:idx + 1]
                    break

        _, word_timings = text_to_speech(tts_text, str(audio_path), mood=mood)
        logger.info(f"    → {len(word_timings)} Wörter  [Stimme: {mood or 'default'}]")

        # 3. Video erstellen
        logger.info("🎞️   Rendere Video...")
        create_video(
            subreddit=story_data["subreddit"],
            title=story_data["title"],
            story=story_data["story"],
            audio_path=str(audio_path),
            output_path=str(video_path),
            word_timings=word_timings,
            gradient_index=random.randint(0, 4),
        )
        audio_path.unlink(missing_ok=True)  # Speicher früh freigeben

        mb = video_path.stat().st_size / 1024 / 1024
        logger.info(f"    → {video_path.name} ({mb:.1f} MB)")

        # 4. Caption — Emoji + Frage + Hashtags
        from video_creator import SUBREDDIT_QUESTIONS, DEFAULT_QUESTION
        question     = SUBREDDIT_QUESTIONS.get(story_data["subreddit"], DEFAULT_QUESTION)
        _emojis      = {"drama": "😤", "funny": "😂", "sad": "💔", "suspense": "👀"}
        mood_emoji   = _emojis.get(mood, "👀")
        description  = story_data.get("description", story_data["title"])

        # Teil-2-Cliffhanger-Markierung in der Caption
        part2_line = "\n🔔 Teil 2 kommt morgen — jetzt folgen!" if is_part2_format else ""
        # Stitch/Duet-Bait bei 35% der Videos
        stitch_line = "\n🎭 Stitch das mit deiner Reaktion 👇" if random.random() < 0.5 else ""
        # Täglich rotierende Trending-Hashtags
        trending = _daily_trending(3)

        full_caption = (
            f"{mood_emoji} {description}\n\n"
            f"{question}{part2_line}{stitch_line}\n\n"
            + " ".join(story_data["hashtags"] + trending)
        )

        # 5. Bunny-Queue
        logger.info("☁️   Lade in Bunny-Queue hoch...")
        password = os.environ["BUNNY_STORAGE_PASSWORD"]
        zone     = os.environ.get("BUNNY_STORAGE_NAME", "syncin")
        cdn_url  = os.environ.get("BUNNY_CDN_URL", "https://syncin.b-cdn.net")
        hostname = os.environ.get("BUNNY_STORAGE_HOSTNAME", "storage.bunnycdn.com")

        filename = f"reddit_de_{stamp}.mp4"

        with open(str(video_path), "rb") as f:
            r = requests.put(
                f"https://{hostname}/{zone}/queue/{filename}",
                headers={"AccessKey": password, "Content-Type": "video/mp4"},
                data=f, verify=certifi.where(), timeout=300,
            )
        r.raise_for_status()

        meta = {
            "title":     story_data["title"],
            "caption":   full_caption,
            "subreddit": story_data["subreddit"],
            "cdn_url":   f"{cdn_url}/queue/{filename}",
        }
        mr = requests.put(
            f"https://{hostname}/{zone}/queue/{filename.replace('.mp4', '.json')}",
            headers={"AccessKey": password, "Content-Type": "application/json"},
            data=json.dumps(meta, ensure_ascii=False).encode(),
            verify=certifi.where(), timeout=30,
        )
        mr.raise_for_status()

        video_path.unlink(missing_ok=True)  # hochgeladen — lokale Kopie löschen
        logger.info(f"✅  In Queue: {filename}")
        logger.info(f"    Titel: {story_data['title'][:60]}")

        # 6. Teil 2 generieren + hochladen falls vorhanden
        if is_part2_format and story_data.get("part2"):
            logger.info("🎞️   Generiere Teil 2...")
            stamp2 = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
            audio2 = OUTPUT_DIR / f"audio2_{stamp2}.mp3"
            video2 = OUTPUT_DIR / f"video2_{stamp2}.mp4"
            try:
                p2_cta = random.choice([
                    "Folg uns für mehr solche Geschichten jeden Tag!",
                    "Folg uns damit du keine Story mehr verpasst!",
                    "Mehr solche Geschichten? Einfach folgen!",
                ])
                tts2_text = f"Teil 2. {story_data['title']}. {story_data['part2']} {p2_cta}"
                words2 = tts2_text.split()
                if len(words2) > MAX_WORDS:
                    tts2_text = " ".join(words2[:MAX_WORDS])
                    for ec in [". ", "! ", "? "]:
                        idx = tts2_text.rfind(ec)
                        if idx > 50:
                            tts2_text = tts2_text[:idx + 1]
                            break
                _, wt2 = text_to_speech(tts2_text, str(audio2), mood=mood)
                create_video(
                    subreddit=story_data["subreddit"],
                    title=f"{story_data['title']} (Teil 2)",
                    story=story_data["part2"],
                    audio_path=str(audio2),
                    output_path=str(video2),
                    word_timings=wt2,
                    gradient_index=random.randint(0, 4),
                )
                audio2.unlink(missing_ok=True)
                caption2 = (
                    f"{mood_emoji} {description} — Teil 2 👀\n\n"
                    f"{question}\n\n"
                    + " ".join(story_data["hashtags"] + trending)
                )
                fn2 = f"reddit_de_{stamp2}.mp4"
                with open(str(video2), "rb") as f2:
                    requests.put(
                        f"https://{hostname}/{zone}/queue/{fn2}",
                        headers={"AccessKey": password, "Content-Type": "video/mp4"},
                        data=f2, verify=certifi.where(), timeout=300,
                    ).raise_for_status()
                requests.put(
                    f"https://{hostname}/{zone}/queue/{fn2.replace('.mp4', '.json')}",
                    headers={"AccessKey": password, "Content-Type": "application/json"},
                    data=json.dumps({
                        "title":     f"{story_data['title']} (Teil 2)",
                        "caption":   caption2,
                        "subreddit": story_data["subreddit"],
                        "cdn_url":   f"{cdn_url}/queue/{fn2}",
                    }, ensure_ascii=False).encode(),
                    verify=certifi.where(), timeout=30,
                ).raise_for_status()
                video2.unlink(missing_ok=True)
                logger.info(f"✅  Teil 2 in Queue: {fn2}")
            except Exception as e:
                logger.error(f"❌  Teil 2 fehlgeschlagen: {e}", exc_info=True)
            finally:
                audio2.unlink(missing_ok=True)
                video2.unlink(missing_ok=True)

        return True

    finally:
        # Safety-Net: Temp-Dateien immer löschen, auch wenn ein Schritt crasht
        audio_path.unlink(missing_ok=True)
        video_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import concurrent.futures
    _cleanup_stale_files()

    subreddit = sys.argv[1] if len(sys.argv) > 1 else None
    count     = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    workers   = min(count, int(sys.argv[3]) if len(sys.argv) > 3 else 3)

    done = []

    def _task(i):
        if count > 1:
            logger.info(f"\n{'='*50}\nVideo {i+1}/{count}\n{'='*50}")
        if generate_and_queue(subreddit):
            done.append(1)

    if workers > 1 and count > 1:
        logger.info(f"🚀  Parallel: {count} Videos × {workers} Workers")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_task, range(count)))
    else:
        for i in range(count):
            _task(i)

    logger.info(f"\n🏁  Fertig: {len(done)}/{count} Videos in Bunny-Queue")
