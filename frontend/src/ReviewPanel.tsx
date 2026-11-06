import { useEffect, useState } from "react";
import {
  Check,
  ChevronRight,
  Headphones,
  MessageSquare,
  Scissors,
  Undo2,
  UserRound,
  ArrowUpRight,
  Loader2,
  Flag,
  Split,
  Merge,
} from "lucide-react";
import { api, post, time } from "./api";
import type {
  Action,
  Correction,
  Proposal,
  Recording,
  Speaker,
  Turn,
} from "./types";
import type { Key } from "./i18n";

type Props = {
  recording: Recording;
  selection: Turn[];
  speakers: Speaker[];
  revision: number;
  t: (k: Key) => string;
  playhead: number;
  assistantReady: boolean;
  onRefresh: () => void;
  notify: (message: string, error?: boolean) => void;
  proposal: Proposal | null;
  setProposal: (p: Proposal | null) => void;
  preview: (actions: Action[]) => Promise<void>;
  busy: boolean;
};
export default function ReviewPanel(p: Props) {
  const {
    recording,
    selection,
    speakers,
    revision,
    t,
    playhead,
    notify,
    proposal,
    setProposal,
    preview,
    onRefresh,
  } = p;
  const [tab, setTab] = useState<"selection" | "assistant">("selection"),
    [name, setName] = useState(""),
    [speaker, setSpeaker] = useState(""),
    [scope, setScope] = useState<"selected" | "cluster">("selected");
  const [text, setText] = useState(""),
    [start, setStart] = useState("0"),
    [end, setEnd] = useState("0"),
    [rightText, setRightText] = useState("");
  const [instruction, setInstruction] = useState(""),
    [asking, setAsking] = useState(false),
    [clean, setClean] = useState(false),
    [minimum, setMinimum] = useState("2"),
    [mergeTarget, setMergeTarget] = useState("");
  const [history, setHistory] = useState<Correction[]>([]),
    [applying, setApplying] = useState(false);
  const first = selection[0],
    ids = selection.map((s) => s.id);
  useEffect(() => {
    setText(first?.text ?? "");
    setName("");
    setSpeaker(first?.speaker_id ?? "");
    setClean(false);
    setRightText("");
    setStart(
      String(
        (selection.length ? Math.min(...selection.map((s) => s.start_ms)) : 0) /
          1000,
      ),
    );
    setEnd(
      String(
        (selection.length ? Math.max(...selection.map((s) => s.end_ms)) : 0) /
          1000,
      ),
    );
    setProposal(null);
  }, [ids.join(","), recording.id, revision]);
  useEffect(() => {
    api<Correction[]>(`/recordings/${recording.id}/corrections`)
      .then(setHistory)
      .catch(() => {});
  }, [recording.id, revision]);
  const act = (action: Action) =>
    preview([{ ...action, row_ids: ids }]).catch((e) =>
      notify(e.message, true),
    );
  async function ask() {
    if (!first) return;
    setAsking(true);
    setProposal(null);
    try {
      setProposal(
        await post<Proposal>("/assistant/preview", {
          recording_id: recording.id,
          base_revision: revision,
          row_ids: ids,
          instruction,
        }),
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setAsking(false);
    }
  }
  async function apply() {
    if (!proposal?.id) return;
    setApplying(true);
    try {
      await post(`/proposals/${proposal.id}/apply`);
      setProposal(null);
      notify(t("correctionApplied"));
      onRefresh();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setApplying(false);
    }
  }
  async function reference() {
    if (!first?.speaker_id) {
      notify(t("referenceSpeaker"), true);
      return;
    }
    if (!clean) {
      notify(t("confirmReference"), true);
      return;
    }
    try {
      await post(`/speakers/${first.speaker_id}/samples`, {
        recording_id: recording.id,
        start_ms: Math.round(Number(start) * 1000),
        end_ms: Math.round(Number(end) * 1000),
        confirmed: true,
      });
      notify(t("referenceSaved"));
      onRefresh();
    } catch (e) {
      notify((e as Error).message, true);
    }
  }
  const previewName = () => {
    if (!speaker && !name.trim()) {
      notify(t("nameRequired"), true);
      return;
    }
    void act({
      kind: "assign",
      ...(speaker ? { speaker_id: speaker } : { name: name.trim() }),
      scope,
    });
  };
  const split = () => {
    if (!first) return;
    const point =
      playhead > first.start_ms && playhead < first.end_ms
        ? playhead
        : Math.round((first.start_ms + first.end_ms) / 2);
    void act({
      kind: "split",
      split_at_ms: point,
      ...(!first.words.length ? { text, right_text: rightText } : {}),
    });
  };
  return (
    <aside className="review-panel">
      <div className="panel-tabs">
        <button
          className={tab === "selection" ? "active" : ""}
          onClick={() => setTab("selection")}
        >
          <UserRound size={15} />
          {t("selection")}
        </button>
        <button
          className={tab === "assistant" ? "active" : ""}
          onClick={() => setTab("assistant")}
        >
          <MessageSquare size={15} />
          {t("assistant")}
          <span className="tiny-dot" />
        </button>
      </div>
      <div className="panel-scroll">
        {proposal && (
          <section
            className={`proposal ${proposal.clarification ? "clarification" : ""}`}
            role="status"
          >
            <div className="eyebrow">
              {proposal.clarification ? t("clarify") : t("preview")}
            </div>
            <p>
              {proposal.clarification ??
                (proposal.explanation === "Manual correction"
                  ? t("manualCorrection")
                  : proposal.explanation)}
            </p>
            {!proposal.clarification && (
              <>
                <div className="proposal-count">
                  {t("affected")}
                  <b>{proposal.affected_turns ?? "—"}</b>
                </div>
                <div className="action-summary">
                  {proposal.actions.map((a, i) => (
                    <div className="proposal-action" key={i}>
                      <span>
                        {a.kind === "assign"
                          ? (a.name ??
                            speakers.find((s) => s.id === a.speaker_id)?.name)
                          : t(
                              (
                                {
                                  mark: a.category ?? "uncertain",
                                  reanalyze: "reanalyze",
                                  split: "split",
                                  bounds: "adjustBounds",
                                  text: "text",
                                  merge: "merge",
                                } as Record<string, Key>
                              )[a.kind] ?? "preview",
                            )}
                      </span>
                      {a.kind === "assign" && (
                        <small>
                          {t(
                            a.scope === "cluster"
                              ? "allCluster"
                              : "selectedTurns",
                          )}
                        </small>
                      )}
                      {a.kind === "merge" && (
                        <small>
                          {
                            speakers.find((s) => s.id === a.source_speaker_id)
                              ?.name
                          }{" "}
                          → {speakers.find((s) => s.id === a.speaker_id)?.name}{" "}
                          · {t("project")}
                        </small>
                      )}
                      {(a.kind === "bounds" || a.kind === "reanalyze") && (
                        <small className="mono">
                          {((a.start_ms ?? 0) / 1000).toFixed(3)}s →{" "}
                          {((a.end_ms ?? 0) / 1000).toFixed(3)}s
                        </small>
                      )}
                      {a.kind === "reanalyze" && a.min_speakers && (
                        <small>
                          {t("minimum")}: {a.min_speakers}
                        </small>
                      )}
                      {a.kind === "split" && (
                        <small className="mono">
                          {((a.split_at_ms ?? 0) / 1000).toFixed(3)}s
                        </small>
                      )}
                      {a.kind === "text" && (
                        <p className="replacement-preview">{a.text}</p>
                      )}
                    </div>
                  ))}
                </div>
                <button
                  className="button primary full"
                  onClick={() => void apply()}
                  disabled={applying}
                >
                  {applying ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Check size={16} />
                  )}{" "}
                  {t("apply")}
                </button>
              </>
            )}
            <button className="text-button" onClick={() => setProposal(null)}>
              {t("dismiss")}
            </button>
          </section>
        )}
        {!first ? (
          <div className="panel-empty">
            <Headphones size={30} />
            <h3>{t("selectTurn")}</h3>
            <p>{t("assistantHint")}</p>
          </div>
        ) : (
          <>
            <div className="selection-header">
              <span className="eyebrow">
                {String(selection.length).padStart(2, "0")}{" "}
                {t("selectionCount")}
              </span>
              <span className="mono muted">
                {time(first.start_ms)}–{time(first.end_ms)}
              </span>
            </div>
            <section className="clip-card">
              <div className="clip-title">
                <Headphones size={14} />
                {t("clip")}
              </div>
              <audio
                controls
                preload="none"
                key={`${recording.id}:${start}:${end}`}
                src={
                  Number(end) > Number(start) &&
                  Number(end) - Number(start) <= 120
                    ? `/api/v1/recordings/${recording.id}/clip?start_ms=${Math.round(Number(start) * 1000)}&end_ms=${Math.round(Number(end) * 1000)}`
                    : undefined
                }
              />
            </section>
            {tab === "assistant" ? (
              <section className="form-section">
                <h3>{t("assistantHint")}</h3>
                <textarea
                  aria-label={t("assistant")}
                  rows={6}
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder={t("assistantPlaceholder")}
                />
                <button
                  className="button primary full"
                  onClick={() => void ask()}
                  disabled={asking || !instruction.trim() || !p.assistantReady}
                >
                  {asking ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <ArrowUpRight size={16} />
                  )}{" "}
                  {asking ? t("thinking") : t("ask")}
                </button>
                {!p.assistantReady && (
                  <p className="warning-text">{t("assistantUnavailable")}</p>
                )}
                <p className="privacy-note">{t("assistantPrivacy")}</p>
              </section>
            ) : (
              <>
                <section className="form-section">
                  <h3>{t("nameSpeaker")}</h3>
                  <p className="small muted">{t("newNameHelp")}</p>
                  <input
                    aria-label={t("newName")}
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      setSpeaker("");
                    }}
                    placeholder={t("newName")}
                  />
                  {speakers.length > 0 && (
                    <>
                      <div className="or-line">{t("or")}</div>
                      <select
                        aria-label={t("existingSpeaker")}
                        value={speaker}
                        onChange={(e) => {
                          setSpeaker(e.target.value);
                          setName("");
                        }}
                      >
                        <option value="">{t("existingSpeaker")}</option>
                        {speakers.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  <label>
                    {t("scope")}
                    <select
                      value={scope}
                      onChange={(e) =>
                        setScope(e.target.value as "selected" | "cluster")
                      }
                    >
                      <option value="selected">{t("selectedTurns")}</option>
                      <option value="cluster">{t("allCluster")}</option>
                    </select>
                  </label>
                  <button
                    className="button full"
                    disabled={p.busy}
                    onClick={previewName}
                  >
                    <UserRound size={15} />
                    {t("assign")}
                  </button>
                </section>
                <section className="form-section">
                  <h3>{t("mark")}</h3>
                  <div className="category-grid">
                    {(
                      [
                        "speech",
                        "noise",
                        "irrelevant",
                        "overlap",
                        "uncertain",
                      ] as const
                    ).map((category) => (
                      <button
                        key={category}
                        onClick={() => void act({ kind: "mark", category })}
                      >
                        {t(category)}
                      </button>
                    ))}
                  </div>
                </section>
                {selection.length === 1 && (
                  <section className="form-section">
                    <h3>{t("text")}</h3>
                    <textarea
                      aria-label={t("text")}
                      value={text}
                      rows={4}
                      onChange={(e) => setText(e.target.value)}
                    />
                    <button
                      className="button full"
                      onClick={() => void act({ kind: "text", text })}
                    >
                      {t("editText")}
                    </button>
                    <div className="two-fields">
                      <label>
                        {t("start")}
                        <input
                          type="number"
                          min="0"
                          step="0.001"
                          value={start}
                          onChange={(e) => setStart(e.target.value)}
                        />
                      </label>
                      <label>
                        {t("end")}
                        <input
                          type="number"
                          min="0"
                          step="0.001"
                          value={end}
                          onChange={(e) => setEnd(e.target.value)}
                        />
                      </label>
                    </div>
                    <button
                      className="button full"
                      onClick={() =>
                        void act({
                          kind: "bounds",
                          start_ms: Math.round(Number(start) * 1000),
                          end_ms: Math.round(Number(end) * 1000),
                        })
                      }
                    >
                      {t("adjustBounds")}
                    </button>
                    {!first.words.length && (
                      <>
                        <label>
                          {t("leftText")}
                          <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                          />
                        </label>
                        <label>
                          {t("rightText")}
                          <textarea
                            value={rightText}
                            onChange={(e) => setRightText(e.target.value)}
                          />
                        </label>
                      </>
                    )}
                    <button className="button full" onClick={split}>
                      <Scissors size={15} />
                      {t("split")}
                    </button>
                    <p className="small muted">{t("splitHint")}</p>
                  </section>
                )}
                <section className="form-section">
                  <h3>{t("saveReference")}</h3>
                  <p className="small muted">{t("referenceHint")}</p>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={clean}
                      onChange={(e) => setClean(e.target.checked)}
                    />
                    <span>{t("cleanConfirm")}</span>
                  </label>
                  <button
                    className="button full"
                    onClick={() => void reference()}
                    disabled={!first.speaker_id || !clean}
                  >
                    <Headphones size={15} />
                    {t("saveReference")}
                  </button>
                </section>
                <section className="form-section">
                  <h3>{t("reanalyze")}</h3>
                  <p className="small muted">{t("recheckHint")}</p>
                  <label>
                    {t("minimum")}
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={minimum}
                      onChange={(e) => setMinimum(e.target.value)}
                    />
                  </label>
                  <button
                    className="button full"
                    onClick={() =>
                      void act({
                        kind: "reanalyze",
                        start_ms: Math.round(Number(start) * 1000),
                        end_ms: Math.round(Number(end) * 1000),
                        min_speakers: Number(minimum),
                      })
                    }
                  >
                    <Split size={15} />
                    {t("reanalyze")}
                  </button>
                </section>
                {first.speaker_id && speakers.length > 1 && (
                  <section className="form-section">
                    <h3>{t("merge")}</h3>
                    <select
                      aria-label={t("mergeInto")}
                      value={mergeTarget}
                      onChange={(e) => setMergeTarget(e.target.value)}
                    >
                      <option value="">{t("mergeInto")}</option>
                      {speakers
                        .filter((s) => s.id !== first.speaker_id)
                        .map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                    </select>
                    <button
                      className="button full"
                      disabled={!mergeTarget}
                      onClick={() =>
                        void act({
                          kind: "merge",
                          source_speaker_id: first.speaker_id!,
                          speaker_id: mergeTarget,
                        })
                      }
                    >
                      <Merge size={15} />
                      {t("previewMerge")}
                    </button>
                  </section>
                )}
              </>
            )}
          </>
        )}
        <section className="form-section history">
          <h3>
            <Undo2 size={14} />
            {t("history")}
          </h3>
          {!history.length ? (
            <p className="small muted">{t("noHistory")}</p>
          ) : (
            history.slice(0, 8).map((edit) => (
              <div key={edit.id}>
                <span>
                  {edit.explanation === "Manual correction"
                    ? t("manualCorrection")
                    : edit.explanation}
                </span>
                {edit.active && (
                  <button
                    className="text-button"
                    onClick={() => {
                      void post(`/corrections/${edit.id}/undo`)
                        .then(() => {
                          notify(t("reverted"));
                          onRefresh();
                        })
                        .catch((e) => notify(e.message, true));
                    }}
                  >
                    {t("undo")}
                  </button>
                )}
              </div>
            ))
          )}
        </section>
      </div>
      <div className="panel-foot">
        <span className="tiny-dot green" />
        {t("saved")}
      </div>
    </aside>
  );
}
