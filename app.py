# -*- coding: utf-8 -*-
import os
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gradio as gr
from faster_whisper import WhisperModel

from corrections import (
    ensure_user_data,
    load_enabled_dictionary_files,
    import_dictionary_file,
    save_glossary_text,
    save_rules_text,
    add_rule_pair,
    apply_corrections_to_segments,
)

# --- OPTIONAL: diarization (pyannote) ---
try:
    from pyannote.audio import Pipeline  # type: ignore
    _PYANNOTE_OK = True
except Exception:
    Pipeline = None
    _PYANNOTE_OK = False

# --- OPTIONAL: OpenAI translation ---
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_OK = True
except Exception:
    OpenAI = None
    _OPENAI_OK = False

# --- OPTIONAL: Argos Translate (offline fallback) ---
try:
    from argostranslate import translate as argos_translate  # type: ignore
    _ARGOS_OK = True
except Exception:
    argos_translate = None
    _ARGOS_OK = False

APP_DIR = Path(__file__).resolve().parent
USER_DATA = APP_DIR / "user_data"
TMP_DIR = APP_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

MAX_AUDIO_SECONDS = 3600  # 1 oră
PREVIEW = 15000  # limită preview UI (download = complet)

FOOTER_FILE = USER_DATA / "footer.md"
DEFAULT_FOOTER = "Parlamentul Republicii Moldova © 2026"


# -------- Utils --------
def _sec_to_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000.0))
    h = ms // 3600000
    ms -= h * 3600000
    m = ms // 60000
    ms -= m * 60000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: List[Dict]) -> str:
    out = []
    for i, seg in enumerate(segments, start=1):
        start = _sec_to_srt_time(float(seg.get("start", 0.0)))
        end = _sec_to_srt_time(float(seg.get("end", 0.0)))
        text = (seg.get("text") or "").strip()
        out.append(str(i))
        out.append(f"{start} --> {end}")
        out.append(text)
        out.append("")
    return "\n".join(out).strip() + "\n"


def segments_to_txt(segments: List[Dict]) -> str:
    return "\n".join([(seg.get("text") or "").strip() for seg in segments]).strip() + "\n"


def _estimate_duration_seconds(audio_path: str) -> Optional[float]:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            audio_path,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if p.returncode == 0:
            val = p.stdout.strip()
            if val:
                return float(val)
    except Exception:
        return None
    return None


def _make_model(model_name: str, device: str, compute_type: str):
    key = (model_name, device, compute_type)
    if not hasattr(_make_model, "_cache"):
        _make_model._cache = {}
    cache = _make_model._cache
    if key in cache:
        return cache[key]
    cache.clear()
    m = WhisperModel(model_name, device=device, compute_type=compute_type)
    cache[key] = m
    return m


def _progress_cb(progress: gr.Progress, done: float, total: float, t0: float):
    if total <= 0:
        progress(0.0, desc="Procesez...")
        return
    frac = max(0.0, min(1.0, done / total))
    elapsed = max(0.001, time.time() - t0)
    speed = done / elapsed
    remaining = (total - done) / speed if speed > 1e-6 else None
    eta = ""
    if remaining is not None and remaining < 10**9:
        eta = f" | ETA ~ {int(remaining)}s"
    progress(frac, desc=f"Progres: {int(frac*100)}%{eta}")


def _load_footer_text() -> str:
    ensure_user_data(USER_DATA)
    if FOOTER_FILE.exists():
        return FOOTER_FILE.read_text(encoding="utf-8", errors="ignore").strip() or DEFAULT_FOOTER
    return DEFAULT_FOOTER


def _save_footer_text(txt: str) -> str:
    ensure_user_data(USER_DATA)
    FOOTER_FILE.write_text((txt or DEFAULT_FOOTER).strip() + "\n", encoding="utf-8")
    return (txt or DEFAULT_FOOTER).strip()


