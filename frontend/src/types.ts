export type Mode = "fast" | "balanced" | "accuracy";
export type Project = { id: string; name: string; created_at: string };
export type Recording = {
  id: string;
  project_id: string;
  filename: string;
  sha256: string;
  metadata_json: {
    duration_ms: number;
    sample_rate: number;
    channels: number;
    size_bytes: number;
    codec: string;
    demo?: boolean;
  };
  current_run_id: string | null;
  revision: number;
};
export type Word = {
  start_ms: number;
  end_ms: number;
  text: string;
  probability?: number;
};
export type Turn = {
  id: string;
  recording_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  cluster: string | null;
  speaker_id: string | null;
  words: Word[];
  overlap: boolean;
  uncertain: boolean;
  excluded: boolean;
  category: string;
  manual: boolean;
};
export type Reference = {
  id: string;
  recording_id: string;
  start_ms: number;
  end_ms: number;
  model_revision: string | null;
};
export type Speaker = {
  id: string;
  name: string;
  notes: string;
  samples: Reference[];
};
export type Job = {
  id: string;
  recording_id: string;
  kind: string;
  mode: Mode;
  language: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  details: Record<string, unknown>;
};
export type Action = {
  kind: "assign" | "merge" | "split" | "bounds" | "text" | "mark" | "reanalyze";
  row_ids?: string[];
  speaker_id?: string;
  name?: string;
  source_speaker_id?: string;
  scope?: "selected" | "cluster";
  start_ms?: number;
  end_ms?: number;
  split_at_ms?: number;
  text?: string;
  right_text?: string;
  category?: "speech" | "noise" | "irrelevant" | "overlap" | "uncertain";
  min_speakers?: number;
  max_speakers?: number;
};
export type Proposal = {
  id?: string;
  actions: Action[];
  explanation: string;
  clarification?: string;
  affected_turns?: number;
  base_revision?: number;
};
export type Correction = {
  id: string;
  active: boolean;
  explanation: string;
  actions: Action[];
  created_at: string;
};
export type Match = {
  cluster: string;
  candidates: {
    speaker_id: string;
    name: string;
    similarity: number;
    sample_id: string;
    recording_id: string;
    start_ms: number;
    end_ms: number;
  }[];
};
export type Models = Record<
  string,
  { ready: boolean; revision: string | null }
>;
export type Conflict = {
  correction_id: string;
  explanation: string;
  actions: Action[];
};
