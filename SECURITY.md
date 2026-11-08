# Reporting a problem

Report ordinary bugs through GitHub issues using public demo audio or generated test fixtures. Do not attach private recordings, transcripts, voice embeddings, access tokens, account files or private job logs.

For a security issue, use GitHub's private vulnerability reporting when available. Otherwise ask the maintainer for a private reporting route without posting exploit details or private data publicly.

VoiceLedger listens on `127.0.0.1`, uses a per-launch local session token, rejects foreign browser origins, and keeps runtime data outside the source tree. It is a personal local application, not a hardened shared or internet-facing service. Do not expose its port through a public tunnel or reverse proxy.

The publication check scans tracked files and every reachable file version in Git branches and tags for private runtime artifacts and known credential patterns. CI fetches full history before running the check. Only the two exact, hash-verified, attributed LibriSpeech demo audio files are allowed. Credential files, exports and archives are rejected. Screenshots must use public demo data; automated pattern checks cannot establish that an arbitrary image contains no private information.

The optional assistant calls the user's installed Codex CLI with ChatGPT authentication and restricted tools. The app validates its structured proposals and requires the user to apply them. No API-key billing fallback is enabled. Model downloads and the assistant require network access; ordinary transcription and manual review work offline after setup.