# -------- FFmpeg helpers (NEW: robust, no-cut, no-phase-cancel) --------
def _ensure_ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False)
        subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, check=False)
    except Exception:
        raise gr.Error("FFmpeg/FFprobe nu sunt disponibile. Instalează FFmpeg și pune-l în PATH.")


def _mean_volume_db(path: str) -> float:
    # cu cât e mai aproape de 0 (mai puțin negativ), cu atât e “mai tare”
    p = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "NUL"],
        capture_output=True,
        text=True,
        check=False,
    )
    txt = (p.stderr or "")
    for line in txt.splitlines():
        line = line.strip()
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split(" dB")[0].strip())
            except Exception:
                pass
    return -9999.0


def _convert_to_wav_best_channel(src_path: str) -> str:
    """
    Convertește sursa la WAV 16k mono alegând canalul (L/R) cu voce mai “tare”.
    Asta evită situația când downmix-ul la mono îți anulează vocea și Whisper repetă/halucinează.
    """
    _ensure_ffmpeg_available()
    ts = int(time.time() * 1000)
    left_wav = str(TMP_DIR / f"input_{ts}_L.wav")
    right_wav = str(TMP_DIR / f"input_{ts}_R.wav")

    cmdL = [
        "ffmpeg", "-y", "-i", src_path, "-vn", "-map", "0:a:0",
        "-af", "pan=mono|c0=FL", "-ar", "16000", "-acodec", "pcm_s16le", left_wav
    ]
    cmdR = [
        "ffmpeg", "-y", "-i", src_path, "-vn", "-map", "0:a:0",
        "-af", "pan=mono|c0=FR", "-ar", "16000", "-acodec", "pcm_s16le", right_wav
    ]

    pL = subprocess.run(cmdL, capture_output=True, text=True, check=False)
    pR = subprocess.run(cmdR, capture_output=True, text=True, check=False)

    okL = (pL.returncode == 0 and os.path.exists(left_wav))
    okR = (pR.returncode == 0 and os.path.exists(right_wav))

    if not okL and not okR:
        err = ((pL.stderr or "") + "\n" + (pR.stderr or "")).strip()
        raise gr.Error("Eroare FFmpeg la conversie audio->wav.\n" + err[-1200:])

    candidates = []
    if okL:
        candidates.append((_mean_volume_db(left_wav), left_wav))
    if okR:
        candidates.append((_mean_volume_db(right_wav), right_wav))
    candidates.sort(reverse=True)  # volum mai mare primul

    return candidates[0][1]


# -------- Traduce (OpenAI + Argos fallback) --------
_LANG_MAP = {
    "română": "română",
    "engleză": "engleză",
    "rusă": "rusă",
    "franceză": "franceză",
    "germană": "germană",
    "italiană": "italiană",
    "spaniolă": "spaniolă",
}

# coduri ISO pentru Argos
_LANG_CODE = {
    "română": "ro",
    "engleză": "en",
    "rusă": "ru",
    "franceză": "fr",
    "germană": "de",
    "italiană": "it",
    "spaniolă": "es",
}


def _translate_with_openai_safe(text: str, target_lang: str, api_key: str, model_name: str) -> Tuple[str, str]:
    """
    Încearcă traducere cu OpenAI.
    NU aruncă excepție: dacă nu se poate, returnează textul original și status.
    """
    if not text.strip():
        return text, "OpenAI: nimic de tradus."

    if not _OPENAI_OK:
        return text, "OpenAI: librăria openai nu e instalată (skip)."

    api_key = (api_key or "").strip()
    if not api_key:
        return text, "OpenAI: lipsește API key (skip)."

    try:
        client = OpenAI(api_key=api_key)

        lang = _LANG_MAP.get(target_lang, target_lang)
        prompt = (
            f"Tradu textul de mai jos în limba {lang}.\n"
            f"Păstrează structura pe linii/paragrafe.\n"
            f"Nu adăuga explicații.\n\n"
            f"TEXT:\n{text}"
        )

        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Ești un traducător profesionist."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        out = (resp.choices[0].message.content or "").strip()
        if not out:
            return text, "OpenAI: răspuns gol (skip)."

        return out, f"OpenAI: traducere OK (model={model_name})."

    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "Error code: 429" in msg:
            return text, "OpenAI: quota depășită / fără credit."
        if "invalid_api_key" in msg or "Error code: 401" in msg:
            return text, "OpenAI: API key invalid."
        return text, f"OpenAI: eroare ({type(e).__name__})."


