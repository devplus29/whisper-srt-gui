# 🎙 Whisper SRT GUI

A production-ready transcription application built with
**faster-whisper** and **Gradio**, designed for accurate audio/video
transcription into **TXT and SRT formats**, with advanced text
correction, speaker diarization and translation capabilities.

------------------------------------------------------------------------

## ✨ Overview

Whisper SRT GUI provides:

-   🎧 High-accuracy transcription
-   📄 TXT & SRT export
-   🧠 Intelligent text correction (glossary + rule engine)
-   👥 Optional speaker diarization (pyannote)
-   🌍 Translation support (OpenAI + offline Argos fallback)
-   ⚡ Full-length audio processing (no truncation)
-   🔁 Repetition reduction & duplicate filtering

------------------------------------------------------------------------

# 🚀 Key Features

## 🎧 Transcription

-   Supports: `.mp3`, `.wav`, `.m4a`, `.mp4`
-   Generates:
    -   `transcript_raw_*.txt`
    -   `transcript_raw_*.srt`
    -   `transcript_corrected_*.txt`
    -   `transcript_corrected_*.srt`
-   Supports files up to **1 hour** (configurable)

------------------------------------------------------------------------

## 🧠 Text Correction (Learning System)

-   Glossary-based correction (1 term / line)
-   Custom rule engine (`Greșit ⇒ Corect` format)
-   Dictionary import via `user_data/dictionaries`

------------------------------------------------------------------------

## 👥 Speaker Diarization (Optional)

-   Powered by `pyannote.audio`
-   Requires Hugging Face token (`HF_TOKEN`)
-   Automatically labels segments (Vorbitor 1, Vorbitor 2, etc.)

------------------------------------------------------------------------

## 🌍 Translation (Optional)

### OpenAI (Cloud-based)

-   Requires `OPENAI_API_KEY`

### Argos Translate (Offline Fallback)

-   Works without internet
-   Requires installed language packages

------------------------------------------------------------------------

# 🔒 Audio Integrity Guarantee

✔ Converts input to WAV (16kHz)\
✔ Uses `vad_filter=False` (no voice activity cutting)\
✔ Processes full audio duration

If audio is 10 minutes → transcript reflects 10 minutes\
If audio is 60 minutes → transcript reflects full duration

------------------------------------------------------------------------

# 🖥 System Requirements

## Windows

-   Python 3.10+
-   FFmpeg + FFprobe added to PATH
-   (Optional) NVIDIA CUDA for GPU acceleration

## Linux (Ubuntu 22.04)

-   Python 3.10+
-   FFmpeg installed via apt
-   (Optional) NVIDIA CUDA for GPU acceleration

------------------------------------------------------------------------

# 📦 Installation

## Clone repository

``` bash
git clone <repo_url>
cd whisper_srt_gui
```

## Windows

``` bat
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

## Linux (Ubuntu 22.04)

``` bash
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

------------------------------------------------------------------------

# ▶️ Run Application

``` bash
python 3app.py
```

Access locally:

http://127.0.0.1:7860

------------------------------------------------------------------------

# 📁 Project Structure

    3app.py              # Main Gradio application
    corrections.py       # Glossary & rule engine
    requirements.txt     # Dependencies
    start.bat            # Windows launcher
    start.sh             # Linux launcher

    user_data/
      glossary.txt
      rules.txt
      dictionaries/
      outputs/

    tmp/                 # Temporary WAV processing

------------------------------------------------------------------------

# 📜 License

MIT License recommended.
