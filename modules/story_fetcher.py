"""
Reddit Story Fetcher — Deutsch
-------------------------------
Fetched Reddit-Storys via Public JSON API (kein API-Key nötig),
kondensiert auf max. 125 Wörter für TikTok via Claude — auf Deutsch.
"""

import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path


def _extract_json_fields(text: str) -> dict:
    """Extrahiert JSON-Felder robust mit Regex — Fallback wenn json.loads scheitert."""
    def extract(key: str) -> str:
        # Suche nach "key": "..." — toleriert unescapte Zeichen bis zum nächsten Feld
        pattern = rf'"{key}"\s*:\s*"([\s\S]*?)"(?:\s*[,}}])'
        m = re.search(pattern, text)
        if m:
            return m.group(1).replace('\\"', '"').replace('\\n', '\n')
        # Fallback ohne trailing delimiter
        pattern2 = rf'"{key}"\s*:\s*"([\s\S]+)"'
        m2 = re.search(pattern2, text)
        return m2.group(1).replace('\\"', '"').replace('\\n', '\n') if m2 else ""
    return {
        "title":       extract("title"),
        "story":       extract("story"),
        "description": extract("description"),
    }

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [story_fetcher] %(message)s", force=True)
_log = logging.getLogger("story_fetcher")

_generation_lock = threading.Lock()

_CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

SUBREDDITS = [
    # ─── AITA / Judgment (Gen Z Liebling) ────────────────────────────────────
    "AmItheAsshole",
    "AITAH",
    "AmIOverreacting",
    # ─── Fail / Cringe / Lustig ───────────────────────────────────────────────
    "tifu",
    "mildlyinfuriating",    # Riesige Gen-Z-Community — extrem relatable
    "facepalm",             # Cringe-Momente — viral unter 16–25
    "Unexpected",           # Kurze überraschende Storys — sehr shareable
    # ─── Beziehung / Dating (junge Zielgruppe) ────────────────────────────────
    "relationship_advice",
    "breakups",             # Sehr relevant 16–25 — erste Trennungen
    "confessions",
    # ─── Jugend / Schule / Uni ────────────────────────────────────────────────
    "teenagers",            # Direkte Gen-Z-Zielgruppe
    "college",              # Studenten-Drama — 18–24
    "TwoHotTakes",          # Bereits viral, jüngeres Publikum
    # ─── Rache / Karma ───────────────────────────────────────────────────────
    "pettyrevenge",
    "maliciouscompliance",
    "ProRevenge",
    # ─── Drama / Entitled ────────────────────────────────────────────────────
    "entitledparents",
    "entitledpeople",
    "ChoosingBeggars",
    "offmychest",
    "TrueOffMyChest",
    # ─── Familie / Toxisch ───────────────────────────────────────────────────
    "raisedbynarcissists",  # Sehr stark bei Gen Z — verarbeitung toxischer Kindheit
    # ─── Updates / Auflösungen ────────────────────────────────────────────────
    "BestofRedditorUpdates",
]

_USED_IDS_FILE = Path(__file__).parent.parent / "output" / "used_posts.json"

_HASHTAG_CORE = ["#fyp", "#reddit", "#tiktokdeutsch"]

