# Third-party notices

The application code is GPL-3.0-only. That license does not replace the terms of models, dependencies or demo recordings.

| Component | License / source |
|---|---|
| faster-whisper | MIT, SYSTRAN and contributors: https://github.com/SYSTRAN/faster-whisper |
| Whisper model family | MIT, OpenAI: https://github.com/openai/whisper |
| CTranslate2 conversions | MIT: https://huggingface.co/Systran/faster-whisper-small, https://huggingface.co/Systran/faster-whisper-large-v3 and https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo. The Balanced download URL retains the working mobiuslabsgmbh alias. |
| Community-1 weights | CC BY 4.0, pyannoteAI / pyannote contributors: https://huggingface.co/pyannote/speaker-diarization-community-1 |
| pyannote.audio | MIT, CNRS, pyannoteAI and contributors: https://github.com/pyannote/pyannote-audio |
| PyAV | BSD-3-Clause: https://github.com/PyAV-Org/PyAV |
| FFmpeg | Its upstream components have their own LGPL/GPL terms: https://ffmpeg.org/legal.html. Installed through upstream PyAV wheels; binaries are not redistributed in this repository. |
| PyTorch / torchaudio | BSD-style terms in their respective projects: https://github.com/pytorch/pytorch and https://github.com/pytorch/audio |
| React, Vite, TanStack Virtual, WaveSurfer, FastAPI, SQLAlchemy, Alembic | See the licenses in the installed distributions and their upstream repositories. |
| Lucide icons | ISC: https://lucide.dev/license |
| LibriSpeech demo excerpts | CC BY 4.0. Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur. https://www.openslr.org/12 |

Model weights are downloaded separately, unmodified, into private application storage. Community-1 access requires the user to accept its Hugging Face download conditions. This repository contains no model weights, Codex executable, ChatGPT credentials, private voice samples or private transcripts.

The public demo concatenates selected LibriSpeech utterances with 250 ms silence and uses lossless FLAC. Its complete source-file list and modifications are recorded in `demo/manifest.json`. Reader A/B/C are aliases. Dataset transcripts are reference annotations, not model predictions or evidence of model accuracy.
