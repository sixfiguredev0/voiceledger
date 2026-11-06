# Public review demonstration

The audio is a short, lossless rearrangement of three readers from the LibriSpeech test-clean corpus, distributed under **CC BY 4.0**. Attribution: Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur. Source: <https://www.openslr.org/12>.

Utterances are concatenated with 250 ms of silence. They form a curated sequence of audiobook excerpts, not a real conversation. Transcripts and speaker groupings use source dataset annotations, not predictions. Two turns are intentionally unconfirmed so visitors can try the review workflow. This demo does not measure the models' accuracy.

`manifest.json` lists every original source file and transformation. Reader A/B/C are aliases, not claims about real names. This data is separate from the application's GPL-3.0-only license.

To reproduce: download the official `test-clean.tar.gz` archive to `.cache/demo/`, then run `python scripts/prepare_demo.py` in the project's Python environment.
