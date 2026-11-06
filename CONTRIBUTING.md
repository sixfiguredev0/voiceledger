# Contributing

VoiceLedger currently supports Windows x64 and Python 3.12. Keep inference local, keep private runtime data outside the repository, and make corrections reversible.

1. Run `Setup.cmd` or build the frontend and run `uv sync --frozen --python 3.12`.
2. Run `uv run pytest -q` and `uv run ruff check src tests scripts`.
3. In `frontend`, run `npm test`, `npm run build`, and `npx playwright install chromium`, then `npm run test:e2e`.
4. Review the staged diff and run `uv run python scripts/check_publication.py`.

Ordinary CI uses generated audio and attributed public demo data. It must not require paid APIs, ChatGPT authentication, Hugging Face credentials or gated model downloads. Real-model validation is an explicit local action: run the app, download its models, then run `uv run python scripts/validate_models.py`.

Preserve raw inference runs. Apply user changes through typed, revision-checked correction commands. Keep recording-local speaker clusters distinct from project-level identities. Cross-recording matches always require confirmation. Similarity scores must not be described as probabilities.

For engine changes, document the exact model revisions and include a small reproducible example. Performance or accuracy claims must name the evaluated audio and conditions. Do not commit private recordings, transcripts, voice embeddings, cached credentials, model weights or diagnostic logs. Use the public demo for screenshots.
