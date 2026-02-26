Whisper SRT GUI (Simplu)

Aplicație (Gradio) pentru transcriere audio/video în TXT și SRT, cu opțiuni de:

corectare automată pe bază de glosar/dicționar/reguli

diarizare vorbitori (opțional, cu pyannote)

traducere (OpenAI sau fallback offline Argos Translate)

✅ Nu taie nicio secundă din audio: transcrierea se face pe WAV complet + vad_filter=False
✅ Reduce repetițiile: setări anti-repetiție + eliminare duplicate consecutive

Funcționalități
Transcriere

Acceptă: .mp3, .wav, .m4a, .mp4 (audio/video)

Generează:

transcript_raw_*.txt + transcript_raw_*.srt

transcript_corrected_*.txt + transcript_corrected_*.srt

Până la 1 oră per fișier (configurabil)

Corectare text (învățare)

Glosar: 1 termen/frază pe linie

Reguli: perechi Greșit ⇒ Corect (cuvinte/fraze)

Import de dicționare .txt în user_data/dictionaries

Diarizare (opțional)

Necesită pyannote.audio + token Hugging Face (HF_TOKEN)

Prefixează segmentele cu Vorbitor N

Traducere (opțional)

OpenAI (dacă ai OPENAI_API_KEY și librăria openai)

Argos Translate fallback offline (dacă ai argostranslate + pachetele lingvistice)

Cerințe
Windows

Python 3.10+ (merge și 3.11)

FFmpeg + FFprobe în PATH (obligatoriu pentru conversie stabilă)

(Opțional) CUDA + Nvidia pentru viteză (altfel merge pe CPU)

Linux (Ubuntu 22.04)

Python 3.10+ (Ubuntu 22.04 vine cu 3.10)

FFmpeg + FFprobe instalate prin apt

(Opțional) CUDA/NVIDIA dacă vrei rulare pe GPU

Instalare
1) Clonează repo-ul
git clone <repo_url>
cd whisper_srt_gui
Instalare pe Windows
2) Creează și activează venv

CMD (recomandat pe Windows):

python -m venv .venv
call .venv\Scripts\activate.bat
3) Instalează dependențele
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
Instalare pe Linux (Ubuntu 22.04)
2) Instalează FFmpeg + dependințe de bază
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip

Verifică:

ffmpeg -version
ffprobe -version
python3 --version
3) Creează și activează venv
python3 -m venv .venv
source .venv/bin/activate
4) Instalează dependențele
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
Variabile de mediu (opțional)
Hugging Face (pentru diarizare)
Windows (CMD / PowerShell)
setx HF_TOKEN "hf_...."

setx se aplică în sesiuni noi de terminal. Închide/re-deschide terminalul.

Linux (Ubuntu)

Temporar (doar în terminalul curent):

export HF_TOKEN="hf_...."

Permanent (recomandat):

echo 'export HF_TOKEN="hf_...."' >> ~/.bashrc
source ~/.bashrc
OpenAI (pentru traducere)
Windows
setx OPENAI_API_KEY "sk-...."
Linux (Ubuntu)

Temporar:

export OPENAI_API_KEY="sk-...."

Permanent:

echo 'export OPENAI_API_KEY="sk-...."' >> ~/.bashrc
source ~/.bashrc
Rulare
Windows
python 3app.py
Linux (Ubuntu)
python 3app.py

Aplicația pornește local pe:

http://0.0.0.0:7860 (în browser deschide de obicei http://127.0.0.1:7860)

Notă despre “nu taie nicio secundă”

Aplicația:

Convertește inputul în WAV 16k (stabil pentru mp3/mp4/m4a)

Rulează transcrierea cu vad_filter=False (nu elimină porțiuni)

Notă despre “repetiții”

Whisper poate repeta uneori propoziții standard (intro/outro) când audio are zgomot/muzică sau canal audio problematic.
În această versiune:

se folosește condition_on_previous_text=False (unde e suportat)

penalizări anti-repetiție (unde sunt suportate)

se elimină duplicate consecutive în segmente

Structură directoare

3app.py – aplicația principală (Gradio UI)

corrections.py – logică de corectare (glosar/reguli/dicționare)

user_data/ – date utilizator:

glossary.txt

rules.txt

dictionaries/

outputs/ (fișierele generate)

tmp/ – fișiere temporare (WAV convertit)

Troubleshooting
Windows: “running scripts is disabled”

Dacă activezi venv din PowerShell și primești eroare de policy:

folosește CMD:

call .venv\Scripts\activate.bat

sau schimbă policy (opțional):

Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
Linux: permisiuni / pachete lipsă

Dacă lipsește python3-venv:

sudo apt install -y python3-venv
“FFmpeg not found”

Windows: instalează FFmpeg și adaugă în PATH

Ubuntu:

sudo apt install -y ffmpeg
Licență

Alege o licență (MIT/Apache-2.0) și adaug-o în LICENSE.