_SUBREDDIT_HASHTAGS: dict[str, list[str]] = {
    "AmItheAsshole":        ["#aita", "#drama", "#beziehung", "#meinung", "#aitatiktok", "#aitareddit"],
    "AITAH":                ["#aita", "#drama", "#beziehung", "#meinung", "#aitatiktok", "#aitareddit"],
    "AmIOverreacting":      ["#aita", "#drama", "#beziehung", "#meinung", "#redditdeutsch"],
    "tifu":                 ["#fail", "#lustig", "#peinlich", "#oops", "#storytime"],
    "mildlyinfuriating":    ["#nervig", "#cringe", "#relatable", "#drama", "#genzde"],
    "facepalm":             ["#cringe", "#facepalm", "#lustig", "#fremdschämen", "#drama"],
    "Unexpected":           ["#unexpected", "#überraschung", "#wow", "#schockierend", "#viral"],
    "relationship_advice":  ["#beziehung", "#liebe", "#drama", "#rat", "#dating"],
    "breakups":             ["#trennung", "#herzschmerz", "#liebe", "#drama", "#relatable"],
    "confessions":          ["#geständnis", "#geheimnis", "#anonym", "#wahregeschichte", "#schockierend"],
    "teenagers":            ["#teenager", "#jugend", "#genz", "#schule", "#drama"],
    "college":              ["#uni", "#studium", "#genz", "#drama", "#campusleben"],
    "TwoHotTakes":          ["#twohotttakes", "#drama", "#meinung", "#beziehung", "#viral"],
    "pettyrevenge":         ["#rache", "#satisfying", "#karma", "#gerechtigkeit", "#storytime"],
    "maliciouscompliance":  ["#rache", "#satisfying", "#clever", "#karma", "#arbeit"],
    "ProRevenge":           ["#rache", "#satisfying", "#gerechtigkeit", "#karma", "#epic"],
    "entitledparents":      ["#eltern", "#drama", "#cringe", "#nein", "#storytime"],
    "entitledpeople":       ["#dreist", "#karen", "#drama", "#cringe", "#redditdeutsch"],
    "ChoosingBeggars":      ["#choosingbeggars", "#dreistigkeit", "#drama", "#cringe", "#nope"],
    "offmychest":           ["#wahregeschichte", "#geständnis", "#emotional", "#anonym", "#storytime"],
    "TrueOffMyChest":       ["#wahregeschichte", "#geständnis", "#emotional", "#anonym", "#storytime"],
    "raisedbynarcissists":  ["#narzisst", "#toxisch", "#family", "#drama", "#heilung"],
    "BestofRedditorUpdates":["#update", "#redditstories", "#drama", "#befriedigung", "#wahregeschichte"],
}

_HASHTAG_REACH = [
    "#viral", "#foryou", "#foryoupage", "#redditstories", "#redditdeutsch",
    "#wahregeschichte", "#schockierend", "#unglaublich", "#relatable",
    "#redtok", "#aitareddit", "#deutsch", "#redditgeschichte", "#krass",
]

_HEADERS = {
    "User-Agent": "reddit-story-bot/1.0",
}

_PULLPUSH_URL = "https://api.pullpush.io/reddit/search/submission/"


