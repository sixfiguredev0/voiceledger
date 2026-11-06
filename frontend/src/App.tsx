import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  AudioLines,
  Upload,
  Plus,
  FileAudio,
  Search,
  Settings2,
  Download,
  ChevronRight,
  ChevronDown,
  Check,
  ShieldCheck,
  Users,
  Flag,
  Layers,
  Loader2,
  X,
  Clock3,
  FolderOpen,
  MessageSquare,
  Headphones,
  ArrowUpRight,
  Play,
  Pause,
  AlertCircle,
} from "lucide-react";
import { api, color, download, post, time, uploadFile } from "./api";
import { translator, type Key } from "./i18n";
import type {
  Action,
  Conflict,
  Job,
  Match,
  Mode,
  Models,
  Project,
  Proposal,
  Recording,
  Speaker,
  Turn,
} from "./types";
import Player from "./Player";
import ReviewPanel from "./ReviewPanel";

type View = "transcript" | "speakers" | "review" | "processing";
function IconMark() {
  return (
    <div className="brand-mark">
      <AudioLines size={25} strokeWidth={1.8} />
    </div>
  );
}
function ModeCards({
  mode,
  setMode,
  t,
}: {
  mode: Mode;
  setMode: (m: Mode) => void;
  t: (key: Key) => string;
}) {
  return (
    <div className="mode-cards">
      {(["fast", "balanced", "accuracy"] as const).map((m, i) => (
        <button
          className={mode === m ? "selected" : ""}
          key={m}
          onClick={() => setMode(m)}
        >
          <span className="mode-top">
            <span className="mode-number">0{i + 1}</span>
            {mode === m && <Check size={15} />}
          </span>
          <b>{t(m)}</b>
          <span>{t(`${m}Desc` as Key)}</span>
          <small>
            {
              {
                fast: "small",
                balanced: "large-v3-turbo",
                accuracy: "large-v3",
              }[m]
            }
          </small>
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [lang, setLang] = useState(
      localStorage.getItem("voiceledger.language") ?? "en",
    ),
    t = useMemo(() => translator(lang), [lang]);
  const [projects, setProjects] = useState<Project[]>([]),
    [projectId, setProjectId] = useState(""),
    [recordings, setRecordings] = useState<Recording[]>([]),
    [recordingId, setRecordingId] = useState("");
  const [speakers, setSpeakers] = useState<Speaker[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [models, setModels] = useState<Models>({}),
    [health, setHealth] = useState({ available_ram_gib: 0, disk_free_gib: 0 });
  const [view, setView] = useState<View>("transcript"),
    [rows, setRows] = useState<Turn[]>([]),
    [total, setTotal] = useState(0),
    [revision, setRevision] = useState(0),
    [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [selectionIds, setSelectionIds] = useState<string[]>([]),
    [search, setSearch] = useState(""),
    [speakerFilter, setSpeakerFilter] = useState(""),
    [uncertainOnly, setUncertainOnly] = useState(false),
    [showExcluded, setShowExcluded] = useState(true);
  const [mode, setMode] = useState<Mode>("balanced"),
    [audioLanguage, setAudioLanguage] = useState("bg"),
    [settings, setSettings] = useState(false),
    [exportOpen, setExportOpen] = useState(false),
    [projectOpen, setProjectOpen] = useState(false),
    [projectName, setProjectName] = useState("");
  const [exportScope, setExportScope] = useState("one"),
    [exportFormat, setExportFormat] = useState("txt"),
    [includeExcluded, setIncludeExcluded] = useState(false);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(
      null,
    ),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false),
    [importProgress, setImportProgress] = useState<number | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null),
    [assistantReady, setAssistantReady] = useState(false),
    [matches, setMatches] = useState<Match[]>([]),
    [sampleClip, setSampleClip] = useState<{
      recording_id: string;
      start_ms: number;
      end_ms: number;
    } | null>(null);
  const [playhead, setPlayhead] = useState(0),
    [media, setMedia] = useState<HTMLAudioElement | null>(null),
    [drop, setDrop] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false),
    [clipPlaying, setClipPlaying] = useState(false);
  const clipStop = useRef<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null),
    scrollRef = useRef<HTMLDivElement>(null),
    loadEpoch = useRef(0);
  const recording = recordings.find((r) => r.id === recordingId),
    project = projects.find((p) => p.id === projectId);
  const selection = useMemo(
    () => rows.filter((r) => selectionIds.includes(r.id)),
    [rows, selectionIds],
  );
  const names = useMemo(
    () => new Map(speakers.map((s) => [s.id, s.name])),
    [speakers],
  );
  const detected = useMemo(
    () => [
      ...new Set(rows.map((r) => r.cluster).filter((v): v is string => !!v)),
    ],
    [rows],
  );
  const displayName = (row: Turn) =>
    row.speaker_id && names.has(row.speaker_id)
      ? names.get(row.speaker_id)!
      : row.cluster
        ? `${lang === "bg" ? "Глас" : "Voice"} ${String(detected.indexOf(row.cluster) + 1).padStart(2, "0")}`
        : t("unknown");
  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), toast.error ? 12000 : 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    localStorage.setItem("voiceledger.language", lang);
    document.documentElement.lang = lang;
  }, [lang]);
  const loadProject = useCallback(async () => {
    if (!projectId) return;
    const [recs, people] = await Promise.all([
      api<Recording[]>(`/projects/${projectId}/recordings`),
      api<Speaker[]>(`/projects/${projectId}/speakers`),
    ]);
    setRecordings(recs);
    setSpeakers(people);
    setRecordingId((current) =>
      recs.some((r) => r.id === current)
        ? current
        : (recs.find(
            (r) =>
              r.id ===
              (new URLSearchParams(location.search).get("recording") ??
                localStorage.getItem(`voiceledger.recording.${projectId}`)),
          )?.id ??
          recs[0]?.id ??
          ""),
    );
  }, [projectId]);
  const loadTranscript = useCallback(async () => {
    if (!recordingId) {
      setRows([]);
      return;
    }
    const epoch = ++loadEpoch.current;
    setLoading(true);
    try {
      let next: Turn[] = [],
        offset = 0;
      while (true) {
        const data = await api<{
          rows: Turn[];
          total: number;
          revision: number;
          conflicts: Conflict[];
        }>(`/recordings/${recordingId}/transcript?offset=${offset}&limit=1000`);
        if (epoch !== loadEpoch.current) return;
        next = next.concat(data.rows);
        setRows(next);
        setTotal(data.total);
        setRevision(data.revision);
        setConflicts(data.conflicts);
        offset += data.rows.length;
        if (offset >= data.total || !data.rows.length) break;
      }
      const m = await api<Match[]>(`/recordings/${recordingId}/matches`);
      if (epoch === loadEpoch.current) setMatches(m);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      if (epoch === loadEpoch.current) setLoading(false);
    }
  }, [recordingId, notify]);
  useEffect(() => {
    void api<Project[]>("/projects")
      .then((value) => {
        setProjects(value);
        setProjectId(
          value.find(
            (p) =>
              p.id ===
              (new URLSearchParams(location.search).get("project") ??
                localStorage.getItem("voiceledger.project")),
          )?.id ??
            value[0]?.id ??
            "",
        );
      })
      .catch((e) => notify(e.message, true));
    void api<{ ready: boolean }>("/assistant/status")
      .then((s) => setAssistantReady(s.ready))
      .catch(() => {});
  }, [notify]);
  useEffect(() => {
    if (projectId) localStorage.setItem("voiceledger.project", projectId);
    if (recording?.project_id === projectId)
      localStorage.setItem(`voiceledger.recording.${projectId}`, recording.id);
  }, [projectId, recordingId, recording?.project_id]);
  useEffect(() => {
    void loadProject().catch((e) => notify(e.message, true));
  }, [loadProject, notify]);
  useEffect(() => {
    setSelectionIds([]);
    setRows([]);
    setSearch("");
    setSpeakerFilter("");
    setProposal(null);
    void loadTranscript();
    return () => {
      loadEpoch.current++;
    };
  }, [recordingId]);
  useEffect(() => {
    if (recording) setAudioLanguage(recording.metadata_json.demo ? "en" : "bg");
  }, [recordingId]);
  useEffect(() => {
    if (recording?.revision && recording.revision !== revision)
      void loadTranscript();
  }, [recording?.revision, loadTranscript, revision]);
  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        const [j, m, h] = await Promise.all([
          api<Job[]>("/jobs"),
          api<Models>("/models"),
          api<typeof health>("/health"),
        ]);
        if (!active) return;
        setJobs(j);
        setModels(m);
        setHealth(h);
        if (projectId) await loadProject();
      } catch {}
    };
    void tick();
    const interval = setInterval(() => void tick(), 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [projectId, loadProject]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        (event.target as HTMLElement)?.closest(
          "input,textarea,select,button,[contenteditable]",
        ) ||
        settings ||
        exportOpen ||
        projectOpen
      )
        return;
      if (event.code === "Space") {
        event.preventDefault();
        if (media)
          media.paused ? void media.play().catch(() => {}) : media.pause();
      }
      if (event.code === "ArrowLeft" && media) {
        event.preventDefault();
        media.currentTime = Math.max(0, media.currentTime - 5);
      }
      if (event.code === "ArrowRight" && media) {
        event.preventDefault();
        media.currentTime = Math.min(
          media.duration || 0,
          media.currentTime + 5,
        );
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [media, settings, exportOpen, projectOpen]);
  const refresh = () => {
    void loadProject();
    void loadTranscript();
  };
  async function openDemo() {
    setBusy(true);
    try {
      const value = await post<{ project_id: string }>("/demo");
      setProjects(await api<Project[]>("/projects"));
      setProjectId(value.project_id);
      setView("transcript");
      setFilesOpen(false);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }
  async function createProject() {
    try {
      const value = await post<Project>("/projects", {
        name: projectName.trim(),
      });
      setProjects((p) => [...p, value]);
      setProjectId(value.id);
      setProjectOpen(false);
      setFilesOpen(false);
      setProjectName("");
    } catch (e) {
      notify((e as Error).message, true);
    }
  }
  async function importFiles(files: FileList | File[] | null) {
    if (!files?.length) return;
    setImportProgress(0);
    try {
      let target = projectId;
      if (!target) {
        const p = await post<Project>("/projects", { name: t("recordings") });
        setProjects((v) => [...v, p]);
        setProjectId(p.id);
        target = p.id;
      }
      const list = Array.from(files);
      for (let i = 0; i < list.length; i++)
        await uploadFile(target, list[i], (value) =>
          setImportProgress((i + value) / list.length),
        );
      const recs = await api<Recording[]>(`/projects/${target}/recordings`);
      setRecordings(recs);
      setRecordingId(recs.at(-1)?.id ?? "");
      setFilesOpen(false);
      notify(t("importSuccess"));
      setView("transcript");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setImportProgress(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function startJob() {
    if (!recording) return;
    if (!models[mode]?.ready || !models.diarization?.ready) {
      setSettings(true);
      notify(t("setupRequired"), true);
      return;
    }
    setBusy(true);
    try {
      await post("/jobs", {
        recording_id: recording.id,
        mode,
        language: audioLanguage,
      });
      notify(t("jobStarted"));
      setView("processing");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }
  async function preview(actions: Action[]) {
    if (!recording) return;
    setBusy(true);
    try {
      setProposal(
        await post<Proposal>("/corrections/preview", {
          recording_id: recording.id,
          base_revision: revision,
          actions,
        }),
      );
    } finally {
      setBusy(false);
    }
  }
  function selectTurn(row: Turn, multi = false) {
    setFilesOpen(false);
    if (!multi) {
      media?.pause();
      clipStop.current = null;
    }
    setSelectionIds((current) =>
      multi
        ? current.includes(row.id)
          ? current.filter((id) => id !== row.id)
          : [...current, row.id]
        : [row.id],
    );
    if (media && !multi) media.currentTime = row.start_ms / 1000;
  }
  const filtered = useMemo(
    () =>
      rows.filter(
        (row) =>
          (!search ||
            row.text
              .toLocaleLowerCase()
              .includes(search.toLocaleLowerCase())) &&
          (!speakerFilter ||
            row.speaker_id === speakerFilter ||
            row.cluster === speakerFilter) &&
          (!(uncertainOnly || view === "review") || row.uncertain) &&
          (showExcluded || !row.excluded),
      ),
    [rows, search, speakerFilter, uncertainOnly, showExcluded, view],
  );
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 108,
    overscan: 8,
  });
  const reviewPosition = Math.max(
    0,
    filtered.findIndex((r) => r.id === selection[0]?.id),
  );
  function beginReview() {
    setView("transcript");
    setSearch("");
    setSpeakerFilter("");
    setUncertainOnly(false);
    const first = rows.find((r) => !r.excluded);
    if (first) {
      selectTurn(first);
      virtualizer.scrollToIndex(0);
    }
  }
  function moveReview(delta: number) {
    const next = filtered[reviewPosition + delta];
    if (next) {
      selectTurn(next);
      virtualizer.scrollToIndex(reviewPosition + delta, { align: "auto" });
    } else {
      setSelectionIds([]);
      media?.pause();
      notify(t("reviewEnd"));
    }
  }
  async function savedReview() {
    const next = filtered[reviewPosition + 1];
    await Promise.all([loadProject(), loadTranscript()]);
    if (next) {
      selectTurn(next);
      virtualizer.scrollToIndex(reviewPosition + 1, { align: "auto" });
    } else {
      setSelectionIds([]);
      media?.pause();
      notify(t("reviewEnd"));
    }
  }
  function playExcerpt() {
    const first = selection[0];
    if (!first || !media) return;
    if (!media.paused && clipStop.current === first.end_ms) {
      media.pause();
      return;
    }
    clipStop.current = first.end_ms;
    media.currentTime = first.start_ms / 1000;
    void media.play().catch(() => notify(t("noAudio"), true));
  }
  useEffect(() => {
    if (!media) return;
    const update = () => setClipPlaying(!media.paused);
    media.addEventListener("play", update);
    media.addEventListener("pause", update);
    return () => {
      media.removeEventListener("play", update);
      media.removeEventListener("pause", update);
    };
  }, [media]);
  const onPlaybackTime = useCallback(
    (ms: number) => {
      setPlayhead(ms);
      if (clipStop.current !== null && ms >= clipStop.current) {
        media?.pause();
        clipStop.current = null;
      }
    },
    [media],
  );
  const activeJob = jobs.find(
    (j) =>
      j.recording_id === recordingId &&
      ["queued", "running", "cancelling"].includes(j.status),
  );
  const totalDuration = recordings.reduce(
    (n, r) => n + r.metadata_json.duration_ms,
    0,
  );
  const modalClose = (
    event: React.MouseEvent<HTMLDivElement>,
    close: () => void,
  ) => {
    if (event.target === event.currentTarget) close();
  };
  return (
    <div
      className={`app-shell ${filesOpen ? "files-open" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (e.dataTransfer.types.includes("Files")) setDrop(true);
      }}
      onDragLeave={(e) => {
        if (!e.relatedTarget) setDrop(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDrop(false);
        void importFiles(e.dataTransfer.files);
      }}
    >
      <input
        ref={fileInput}
        type="file"
        className="hidden"
        multiple
        accept="audio/*,.m4a,.flac,.wav,.mp3"
        onChange={(e) => void importFiles(e.target.files)}
      />
      <aside className="sidebar">
        <button
          className="drawer-close icon-button"
          aria-label={t("close")}
          onClick={() => setFilesOpen(false)}
        >
          <X size={20} />
        </button>
        <a className="brand" href="/" aria-label="VoiceLedger">
          <IconMark />
          <span>
            Voice<span className="brand-light">Ledger</span>
            <small>{t("tagline")}</small>
          </span>
        </a>
        <div className="workspace-label">
          <span>{t("local")}</span>
          <span className="tiny-dot green" />
        </div>
        <div className="project-switch">
          <FolderOpen size={17} />
          <select
            aria-label={t("project")}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {!projects.length && <option value="">{t("newProject")}</option>}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            aria-label={t("newProject")}
            onClick={() => setProjectOpen(true)}
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="sidebar-section-title">
          <span>{t("recordings")}</span>
          <span className="count">
            {recordings.length.toString().padStart(2, "0")}
          </span>
        </div>
        <div className="recording-list">
          {recordings.map((r, i) => (
            <button
              className={`recording-item ${r.id === recordingId ? "selected" : ""}`}
              key={r.id}
              onClick={() => {
                setRecordingId(r.id);
                setView("transcript");
                setFilesOpen(false);
              }}
            >
              <span className="file-icon">
                <FileAudio size={19} />
              </span>
              <span className="record-info">
                <b>{r.filename.replace(/\.[^.]+$/, "")}</b>
                <small>{time(r.metadata_json.duration_ms, true)}</small>
              </span>
              <span
                className={`record-dot ${r.current_run_id ? "done" : ""}`}
              />
            </button>
          ))}
          {!recordings.length && (
            <div className="sidebar-empty">
              <FileAudio size={23} />
              <span>{t("noRecordings")}</span>
            </div>
          )}
        </div>
        <button
          className="import-button"
          disabled={importProgress !== null}
          onClick={() => fileInput.current?.click()}
        >
          <Upload size={16} />
          {importProgress !== null
            ? `${t("importing")} ${Math.round(importProgress * 100)}%`
            : t("import")}
        </button>
        <div className="sidebar-bottom">
          <button disabled={busy} onClick={() => void openDemo()}>
            <Headphones size={16} />
            {t("demo")}
            <ArrowUpRight size={14} />
          </button>
          <button onClick={() => setSettings(true)}>
            <Settings2 size={16} />
            {t("settings")}
            <ChevronRight size={14} />
          </button>
          <div className="privacy-line">
            <ShieldCheck size={13} />
            <span>{t("localOnly")}</span>
          </div>
          <small>
            {t("github")}
            <span>v0.1.0</span>
          </small>
        </div>
      </aside>
      {filesOpen && (
        <button
          className="sidebar-shade"
          aria-label={t("close")}
          onClick={() => setFilesOpen(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <button
            className="mobile-files-button icon-button"
            aria-label={t("filesMenu")}
            onClick={() => setFilesOpen(true)}
          >
            <FolderOpen size={20} />
          </button>
          <div className="breadcrumbs">
            <span>{t("local")}</span>
            <ChevronRight size={13} />
            <b>{project?.name ?? "VoiceLedger"}</b>
          </div>
          <div className="topbar-right">
            <span className="local-indicator">
              <span className="tiny-dot green" />
              LOCAL
            </span>
            <select
              aria-label={t("interfaceLanguage")}
              value={lang}
              onChange={(e) => setLang(e.target.value)}
            >
              <option value="en">EN</option>
              <option value="bg">БГ</option>
            </select>
            <div className="profile-avatar">VL</div>
          </div>
        </header>
        {!recording ? (
          <main className="welcome">
            <span className="welcome-label">
              <AudioLines size={15} />
              VOICELEDGER
            </span>
            <h1>{t("noProject")}</h1>
            <p>{t("emptyText")}</p>
            <div className="welcome-wave" aria-hidden="true">
              {Array.from({ length: 49 }, (_, i) => (
                <i
                  key={i}
                  style={{
                    height:
                      16 +
                      Math.sin(i * 0.8) ** 2 * 45 +
                      Math.sin(i * 0.23) ** 2 * 55,
                  }}
                />
              ))}
            </div>
            <button
              className="button primary"
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={17} />
              {t("chooseAudio")}
            </button>
            <small>{t("formats")}</small>
          </main>
        ) : (
          <>
            <section className="recording-heading">
              <div>
                <h1 title={recording.filename}>
                  {recording.filename.replace(/\.[^.]+$/, "")}
                </h1>
                <div className="recording-metadata">
                  <span>
                    <Clock3 size={13} />
                    {time(recording.metadata_json.duration_ms, true)}
                  </span>
                  <span>
                    <Users size={13} />
                    {detected.length} {t("detected").toLocaleLowerCase()}
                  </span>
                </div>
              </div>
              <div className="heading-actions">
                <button
                  className="button"
                  onClick={() => setExportOpen(true)}
                  disabled={!rows.length}
                >
                  <Download size={15} />
                  {t("export")}
                  <ChevronDown size={12} />
                </button>
                <button
                  className={`button ${!rows.length ? "primary" : "reprocess-secondary"}`}
                  onClick={() => void startJob()}
                  disabled={!!activeJob || busy}
                >
                  {activeJob ? (
                    <Loader2 size={15} className="spin" />
                  ) : (
                    <AudioLines size={15} />
                  )}{" "}
                  {activeJob
                    ? t(activeJob.status as Key)
                    : rows.length
                      ? t("reprocess")
                      : t("process")}
                </button>
                {!!rows.length && (
                  <button
                    className="button primary start-review"
                    onClick={beginReview}
                  >
                    <Play size={16} />
                    {t("startReview")}
                  </button>
                )}
              </div>
            </section>
            <nav className="view-tabs">
              {(
                [
                  ["transcript", FileAudio],
                  ["speakers", Users],
                  ["review", Flag],
                  ["processing", Layers],
                ] as const
              ).map(([v, Icon]) => (
                <button
                  key={v}
                  className={view === v ? "active" : ""}
                  onClick={() => setView(v)}
                >
                  <Icon size={15} />
                  {t(v)}
                  {v === "review" &&
                    rows.filter((r) => r.uncertain).length > 0 && (
                      <span className="tab-count">
                        {rows.filter((r) => r.uncertain).length}
                      </span>
                    )}
                  {v === "speakers" && (
                    <span className="tab-count neutral">{speakers.length}</span>
                  )}
                </button>
              ))}
              <span
                className="mode-indicator"
                onClick={() => setSettings(true)}
              >
                <span className="tiny-dot" />
                {t(mode)}
                <Settings2 size={12} />
              </span>
            </nav>
            {recording.metadata_json.demo && (
              <div className="demo-banner">
                <Headphones size={13} />
                <b>{t("demoLabel")}</b>
                <span>{t("demoHint")}</span>
              </div>
            )}
            {view === "transcript" || view === "review" ? (
              <div
                className={`review-workspace ${selection.length ? "is-reviewing" : ""}`}
              >
                <main className="transcript-main">
                  <Player
                    recording={recording}
                    t={t}
                    onTime={onPlaybackTime}
                    onReady={setMedia}
                  />
                  {conflicts.length > 0 && (
                    <div className="conflict-banner">
                      <AlertCircle size={17} />
                      <div>
                        <b>{t("conflicts")}</b>
                        <p>{t("conflictHint")}</p>
                        {conflicts.map((c, i) => (
                          <details key={i}>
                            <summary>{t("restoreEdit")}</summary>
                            <p>{c.explanation}</p>
                            <pre>{JSON.stringify(c.actions, null, 2)}</pre>
                            <button
                              onClick={() =>
                                void post(
                                  `/corrections/${c.correction_id}/undo`,
                                ).then(refresh)
                              }
                            >
                              {t("undo")}
                            </button>
                          </details>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="transcript-toolbar">
                    <div className="search-field">
                      <Search size={15} />
                      <input
                        aria-label={t("search")}
                        placeholder={t("search")}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      {search && (
                        <button
                          aria-label={t("clear")}
                          onClick={() => setSearch("")}
                        >
                          <X size={13} />
                        </button>
                      )}
                    </div>
                    <details className="transcript-filters">
                      <summary>
                        <Settings2 size={14} />
                        {t("filters")}
                      </summary>
                      <div className="filter-popover">
                        <select
                          aria-label={t("allSpeakers")}
                          value={speakerFilter}
                          onChange={(e) => setSpeakerFilter(e.target.value)}
                        >
                          <option value="">{t("allSpeakers")}</option>
                          {speakers.map((s) => (
                            <option key={s.id} value={s.id}>
                              {s.name}
                            </option>
                          ))}
                          {detected.map((c, i) => (
                            <option key={c} value={c}>
                              {lang === "bg" ? "Глас" : "Voice"}{" "}
                              {String(i + 1).padStart(2, "0")}
                            </option>
                          ))}
                        </select>
                        <button
                          className={`filter-button ${uncertainOnly ? "selected" : ""}`}
                          onClick={() => setUncertainOnly(!uncertainOnly)}
                          aria-pressed={uncertainOnly}
                        >
                          <Flag size={13} />
                          {t("onlyUncertain")}
                        </button>
                        <label className="show-excluded">
                          <input
                            type="checkbox"
                            checked={showExcluded}
                            onChange={(e) => setShowExcluded(e.target.checked)}
                          />
                          {t("showExcluded")}
                        </label>
                      </div>
                    </details>
                  </div>
                  <div className="transcript-labels">
                    <span>
                      {t("readHint")}
                      <span className="muted">
                        {" "}
                        {loading
                          ? `${rows.length} / ${total}`
                          : filtered.length}
                      </span>
                    </span>
                    <span>
                      {selection.length > 0 ? (
                        <button onClick={() => setSelectionIds([])}>
                          {selection.length} {t("selectionCount")}{" "}
                          <X size={11} />
                        </button>
                      ) : loading ? (
                        <Loader2 size={13} className="spin" />
                      ) : (
                        <>
                          <span className="tiny-dot green" />
                          {t("saved")}
                        </>
                      )}
                    </span>
                  </div>
                  <div className="transcript-scroll" ref={scrollRef}>
                    {!rows.length && !loading ? (
                      <div className="empty-transcript">
                        <div className="empty-symbol">
                          <AudioLines size={30} />
                        </div>
                        <h2>{t("noTranscript")}</h2>
                        <p>{t("startHint")}</p>
                        <ModeCards mode={mode} setMode={setMode} t={t} />
                        <button
                          className="button primary"
                          disabled={!!activeJob}
                          onClick={() => void startJob()}
                        >
                          <AudioLines size={16} />
                          {t("process")}
                        </button>
                      </div>
                    ) : !filtered.length ? (
                      <div className="empty-state">
                        <Flag size={28} />
                        <h2>
                          {view === "review"
                            ? t("emptyReview")
                            : t("noResults")}
                        </h2>
                        <p>{view === "review" ? t("emptyReviewHint") : ""}</p>
                      </div>
                    ) : (
                      <div
                        style={{
                          height: virtualizer.getTotalSize(),
                          width: "100%",
                          position: "relative",
                        }}
                      >
                        {virtualizer.getVirtualItems().map((item) => {
                          const row = filtered[item.index],
                            chosen = selectionIds.includes(row.id),
                            isPlaying =
                              playhead >= row.start_ms && playhead < row.end_ms,
                            shade = color(row.speaker_id ?? row.cluster);
                          return (
                            <div
                              key={row.id}
                              data-index={item.index}
                              ref={virtualizer.measureElement}
                              className={`turn-row ${chosen ? "chosen" : ""} ${isPlaying ? "playing" : ""} ${row.excluded ? "excluded" : ""}`}
                              style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                width: "100%",
                                transform: `translateY(${item.start}px)`,
                              }}
                              role="button"
                              tabIndex={0}
                              aria-pressed={chosen}
                              onClick={(e) =>
                                selectTurn(row, e.ctrlKey || e.metaKey)
                              }
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  selectTurn(row, e.ctrlKey || e.metaKey);
                                }
                              }}
                            >
                              <span className="turn-time">
                                {time(row.start_ms)}
                              </span>
                              <div
                                className="turn-avatar"
                                style={{
                                  background: shade + "1c",
                                  color: shade,
                                }}
                              >
                                {row.speaker_id
                                  ? displayName(row)
                                      .slice(0, 2)
                                      .toLocaleUpperCase()
                                  : String(
                                      detected.indexOf(row.cluster ?? "") + 1,
                                    ).padStart(2, "0")}
                              </div>
                              <div className="turn-body">
                                <div className="turn-speaker">
                                  <b style={{ color: shade }}>
                                    {displayName(row)}
                                  </b>
                                  {row.manual && (
                                    <span className="turn-tag">
                                      <Check size={10} />
                                      {t("manual")}
                                    </span>
                                  )}
                                  {row.uncertain && (
                                    <span className="turn-tag warning">
                                      <Flag size={10} />
                                      {t("uncertain")}
                                    </span>
                                  )}
                                  {row.overlap && (
                                    <span className="turn-tag">
                                      {t("overlap")}
                                    </span>
                                  )}
                                  {row.excluded && (
                                    <span className="turn-tag">
                                      {t("excluded")}
                                    </span>
                                  )}
                                </div>
                                <p className={!row.text ? "missing-text" : ""}>
                                  {row.text || t("untranscribed")}
                                </p>
                              </div>
                              <span className="turn-check">
                                {chosen ? (
                                  <Check size={14} />
                                ) : (
                                  <ChevronRight size={13} />
                                )}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  <div className="transcript-foot">
                    <span>{t("shortcuts")}</span>
                    <span className="mono">
                      {rows.length} / {total}
                    </span>
                  </div>
                </main>
                <ReviewPanel
                  recording={recording}
                  selection={selection}
                  speakers={speakers}
                  revision={revision}
                  t={t}
                  playhead={playhead}
                  assistantReady={assistantReady}
                  onRefresh={refresh}
                  notify={notify}
                  proposal={proposal}
                  setProposal={setProposal}
                  preview={preview}
                  busy={busy}
                  onStart={beginReview}
                  onPlay={playExcerpt}
                  onNext={() => moveReview(1)}
                  onPrevious={() => moveReview(-1)}
                  onClose={() => {
                    setSelectionIds([]);
                    media?.pause();
                    clipStop.current = null;
                  }}
                  onSaved={savedReview}
                  position={reviewPosition + 1}
                  count={filtered.length}
                  playing={clipPlaying}
                />
              </div>
            ) : view === "speakers" ? (
              <main className="library-page">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">{t("registered")}</span>
                    <h2>
                      {t("speakers")}{" "}
                      <span>{speakers.length.toString().padStart(2, "0")}</span>
                    </h2>
                  </div>
                  <p>{t("newNameHelp")}</p>
                </div>
                {!speakers.length ? (
                  <div className="empty-state">
                    <Users size={34} />
                    <h2>{t("emptyLibrary")}</h2>
                    <p>{t("noSpeakers")}</p>
                    <button
                      className="button"
                      onClick={() => setView("transcript")}
                    >
                      {t("transcript")}
                      <ChevronRight size={14} />
                    </button>
                  </div>
                ) : (
                  <div className="speaker-cards">
                    {speakers.map((s) => (
                      <article className="speaker-card" key={s.id}>
                        <div className="speaker-card-top">
                          <div
                            className="large-avatar"
                            style={{
                              background: color(s.id) + "20",
                              color: color(s.id),
                            }}
                          >
                            {s.name.slice(0, 2).toLocaleUpperCase()}
                          </div>
                          <span className="verified-label">
                            <Check size={12} />
                            {t("confirmation")}
                          </span>
                        </div>
                        <h3>{s.name}</h3>
                        <p>
                          {s.samples.length} {t("samples")}
                        </p>
                        <div className="reference-list">
                          {s.samples.map((sample) => (
                            <button
                              key={sample.id}
                              onClick={() => setSampleClip(sample)}
                            >
                              <Headphones size={14} />
                              {time(sample.start_ms)}–{time(sample.end_ms)}
                              <Play size={12} />
                            </button>
                          ))}
                        </div>
                        {s.notes && <p className="small">{s.notes}</p>}
                      </article>
                    ))}
                  </div>
                )}
                {detected.length > 0 && (
                  <section className="match-section">
                    <div className="section-heading">
                      <h2>{t("detected")}</h2>
                      <span className="small muted">{t("referenceHint")}</span>
                    </div>
                    <div className="speaker-cards">
                      {detected.map((cluster, index) => {
                        const turns = rows.filter(
                          (row) => row.cluster === cluster,
                        );
                        const clean = turns
                          .filter(
                            (row) =>
                              !row.overlap &&
                              !row.excluded &&
                              row.end_ms - row.start_ms >= 1000 &&
                              row.end_ms - row.start_ms <= 15000,
                          )
                          .sort(
                            (a, b) =>
                              Number(a.uncertain) - Number(b.uncertain) ||
                              Math.abs(a.end_ms - a.start_ms - 8000) -
                                Math.abs(b.end_ms - b.start_ms - 8000),
                          )
                          .slice(0, 3);
                        return (
                          <article className="speaker-card" key={cluster}>
                            <div className="speaker-card-top">
                              <div
                                className="large-avatar"
                                style={{
                                  background: color(cluster) + "20",
                                  color: color(cluster),
                                }}
                              >
                                {String(index + 1).padStart(2, "0")}
                              </div>
                              <span className="small muted">
                                {turns.length} {t("turns")}
                              </span>
                            </div>
                            <h3>
                              {lang === "bg" ? "Глас" : "Voice"}{" "}
                              {String(index + 1).padStart(2, "0")}
                            </h3>
                            <div className="reference-list">
                              {clean.map((row) => (
                                <button
                                  key={row.id}
                                  onClick={() => setSampleClip(row)}
                                >
                                  <Headphones size={14} />
                                  {time(row.start_ms)}–{time(row.end_ms)}
                                  <Play size={12} />
                                </button>
                              ))}
                            </div>
                            <button
                              className="text-button"
                              onClick={() => {
                                const row = clean[0] ?? turns[0];
                                setSelectionIds([row.id]);
                                setSpeakerFilter(cluster);
                                setView("transcript");
                              }}
                            >
                              {t("view")}
                              <ChevronRight size={13} />
                            </button>
                          </article>
                        );
                      })}
                    </div>
                  </section>
                )}
                <section className="match-section">
                  <div className="section-heading">
                    <h2>{t("matches")}</h2>
                    <span className="small muted">{t("similarity")}</span>
                  </div>
                  {matches.some((m) => m.candidates.length) ? (
                    matches
                      .filter((m) => m.candidates.length)
                      .map((match) => (
                        <article className="match-card" key={match.cluster}>
                          <b>
                            {lang === "bg" ? "Глас" : "Voice"}{" "}
                            {String(
                              detected.indexOf(match.cluster) + 1,
                            ).padStart(2, "0")}
                          </b>
                          <div>
                            {match.candidates.map((candidate) => (
                              <div
                                className="match-candidate"
                                key={candidate.speaker_id}
                              >
                                <span
                                  className="tiny-dot"
                                  style={{
                                    background: color(candidate.speaker_id),
                                  }}
                                />
                                <b>{candidate.name}</b>
                                <span className="mono muted">
                                  {candidate.similarity.toFixed(3)}
                                </span>
                                <button
                                  className="icon-button"
                                  aria-label={t("listen")}
                                  onClick={() => setSampleClip(candidate)}
                                >
                                  <Headphones size={15} />
                                </button>
                                <button
                                  className="text-button"
                                  onClick={() => {
                                    const found = rows.find(
                                      (r) => r.cluster === match.cluster,
                                    );
                                    if (found) {
                                      setSelectionIds([found.id]);
                                      setView("transcript");
                                      void preview([
                                        {
                                          kind: "assign",
                                          row_ids: [found.id],
                                          speaker_id: candidate.speaker_id,
                                          scope: "cluster",
                                        },
                                      ]).catch((e) => notify(e.message, true));
                                    }
                                  }}
                                >
                                  {t("confirmMatch")}
                                  <ChevronRight size={13} />
                                </button>
                              </div>
                            ))}
                          </div>
                        </article>
                      ))
                  ) : (
                    <p className="muted">{t("noMatches")}</p>
                  )}
                </section>
              </main>
            ) : (
              <main className="jobs-page">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">{t("local")}</span>
                    <h2>{t("processing")}</h2>
                  </div>
                  <p>{t("jobHint")}</p>
                </div>
                <ModeCards mode={mode} setMode={setMode} t={t} />
                <div className="jobs-list">
                  {jobs.length ? (
                    jobs.map((job) => (
                      <article className="job-card" key={job.id}>
                        <div className="job-icon">
                          {job.status === "running" ? (
                            <Loader2 size={22} className="spin" />
                          ) : job.status === "completed" ? (
                            <Check size={22} />
                          ) : (
                            <AudioLines size={22} />
                          )}
                        </div>
                        <div className="job-content">
                          <div className="job-title">
                            <b>
                              {recordings.find((r) => r.id === job.recording_id)
                                ?.filename ?? t("models")}
                            </b>
                            <span className={`status-badge ${job.status}`}>
                              {t(job.status as Key)}
                            </span>
                          </div>
                          <div className="job-details">
                            <span>
                              {t(
                                job.stage === "download"
                                  ? "downloadStage"
                                  : ((job.stage in
                                    {
                                      normalize: 1,
                                      asr: 1,
                                      diarization: 1,
                                      reference: 1,
                                      queued: 1,
                                      completed: 1,
                                    }
                                      ? job.stage
                                      : "processing") as Key),
                              )}
                            </span>
                            <span>{t(job.mode)}</span>
                            <span className="mono">
                              {Math.round(job.progress * 100)}%
                            </span>
                          </div>
                          <div className="progress-track">
                            <span style={{ width: `${job.progress * 100}%` }} />
                          </div>
                          {job.error && (
                            <p className="job-error">{job.error}</p>
                          )}
                        </div>
                        <div>
                          {["queued", "running"].includes(job.status) ? (
                            <button
                              className="button small-button"
                              onClick={() =>
                                void post(`/jobs/${job.id}/cancel`).catch((e) =>
                                  notify(e.message, true),
                                )
                              }
                            >
                              {t("stop")}
                            </button>
                          ) : ["failed", "cancelled", "interrupted"].includes(
                              job.status,
                            ) ? (
                            <button
                              className="button small-button"
                              onClick={() =>
                                void post(`/jobs/${job.id}/resume`).catch((e) =>
                                  notify(e.message, true),
                                )
                              }
                            >
                              {t("resume")}
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">
                      <Layers size={28} />
                      <h2>{t("noJobs")}</h2>
                    </div>
                  )}
                </div>
              </main>
            )}
          </>
        )}
      </div>
      {settings && (
        <div
          className="modal-backdrop"
          onClick={(e) => modalClose(e, () => setSettings(false))}
        >
          <section
            className="modal settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
          >
            <div className="modal-title">
              <div>
                <span className="eyebrow">VOICELEDGER</span>
                <h2 id="settings-title">{t("settings")}</h2>
              </div>
              <button
                className="icon-button"
                aria-label={t("close")}
                onClick={() => setSettings(false)}
              >
                <X size={20} />
              </button>
            </div>
            <h3>{t("mode")}</h3>
            <ModeCards mode={mode} setMode={setMode} t={t} />
            <div className="settings-fields">
              <label>
                {t("language")}
                <select
                  value={audioLanguage}
                  onChange={(e) => setAudioLanguage(e.target.value)}
                >
                  <option value="bg">{t("bg")}</option>
                  <option value="en">{t("en")}</option>
                  <option value="auto">{t("auto")}</option>
                </select>
              </label>
              <label>
                {t("interfaceLanguage")}
                <select value={lang} onChange={(e) => setLang(e.target.value)}>
                  <option value="en">English</option>
                  <option value="bg">Български</option>
                </select>
              </label>
            </div>
            <div className="memory-card">
              <Layers size={17} />
              <span>
                {t("availableMemory")}
                <b>{health.available_ram_gib} GB</b>
              </span>
              <p>{t("memoryHint")}</p>
            </div>
            <div className="section-heading">
              <h3>{t("models")}</h3>
              <a href="/setup" target="_blank" rel="noreferrer">
                {t("setup")}
                <ArrowUpRight size={13} />
              </a>
            </div>
            {recording && (
              <button
                className="button"
                disabled={!!activeJob || busy}
                onClick={() => {
                  setSettings(false);
                  void startJob();
                }}
              >
                <AudioLines size={16} />
                {t(rows.length ? "reprocess" : "process")}
              </button>
            )}
            <p className="small muted">{t("modelHint")}</p>
            <div className="model-rows">
              {(["fast", "balanced", "accuracy", "diarization"] as const).map(
                (m) => (
                  <div key={m}>
                    <span>
                      <span
                        className={`tiny-dot ${models[m]?.ready ? "green" : ""}`}
                      />
                      {t(m)}
                    </span>
                    <span className="small muted">
                      {models[m]?.ready ? t("downloaded") : t("missing")}
                    </span>
                    {m !== "diarization" && (
                      <button
                        className="text-button"
                        disabled={models[m]?.ready && models.diarization?.ready}
                        onClick={() => {
                          void post(`/models/${m}/download`)
                            .then(() => {
                              notify(t("jobStarted"));
                              setView("processing");
                              setSettings(false);
                            })
                            .catch((e) => notify(e.message, true));
                        }}
                      >
                        {t("download")}
                      </button>
                    )}
                  </div>
                ),
              )}
            </div>
          </section>
        </div>
      )}
      {projectOpen && (
        <div
          className="modal-backdrop"
          onClick={(e) => modalClose(e, () => setProjectOpen(false))}
        >
          <form
            className="modal compact-modal"
            onSubmit={(e) => {
              e.preventDefault();
              void createProject();
            }}
          >
            <div className="modal-title">
              <h2>{t("newProject")}</h2>
              <button
                type="button"
                className="icon-button"
                aria-label={t("close")}
                onClick={() => setProjectOpen(false)}
              >
                <X size={19} />
              </button>
            </div>
            <label>
              {t("projectName")}
              <input
                autoFocus
                required
                maxLength={120}
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
              />
            </label>
            <button
              className="button primary full"
              disabled={!projectName.trim()}
            >
              {t("create")}
            </button>
          </form>
        </div>
      )}
      {exportOpen && (
        <div
          className="modal-backdrop"
          onClick={(e) => modalClose(e, () => setExportOpen(false))}
        >
          <section
            className="modal compact-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="export-title"
          >
            <div className="modal-title">
              <h2 id="export-title">{t("export")}</h2>
              <button
                className="icon-button"
                aria-label={t("close")}
                onClick={() => setExportOpen(false)}
              >
                <X size={19} />
              </button>
            </div>
            <label>
              {t("recordings")}
              <select
                value={exportScope}
                onChange={(e) => setExportScope(e.target.value)}
              >
                <option value="one">{t("exportOne")}</option>
                <option value="all">{t("exportAll")}</option>
              </select>
            </label>
            <div className="format-options">
              {["txt", "srt", "csv", "json"].map((f) => (
                <button
                  className={f === exportFormat ? "selected" : ""}
                  key={f}
                  onClick={() => setExportFormat(f)}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={includeExcluded}
                onChange={(e) => setIncludeExcluded(e.target.checked)}
              />
              {t("includeExcluded")}
            </label>
            <p className="small muted">{t("exportHint")}</p>
            <button
              className="button primary full"
              onClick={() =>
                void download(
                  `/projects/${projectId}/export/${exportFormat}?include_excluded=${includeExcluded}${exportScope === "one" ? `&recording_id=${recordingId}` : ""}`,
                  `voiceledger.${exportFormat}`,
                )
                  .then(() => setExportOpen(false))
                  .catch((e) => notify(e.message, true))
              }
            >
              <Download size={16} />
              {t("downloadExport")}
            </button>
          </section>
        </div>
      )}
      {sampleClip && (
        <div
          className="modal-backdrop"
          onClick={(e) => modalClose(e, () => setSampleClip(null))}
        >
          <section className="modal compact-modal">
            <div className="modal-title">
              <h2>{t("listen")}</h2>
              <button
                className="icon-button"
                aria-label={t("close")}
                onClick={() => setSampleClip(null)}
              >
                <X size={19} />
              </button>
            </div>
            <audio
              controls
              autoPlay
              src={`/api/v1/recordings/${sampleClip.recording_id}/clip?start_ms=${sampleClip.start_ms}&end_ms=${sampleClip.end_ms}`}
            />
            <p className="mono muted">
              {time(sampleClip.start_ms)}–{time(sampleClip.end_ms)}
            </p>
          </section>
        </div>
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <AlertCircle size={18} /> : <Check size={18} />}
          <span>{toast.text}</span>
          <button
            className="icon-button"
            aria-label={t("close")}
            onClick={() => setToast(null)}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {drop && (
        <div className="drop-overlay">
          <Upload size={42} />
          <h2>{t("drop")}</h2>
          <p>{t("formats")}</p>
        </div>
      )}
    </div>
  );
}
