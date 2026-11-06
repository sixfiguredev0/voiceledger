import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  AudioLines,
  Volume2,
} from "lucide-react";
import { api, time } from "./api";
import type { Recording } from "./types";
import type { Key } from "./i18n";

type Props = {
  recording: Recording;
  t: (key: Key) => string;
  onTime: (ms: number) => void;
  onReady: (audio: HTMLAudioElement | null) => void;
};
export default function Player({ recording, t, onTime, onReady }: Props) {
  const media = useRef<HTMLAudioElement>(null),
    wave = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(0),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState("1");
  const [hasPeaks, setHasPeaks] = useState(false);
  useEffect(() => {
    onReady(media.current);
    setPosition(0);
    setPlaying(false);
    return () => onReady(null);
  }, [recording.id, onReady]);
  useEffect(() => {
    let destroyed = false,
      ws: WaveSurfer | undefined;
    setHasPeaks(false);
    api<{ peaks: number[]; duration: number }>(
      `/recordings/${recording.id}/peaks`,
    )
      .then((value) => {
        if (destroyed || !wave.current || !media.current || !value.peaks.length)
          return;
        ws = WaveSurfer.create({
          container: wave.current,
          media: media.current,
          peaks: [value.peaks],
          duration: value.duration,
          waveColor: "#68746c",
          progressColor: "#e9bf7a",
          cursorColor: "#e9bf7a",
          height: 40,
          barWidth: 2,
          barGap: 2,
          barRadius: 2,
          normalize: false,
        });
        ws.on("error", () => setHasPeaks(false));
        setHasPeaks(true);
      })
      .catch(() => {});
    return () => {
      destroyed = true;
      ws?.destroy();
    };
  }, [recording.id, recording.revision]);
  const seek = (delta: number) => {
    if (media.current)
      media.current.currentTime = Math.max(
        0,
        Math.min(
          recording.metadata_json.duration_ms / 1000,
          media.current.currentTime + delta,
        ),
      );
  };
  return (
    <section className="player" aria-label={t("timeline")}>
      <div className="player-top">
        <span className="eyebrow">
          <AudioLines size={14} />
          {t("timeline")}
        </span>
      </div>
      <audio
        ref={media}
        src={`/api/v1/recordings/${recording.id}/audio`}
        preload="metadata"
        onTimeUpdate={() => {
          const ms = Math.round((media.current?.currentTime ?? 0) * 1000);
          setPosition(ms);
          onTime(ms);
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
      <div className="wave-wrap">
        <div ref={wave} className="waveform" />
        {!hasPeaks && (
          <input
            aria-label={t("timeline")}
            className="timeline-fallback"
            type="range"
            min="0"
            max={recording.metadata_json.duration_ms}
            value={position}
            onChange={(e) => {
              if (media.current)
                media.current.currentTime = Number(e.target.value) / 1000;
            }}
          />
        )}
      </div>
      <div className="player-bottom">
        <div className="play-controls">
          <button
            className="icon-button"
            aria-label={t("back")}
            onClick={() => seek(-5)}
          >
            <SkipBack size={17} />
          </button>
          <button
            className="play-button"
            aria-label={playing ? t("pause") : t("play")}
            onClick={() => {
              if (media.current)
                playing
                  ? media.current.pause()
                  : void media.current.play().catch(() => {});
            }}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button
            className="icon-button"
            aria-label={t("forward")}
            onClick={() => seek(5)}
          >
            <SkipForward size={17} />
          </button>
          <span className="timecode">
            <b>{time(position, true)}</b>
            <span>/</span>
            {time(recording.metadata_json.duration_ms, true)}
          </span>
        </div>
        <div className="audio-options">
          <Volume2 size={15} />
          <input
            type="range"
            aria-label={t("volume")}
            min="0"
            max="1"
            step="0.05"
            defaultValue="1"
            onChange={(e) => {
              if (media.current) media.current.volume = Number(e.target.value);
            }}
          />
          <select
            aria-label={t("speed")}
            value={speed}
            onChange={(e) => {
              setSpeed(e.target.value);
              if (media.current)
                media.current.playbackRate = Number(e.target.value);
            }}
          >
            {["0.75", "1", "1.25", "1.5", "2"].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}