def _load_used_ids() -> set:
    try:
        if _USED_IDS_FILE.exists():
            return set(json.loads(_USED_IDS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def _save_used_id(post_id: str):
    try:
        _USED_IDS_FILE.parent.mkdir(exist_ok=True, parents=True)
        ids      = _load_used_ids()
        ids.add(post_id)
        ids_list = list(ids)[-500:]
        _USED_IDS_FILE.write_text(json.dumps(ids_list, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _get_hashtags(subreddit: str) -> list[str]:
    topic_tags = list(_SUBREDDIT_HASHTAGS.get(subreddit, ["#reddit", "#storytime", "#drama"]))
    random.shuffle(topic_tags)
    reach_pool = [t for t in _HASHTAG_REACH if t not in topic_tags and t not in _HASHTAG_CORE]
    random.shuffle(reach_pool)
    return _HASHTAG_CORE + topic_tags[:4] + reach_pool[:2]


def _fetch_reddit_posts(subreddit: str, sort: str = "hot") -> list[dict]:
    """Holt Posts über Pullpush.io — umgeht Reddits Datacenter-IP-Sperren."""
    params = {
        "subreddit": subreddit,
        "is_self": "true",
        "size": 50,
    }
    try:
        resp = requests.get(_PULLPUSH_URL, headers=_HEADERS, params=params, timeout=20)
        _log.info(f"Pullpush HTTP {resp.status_code} für r/{subreddit}")
        resp.raise_for_status()
        posts = resp.json().get("data", [])
        _log.info(f"Pullpush lieferte {len(posts)} Posts für r/{subreddit}")
        return posts
    except Exception as e:
        _log.warning(f"Pullpush API Fehler ({subreddit}): {e}")
        return []


def _llm_call(prompt: str, max_tokens: int = 1800) -> str:
    """Ruft Anthropic auf — fällt auf OpenAI GPT-4o-mini zurück wenn Credits aufgebraucht."""
    import anthropic as _anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        try:
            client = _anthropic.Anthropic(api_key=anthropic_key)
            msg = client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except _anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                import logging
                logging.getLogger("redditbot-de").warning("[llm] Anthropic Credits aufgebraucht — OpenAI Fallback")
            else:
                raise
    import openai
    oai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not oai_key:
        raise RuntimeError("Weder Anthropic noch OpenAI API-Key verfügbar")
    oai = openai.OpenAI(api_key=oai_key)
    resp = oai.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _adapt_for_tiktok_de(title: str, text: str, subreddit: str) -> dict:
    """Bereitet die Story für TikTok auf — vollständig, auf Deutsch.
    Bei langen Posts (>500 Wörter) wird part1 + part2 für zwei Videos zurückgegeben."""

    _is_long = len(text.split()) > 500

    if _is_long:
        prompt = f"""Du bist ein viraler TikTok-Content-Creator für deutsches Publikum (Zielgruppe: 16–25 Jahre), spezialisiert auf Reddit-Story-Videos.

Subreddit: r/{subreddit}
Post-Titel: {title}
Story-Text:
{text[:6000]}

Diese Story ist LANG — teile sie in ZWEI aufeinanderfolgende TikToks auf, um maximales Engagement und Follows zu erzeugen.

**Teil 1 (~65 Wörter):**
- Beginne mit einem SCROLL-STOPPING ersten Satz — schreibe den tatsächlich schockierenden/emotionalen Inhalt, NICHT "das glaubst du nicht"
- Baue die Story auf, steigere die Spannung
- Ende mit einem DRAMATISCHEN Cliffhanger — dem spannendsten möglichen Stopppunkt
- Letzter Satz treibt Follows: z.B. "Teil 2 kommt morgen..." oder "Folge mir, um das Ende zu sehen..."

**Teil 2 (~200 Wörter):**
- Führe direkt vom Cliffhanger aus Teil 1 fort
- Alle wichtigen Details, Wendungen und die vollständige Auflösung
- Schließe mit einem befriedigenden, emotional resonanten Ende

**Titel** (max. 8 Wörter): Schockierende Aussage oder Frage — wenn möglich in der Ich-Perspektive. Beispiele: "Mein Mann hat mich 7 Jahre belogen", "Ich flog raus — wegen meiner besten Freundin"

**Beschreibung** (1-2 Sätze): Erzeuge FOMO. Mach Zuschauer neugierig, dass sie UNBEDINGT schauen müssen.

Antworte NUR mit diesem JSON (kein Markdown, kein Extra-Text):
{{
  "title": "Schockierender Titel (max. 8 Wörter, Deutsch)",
  "part1": "Teil 1 (~65 Wörter, endet mit Cliffhanger, Deutsch)",
  "part2": "Teil 2 (~200 Wörter, vollständige Auflösung, Deutsch)",
  "description": "TikTok-Beschreibung mit FOMO (1-2 Sätze, Deutsch)"
}}"""
    else:
        prompt = f"""Du bist ein viraler TikTok-Content-Creator für deutsches Publikum (Zielgruppe: 16–25 Jahre), spezialisiert auf Reddit-Story-Videos.

Subreddit: r/{subreddit}
Post-Titel: {title}
Story-Text:
{text[:6000]}

Deine Aufgabe:
1. SCROLL-STOPPING erster Satz — schreibe den tatsächlich schockierenden/emotionalen Inhalt. NICHT "das glaubst du nicht" — schreibe das, was jemanden wirklich stoppt. Beispiel: "Mein Mann hat mir nach 7 Jahren erzählt, unsere Ehe war nur ein Geschäftsarrangement — an unserem Hochzeitstag."
2. Erzähle die Story in KURZEN, knackigen Sätzen. Baue Spannung Schritt für Schritt auf. Alle wichtigen Details, Wendungen und das Ende (max. 350 Wörter).
3. Kürze nur echte Wiederholungen — die Geschichte muss vollständig und befriedigend sein.
4. TikTok-Titel (max. 8 Wörter, Deutsch): Schockierende Aussage oder Frage, wenn möglich Ich-Perspektive. KEINE Zusammenfassung — emotional/rätselhaft.
5. TikTok-Beschreibung (1-2 Sätze, Deutsch, 1-2 Emojis): Erzeuge FOMO, mach Zuschauer neugierig.

Antworte NUR mit diesem JSON-Format (kein Markdown, kein Extra-Text):
{{
  "title": "Schockierender/rätselhafter Titel (max. 8 Wörter, Deutsch)",
  "story": "Die vollständige Story (max. 350 Wörter, Deutsch)",
  "description": "FOMO-erzeugende Beschreibung (1-2 Sätze, Deutsch)"
}}"""

    raw   = _llm_call(prompt, max_tokens=1800)
    match = re.search(r'\{[\s\S]*\}', raw)
    raw   = match.group(0) if match else raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: Felder einzeln per Regex extrahieren — robust gegen unescapte Sonderzeichen
        data = _extract_json_fields(raw)
        if not data.get("story") and not data.get("part1"):
            raise RuntimeError(f"Claude-Antwort konnte nicht geparst werden: {raw[:200]}")

    if _is_long:
        # Normalisieren: part1 → story; Wortgrenzen pro Teil einhalten
        part1 = data.get("part1", "")
        part2 = data.get("part2", "")

        p1_words = part1.split()
        if len(p1_words) > 80:
            part1 = " ".join(p1_words[:80])
            for ec in [". ", "! ", "? "]:
                idx = part1.rfind(ec)
                if idx > 20:
                    part1 = part1[:idx + 1]
                    break

        p2_words = part2.split()
        if len(p2_words) > 220:
            part2 = " ".join(p2_words[:220])
            for ec in [". ", "! ", "? "]:
                idx = part2.rfind(ec)
                if idx > 50:
                    part2 = part2[:idx + 1]
                    break

        data["story"] = part1
        data["part2"] = part2
    else:
        words = data.get("story", "").split()
        if len(words) > 360:
            data["story"] = " ".join(words[:360])
            last_end = max(data["story"].rfind(". "), data["story"].rfind("! "), data["story"].rfind("? "))
            if last_end > 50:
                data["story"] = data["story"][:last_end + 1]

    return data


def fetch_story(subreddit_override: str = None) -> dict:
    """
    Holt eine passende Reddit-Story und gibt sie TikTok-fertig zurück.
    Nutzt die öffentliche Reddit JSON API — kein API-Key nötig.
    Thread-safe: Lock nur um Datei-I/O, nicht um LLM-Calls.
    """
    with _generation_lock:
        used_ids = _load_used_ids()
        subreddit_name = subreddit_override or random.choice(SUBREDDITS)

    for attempt in range(len(SUBREDDITS)):
        sort  = "hot" if random.random() < 0.6 else "top"
        posts = _fetch_reddit_posts(subreddit_name, sort)
        time.sleep(0.5)

        with _generation_lock:
            used_ids = _load_used_ids()

        candidates = [
            p for p in posts
            if not p.get("stickied", False)
            and p.get("is_self", False)
            and p.get("id") not in used_ids
            and len(p.get("selftext", "")) >= 300
            and p.get("selftext", "") not in ["[removed]", "[deleted]", ""]
            and len(p.get("selftext", "")) <= 8000
        ]

        _log.info(f"r/{subreddit_name}: {len(posts)} Posts → {len(candidates)} Kandidaten")
        if candidates:
            post = random.choice(candidates[:15])
            _log.info(f"Post gewählt: r/{subreddit_name} — {post['title'][:60]}")
            adapted = _adapt_for_tiktok_de(post["title"], post["selftext"], subreddit_name)
            with _generation_lock:
                _save_used_id(post["id"])
            result = {
                "title":       adapted["title"],
                "story":       adapted["story"],
                "description": adapted.get("description", adapted["title"]),
                "hashtags":    _get_hashtags(subreddit_name),
                "subreddit":   subreddit_name,
                "post_id":     post["id"],
            }
            if adapted.get("part2"):
                result["part2"] = adapted["part2"]
            return result

        _log.info(f"Keine passenden Posts in r/{subreddit_name} — versuche nächsten")
        subreddit_name = random.choice(SUBREDDITS)

    raise RuntimeError("Kein passender Reddit-Post nach mehreren Versuchen gefunden")
