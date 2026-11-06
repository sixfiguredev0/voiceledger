# Measurements and acceptance

Measured locally on Windows x64, Intel Core Ultra 5 135H, 18 logical processors, about 15.5 GiB physical RAM, CPU inference capped at eight threads. Python 3.12.16, faster-whisper 1.2.1, pyannote.audio 4.0.7, PyTorch 2.8.0 CPU. These are smoke measurements, not a controlled model comparison.

## Decode validation

Three private AAC M4A recordings, all 48 kHz mono, were completely decoded. Their aggregate duration was approximately 4:27:15 and size 249 MiB. The originals' SHA-256 hashes stayed unchanged. The largest difference between source-header and normalized duration was **1 ms** after rounding.

Phone AAC timestamps occasionally overlapped by one source sample. Placing samples on the source clock before resampling removed accumulated drift; naive contiguous concatenation exceeded the 100 ms tolerance on the longest file. Private filenames, hashes, audio and transcripts are intentionally absent here.

## One-minute Bulgarian smoke test

The same 60-second excerpt, starting two minutes into the priority recording, was processed once per mode with CPU INT8 and no ASR cache hits. Audio extraction and normalization are outside these ASR timings. Reported time includes model startup. Other desktop activity and system caches were not controlled.

| Mode | Model / beam | Elapsed ASR | Returned words |
|---|---|---:|---:|
| Fast draft | small / 1 | 24.44 s | 133 |
| Balanced | large-v3-turbo / 3 | 42.57 s | 118 |
| Accuracy | large-v3 / 5 | 137.73 s | 129 |

Different word counts do not establish quality. Community-1 took 62.85 seconds, including initialization, on this excerpt and reported one voice. That count has not been manually validated. A later cached ASR run took 2.41 seconds; it is not included as a fresh inference result.

Model revisions used:

| Component | Repository | Revision |
|---|---|---|
| Fast | Systran/faster-whisper-small | `536b0662742c02347bc0e980a01041f333bce120` |
| Balanced | mobiuslabsgmbh/faster-whisper-large-v3-turbo (upstream now redirects to dropbox-dash) | `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` |
| Accuracy | Systran/faster-whisper-large-v3 | `edaa852ec7e145841d8ffdb056a99866b5f0a478` |
| Speaker analysis | pyannote/speaker-diarization-community-1 | `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee` |

## Public integration check

The [attributed demo](../demo/README.md) consists of two roughly half-minute sequences from three LibriSpeech readers. A separate project was processed with actual models, keeping the curated demo independent.

- The first automatic pass found two clusters for three known readers. Reanalysis with a minimum of three found three. This checks the hint and recovery path; a correct count alone does not prove correct diarization.
- Cancellation during speaker analysis and resume completed successfully while retaining ASR artifacts.
- A confirmed dataset-aligned reference clip produced a valid embedding. Cross-recording candidate comparisons were returned for the second recording. Candidate availability does not establish identity-match accuracy.
- On the 28-second second file, fresh Fast ASR took 6.655 s and speaker inference took 24.270 s, excluding worker/model startup. Peak worker RSS was about 592 MiB. Those numbers are not representative of multi-hour peak memory.
- English and Bulgarian fictional Codex instructions produced validated proposals using existing ChatGPT authentication. No private audio or transcript was sent in these checks.

To rerun with downloaded models and a running app:

```powershell
uv run python scripts/validate_models.py
```

It imports only the public demo into a separate validation project. Run it while the ordinary queue is idle. The result is written to ignored local cache storage.

## Bulgarian acceptance procedure

**Word error rate and speaker attribution accuracy are not established yet.** A ten-minute review set can be assembled across the three recordings. Start with the priority recording, include a recurring voice, brief appearances and difficult audio, and annotate approximately three minutes by listening. Do not treat a model's transcript as ground truth.

1. Correct the words, speaker names, boundaries and overlap labels in the review set. Save a JSON export outside the repository. Keep annotations of non-transcribed speech too.
2. Provide a separate JSON mapping from raw recording-local cluster labels to the manually verified names. Use names matching the export's `speakers` values. This maps anonymous labels for scoring; it does not claim automatic recognition.
3. Compare the current immutable model run with the reviewed export:

```powershell
.venv\Scripts\python.exe -m voiceledger.cli evaluate RECORDING_ID reviewed.json --speaker-map mapping.json --start 0 --seconds 180
```

WER uses Unicode normalization, lowercase text, punctuation removal and edit distance. Speaker attribution is duration-weighted on annotated, non-overlapping speech; missing and unknown predictions count against coverage. This is an application acceptance metric, not a full diarization error rate benchmark. Complete reference turns inside the selected interval define the scored interval. Avoid reprocessing between saving the reference and scoring the intended raw run.

Working targets: **WER ≤25%** and **speaker attribution ≥85%**. If missed, inspect errors, retry difficult material in Accuracy mode, and record remaining limitations. Full-batch estimates and quality claims should follow that review. No result in this document demonstrates that these targets have been met.