def _translate_with_argos(text: str, target_lang: str, source_lang_ui: Optional[str]) -> Tuple[str, str]:
    """
    Traducere offline cu Argos Translate.
    Dacă nu se poate, returnează textul original și status.
    """
    if not text.strip():
        return text, "Argos: nimic de tradus."

    if not _ARGOS_OK:
        return text, "Argos: librăria argostranslate nu e instalată (skip)."

    to_code = _LANG_CODE.get(target_lang)
    if not to_code:
        return text, f"Argos: limba țintă necunoscută: {target_lang} (skip)."

    # dacă utilizatorul a ales limba transcrierii (ro/en/ru), o folosim; altfel ro implicit
    from_code = _LANG_CODE.get(source_lang_ui) if source_lang_ui else None
    if not from_code:
        from_code = "ro"

    try:
        out = argos_translate.translate(text, from_code, to_code)
        out = (out or "").strip()
        if not out:
            return text, "Argos: răspuns gol (skip)."
        return out, f"Argos: traducere OK ({from_code}->{to_code})."
    except Exception as e:
        return text, f"Argos: eroare ({type(e).__name__}) (skip)."


# -------- Diarization (pyannote) --------
_DIAR_PIPE = None


def _get_diar_pipeline():
    global _DIAR_PIPE
    if not _PYANNOTE_OK:
        raise gr.Error("Diarizarea nu este disponibilă (pyannote.audio nu este instalat).")
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise gr.Error('Setează HF_TOKEN (Hugging Face). Exemplu: export HF_TOKEN="hf_...."')
    if _DIAR_PIPE is None:
        _DIAR_PIPE = Pipeline.from_pretrained(
            "pyannote-community/speaker-diarization-community-1",
            token=token,
        )
    return _DIAR_PIPE


def _segments_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    left = max(a0, b0)
    right = min(a1, b1)
    return max(0.0, right - left)


def _apply_diarization_to_segments(audio_path: str, segments: List[Dict]) -> List[Dict]:
    """
    Returnează segmente cu cheie 'speaker' setată la "Vorbitor N".
    Compatibil pyannote.audio v3 (Annotation) și v4+ (DiarizeOutput).
    """
    pipe = _get_diar_pipeline()
    diar_out = pipe(audio_path)

    diar = getattr(diar_out, "speaker_diarization", diar_out)

    diar_turns: List[Tuple[float, float, str]] = []
    for turn, _, label in diar.itertracks(yield_label=True):
        diar_turns.append((float(turn.start), float(turn.end), str(label)))

    speaker_map: Dict[str, str] = {}
    next_id = 1

    out: List[Dict] = []
    for seg in segments:
        s0 = float(seg.get("start", 0.0))
        s1 = float(seg.get("end", 0.0))

        best_label = None
        best_ov = 0.0
        for d0, d1, lab in diar_turns:
            ov = _segments_overlap(s0, s1, d0, d1)
            if ov > best_ov:
                best_ov = ov
                best_label = lab

        if best_label is None:
            speaker = "Vorbitor 1"
        else:
            if best_label not in speaker_map:
                speaker_map[best_label] = f"Vorbitor {next_id}"
                next_id += 1
            speaker = speaker_map[best_label]

        seg2 = dict(seg)
        seg2["speaker"] = speaker
        out.append(seg2)

    return out


# -------- Core --------
def ui_transcribe(
    audio_file,
    model_name: str,
    beam_size: int,
    language: str,
    device: str,
    compute_type: str,
    do_autocorrect: bool,
    do_rules: bool,
    speaker_prefix: str,
    do_diarize: bool,
    do_translate: bool,
    translate_target_lang: str,
    openai_api_key: str,
    openai_model: str,
    progress=gr.Progress(track_tqdm=False),
):
    ensure_user_data(USER_DATA)

    if audio_file is None:
        raise gr.Error("Încarcă un fișier audio/video.")

    if isinstance(audio_file, dict) and "path" in audio_file:
        audio_path = audio_file["path"]
    else:
        audio_path = str(audio_file)

    if not os.path.exists(audio_path):
        raise gr.Error("Nu găsesc fișierul încărcat pe disc.")

    dur_src = _estimate_duration_seconds(audio_path)
    if dur_src is not None and dur_src > MAX_AUDIO_SECONDS:
        raise gr.Error(f"Fișier prea lung: {int(dur_src)}s. Maxim permis: {MAX_AUDIO_SECONDS}s (1 oră).")

    model = _make_model(model_name, device=device, compute_type=compute_type)

    t0 = time.time()
    progress(0.0, desc="Pregătesc audio (WAV safe)...")

    # NEW: convertim la WAV safe (alege canalul cu voce mai bună, evită anularea stereo)
    wav_path = _convert_to_wav_best_channel(audio_path)

    dur = _estimate_duration_seconds(wav_path)
    if dur is not None and dur > MAX_AUDIO_SECONDS:
        raise gr.Error(f"Fișier prea lung: {int(dur)}s. Maxim permis: {MAX_AUDIO_SECONDS}s (1 oră).")

    progress(0.05, desc="Pornesc transcrierea (fără VAD)...")
    segments_out: List[Dict] = []

    total = dur if dur is not None else 0.0
    done = 0.0

    # NEW: vad_filter=False -> nu taie nimic
    # NEW: anti-repetiție (dacă versiunea ta suportă parametrii)
    try:
        seg_iter, _info = model.transcribe(
            wav_path,
            language=(language or None),
            beam_size=int(beam_size),
            vad_filter=False,
            temperature=0.0,
            condition_on_previous_text=False,
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
        )
    except TypeError:
        seg_iter, _info = model.transcribe(
            wav_path,
            language=(language or None),
            beam_size=int(beam_size),
            vad_filter=False,
            temperature=0.0,
            condition_on_previous_text=False,
        )

    for seg in seg_iter:
        d = {"start": float(seg.start), "end": float(seg.end), "text": (seg.text or "").strip()}
        segments_out.append(d)

        if total > 0:
            done = max(done, float(seg.end))
            _progress_cb(progress, done, total, t0)

    # NEW: elimină duplicate consecutive (reduce “fraze repetate”)
    dedup: List[Dict] = []
    prev = None
    for s in segments_out:
        t = (s.get("text") or "").strip()
        if not t:
            continue
        if t != prev:
            dedup.append(s)
        prev = t
    segments_out = dedup

    # diarizare (opțional) - IMPORTANT: pe wav_path (stabil)
    if do_diarize:
        progress(0.95, desc="Diarizare (pyannote)...")
        segments_out = _apply_diarization_to_segments(wav_path, segments_out)
        for s in segments_out:
            spk = s.get("speaker", "").strip()
            if spk:
                s["text"] = f"{spk}: {s['text']}"

        # NEW: încă o deduplicare după prefix speaker (utile la formule repetitive)
        dedup2: List[Dict] = []
        prev2 = None
        for s in segments_out:
            t = (s.get("text") or "").strip()
            if not t:
                continue
            if t != prev2:
                dedup2.append(s)
            prev2 = t
        segments_out = dedup2

    progress(0.98, desc="Corectare text...")

    # Prefix manual (doar dacă NU e diarizare)
    if (not do_diarize) and speaker_prefix and speaker_prefix != "(fără)":
        pref = speaker_prefix.strip()
        for s in segments_out:
            s["text"] = f"{pref}: {s['text']}"

    raw_segments = segments_out

    corr_segments = apply_corrections_to_segments(
        raw_segments,
        user_data_dir=USER_DATA,
        enable_dict_autocorrect=do_autocorrect,
        enable_rules=do_rules,
    )

    raw_txt = segments_to_txt(raw_segments)
    raw_srt = segments_to_srt(raw_segments)
    corr_txt = segments_to_txt(corr_segments)
    corr_srt = segments_to_srt(corr_segments)

    # ---- Traducere: OpenAI -> dacă eșuează -> Argos offline ----
    openai_status = ""
    argos_status = ""

    if do_translate:
        progress(0.99, desc="Traducere (OpenAI / Argos fallback)...")

        api_key = (openai_api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()

        # 1) încearcă OpenAI
        translated, openai_status = _translate_with_openai_safe(
            corr_txt, translate_target_lang, api_key, openai_model
        )

        # 2) dacă OpenAI n-a tradus (a întors textul original), încearcă Argos
        if translated == corr_txt:
            translated2, argos_status = _translate_with_argos(
                corr_txt, translate_target_lang, source_lang_ui=(language or "ro")
            )
            corr_txt = translated2
        else:
            corr_txt = translated

    progress(1.0, desc="Finalizez fișierele...")

    out_dir = USER_DATA / "outputs"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    raw_txt_path = out_dir / f"transcript_raw_{ts}.txt"
    raw_srt_path = out_dir / f"transcript_raw_{ts}.srt"
    corr_txt_path = out_dir / f"transcript_corrected_{ts}.txt"
    corr_srt_path = out_dir / f"transcript_corrected_{ts}.srt"
    raw_txt_path.write_text(raw_txt, encoding="utf-8")
    raw_srt_path.write_text(raw_srt, encoding="utf-8")
    corr_txt_path.write_text(corr_txt, encoding="utf-8")
    corr_srt_path.write_text(corr_srt, encoding="utf-8")

    prev_raw_txt = raw_txt[:PREVIEW]
    prev_raw_srt = raw_srt[:PREVIEW]
    prev_corr_txt = corr_txt[:PREVIEW]
    prev_corr_srt = corr_srt[:PREVIEW]

    meta = []
    meta.append(f"Model: {model_name} | beam={beam_size} | lang={language or 'auto'} | device={device} | compute={compute_type}")
    if dur_src is not None:
        meta.append(f"Durată sursă: {dur_src:.1f}s")
    if dur is not None:
        meta.append(f"Durată WAV (transcris complet): {dur:.1f}s")
    meta.append(f"Segmente: {len(raw_segments)}")
    meta.append("VAD: OFF (nu taie nimic)")
    meta.append("Anti-repetiție: ON (condition_on_previous_text=False + dedup)")
    if do_diarize:
        meta.append("Diarizare: ON (pyannote)")
    if do_translate:
        meta.append(f"Traducere: ON | țintă={translate_target_lang} | OpenAI model={openai_model}")
        if openai_status:
            meta.append(openai_status)
        if argos_status:
            meta.append(argos_status)
    meta.append(f"Preview UI limit: {PREVIEW} caractere (download = complet).")
    meta_text = "\n".join(meta)

    return (
        prev_raw_txt, prev_raw_srt, str(raw_txt_path), str(raw_srt_path),
        prev_corr_txt, prev_corr_srt, str(corr_txt_path), str(corr_srt_path),
        meta_text
    )


# ---------- Învățare ----------
def ui_reload_learning():
    ensure_user_data(USER_DATA)
    glossary = (USER_DATA / "glossary.txt").read_text(encoding="utf-8") if (USER_DATA / "glossary.txt").exists() else ""
    rules = (USER_DATA / "rules.txt").read_text(encoding="utf-8") if (USER_DATA / "rules.txt").exists() else ""
    dicts = load_enabled_dictionary_files(USER_DATA)
    dicts_text = "\n".join(dicts) if dicts else "(nu există încă dicționare)"
    footer = _load_footer_text()
    return glossary, rules, dicts_text, footer


def ui_save_glossary(glossary_text: str):
    ensure_user_data(USER_DATA)
    save_glossary_text(USER_DATA, glossary_text or "")
    return glossary_text


def ui_save_rules(rules_text: str):
    ensure_user_data(USER_DATA)
    save_rules_text(USER_DATA, rules_text or "")
    return rules_text


def ui_import_dict(file_obj):
    ensure_user_data(USER_DATA)
    if file_obj is None:
        raise gr.Error("Încarcă un fișier .txt (1 termen / linie).")
    src = file_obj["path"] if isinstance(file_obj, dict) else str(file_obj)
    import_dictionary_file(USER_DATA, src)
    dicts = load_enabled_dictionary_files(USER_DATA)
    return "\n".join(dicts) if dicts else "(nu există încă dicționare)"


def ui_add_rule(wrong: str, right: str, also_gloss: bool, existing_rules: str):
    ensure_user_data(USER_DATA)
    wrong = (wrong or "").strip()
    right = (right or "").strip()
    if not wrong or not right:
        raise gr.Error("Completează Greșit și Corect.")
    add_rule_pair(USER_DATA, wrong, right)

    if also_gloss:
        gloss_path = USER_DATA / "glossary.txt"
        gloss = gloss_path.read_text(encoding="utf-8") if gloss_path.exists() else ""
        lines = [l.strip() for l in gloss.splitlines() if l.strip()]
        if right not in lines:
            lines.append(right)
            gloss_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rules_text = (USER_DATA / "rules.txt").read_text(encoding="utf-8") if (USER_DATA / "rules.txt").exists() else ""
    return "", "", rules_text


# ---------- UI ----------
def build_ui():
    ensure_user_data(USER_DATA)

    model_choices = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
    speaker_choices = ["(fără)"] + [f"Vorbitor {i}" for i in range(1, 2)]

    css = """
    .btn-fullwidth button { width: 100% !important; }
    footer { display: none !important; }
    """

    with gr.Blocks(title="Whisper SRT GUI (Simplu)", css=css) as demo:
        gr.Markdown("### Elaborat de Direcția Tehnologii Informaționale și Comunicații\n")

        with gr.Tabs():
            with gr.Tab("Transcriere"):
                audio = gr.File(label="Audio/Video (mp3/mp4/wav/m4a) — până la 1 oră", file_types=["audio", "video"])

                with gr.Row():
                    model_name = gr.Dropdown(label="Model Whisper", choices=model_choices, value="large-v3")
                    language = gr.Dropdown(label="Limba (gol = auto)", choices=["", "ro", "en", "ru"], value="ro")

                with gr.Row():
                    beam = gr.Slider(label="Beam size (calitate vs viteză)", minimum=1, maximum=16, step=1, value=16)
                    device = gr.Dropdown(label="Device", choices=["cpu", "cuda"], value="cuda")
                    compute = gr.Dropdown(label="Compute type", choices=["int8", "int8_float16", "float16", "float32"], value="float32")

                with gr.Row():
                    do_autocorrect = gr.Checkbox(label="Autocorrect din dicționar/glosar (automat)", value=True)
                    do_rules = gr.Checkbox(label="Aplică reguli Greșit=>Corect (cuvinte+fraze)", value=True)

                with gr.Row():
                    do_diarize = gr.Checkbox(
                        label="Diarizare automată (pyannote) – necesită HF_TOKEN + pyannote.audio",
                        value=False,
                        interactive=True,
                    )
                    speaker_prefix = gr.Dropdown(
                        label="Prefix vorbitor (manual, folosit doar dacă diarizare=OFF)",
                        choices=speaker_choices,
                        value="(fără)",
                    )

                gr.Markdown("#### Traducere (OpenAI + fallback offline Argos)")
                with gr.Row():
                    do_translate = gr.Checkbox(label="Tradu (OpenAI → Argos fallback)", value=False, interactive=True)
                    translate_target_lang = gr.Dropdown(
                        label="Limba țintă",
                        choices=list(_LANG_MAP.keys()),
                        value="română",
                    )

                with gr.Row():
                    openai_model = gr.Dropdown(
                        label="Model OpenAI",
                        choices=["gpt-4o", "gpt-4o-mini"],
                        value="gpt-4o-mini",
                    )
                    openai_api_key = gr.Textbox(
                        label="OpenAI API Key (sau lasă gol dacă ai OPENAI_API_KEY în env)",
                        type="password",
                        placeholder="sk-...",
                    )

                btn = gr.Button("Transcrie", variant="primary", elem_classes=["btn-fullwidth"])

                gr.Markdown("#### Rezultate RAW (necorectat)")
                raw_text = gr.Textbox(label="TXT (preview)", lines=10)
                raw_srt = gr.Textbox(label="SRT (preview)", lines=10)
                with gr.Row():
                    raw_txt_file = gr.File(label="Descarcă TXT (raw, complet)")
                    raw_srt_file = gr.File(label="Descarcă SRT (raw, complet)")

                gr.Markdown("#### Rezultate (corectat cu glosar/dicționare/reguli)")
                corr_text = gr.Textbox(label="TXT corectat (preview)", lines=10)
                corr_srt = gr.Textbox(label="SRT corectat (preview)", lines=10)
                with gr.Row():
                    corr_txt_file = gr.File(label="Descarcă TXT (corectat, complet)")
                    corr_srt_file = gr.File(label="Descarcă SRT (corectat, complet)")

                meta = gr.Textbox(label="Info", lines=8)

                btn.click(
                    fn=ui_transcribe,
                    inputs=[
                        audio, model_name, beam, language, device, compute,
                        do_autocorrect, do_rules, speaker_prefix, do_diarize,
                        do_translate, translate_target_lang, openai_api_key, openai_model
                    ],
                    outputs=[
                        raw_text, raw_srt, raw_txt_file, raw_srt_file,
                        corr_text, corr_srt, corr_txt_file, corr_srt_file,
                        meta
                    ],
                )

            with gr.Tab("Învățare (Dicționar/Glosar/Reguli)"):
                with gr.Row():
                    dict_upload = gr.File(label="Încarcă dicționar .txt (1 termen/frază pe linie)", file_types=[".txt"])
                    dict_btn = gr.Button("Importă dicționar")
                dict_list = gr.Textbox(label="Dicționare importate (în user_data/dictionaries)", interactive=False, lines=5)

                with gr.Row():
                    glossary = gr.Textbox(label="Glosar (1 termen/frază pe linie)", lines=8)
                    rules = gr.Textbox(label="Reguli Greșit => Corect (cuvinte + fraze)", lines=10)

                with gr.Row():
                    gloss_btn = gr.Button("Salvează glosar")
                    rules_btn = gr.Button("Salvează reguli")

                gr.Markdown("##### Adaugă rapid o regulă Greșit => Corect")
                with gr.Row():
                    wrong = gr.Textbox(label="Greșit")
                    right = gr.Textbox(label="Corect")
                also_gloss = gr.Checkbox(label="Adaugă și forma corectă în glosar", value=True)
                add_btn = gr.Button("Adaugă regula")

                gr.Markdown("##### Footer (editabil)")
                footer_box = gr.Textbox(label="Text footer (Markdown simplu)", lines=2)
                footer_btn = gr.Button("Salvează footer")

                demo.load(ui_reload_learning, outputs=[glossary, rules, dict_list, footer_box])
                dict_btn.click(ui_import_dict, inputs=[dict_upload], outputs=[dict_list])
                gloss_btn.click(ui_save_glossary, inputs=[glossary], outputs=[glossary])
                rules_btn.click(ui_save_rules, inputs=[rules], outputs=[rules])
                add_btn.click(ui_add_rule, inputs=[wrong, right, also_gloss, rules], outputs=[wrong, right, rules])
                footer_btn.click(_save_footer_text, inputs=[footer_box], outputs=[footer_box])

        gr.Markdown(_load_footer_text())

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)