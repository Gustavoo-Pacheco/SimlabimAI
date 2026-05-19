"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const TARGET_SAMPLE_RATE = 16000;

type State = "idle" | "recording" | "processing" | "ready" | "error";

interface Props {
  onWavReady: (blob: Blob | null) => void;
  disabled?: boolean;
}

function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function buildWav(pcm: Int16Array, sampleRate: number): Blob {
  const bytesPerSample = 2;
  const channels = 1;
  const dataSize = pcm.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // format = PCM
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * bytesPerSample, true); // byte rate
  view.setUint16(32, channels * bytesPerSample, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  new Int16Array(buffer, 44).set(pcm);
  return new Blob([buffer], { type: "audio/wav" });
}

async function blobToWav16k(input: Blob): Promise<Blob> {
  const arrayBuffer = await input.arrayBuffer();
  // AudioContext is needed only to decode the source format (webm/mp4).
  const decodeCtx = new (window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext)();
  let decoded: AudioBuffer;
  try {
    decoded = await decodeCtx.decodeAudioData(arrayBuffer.slice(0));
  } finally {
    decodeCtx.close().catch(() => {});
  }

  // Mono-mix into a single Float32Array at the source sample rate.
  const srcFrames = decoded.length;
  const mono = new Float32Array(srcFrames);
  if (decoded.numberOfChannels === 1) {
    mono.set(decoded.getChannelData(0));
  } else {
    const ch0 = decoded.getChannelData(0);
    const ch1 = decoded.getChannelData(1);
    for (let i = 0; i < srcFrames; i++) mono[i] = (ch0[i] + ch1[i]) * 0.5;
  }

  // Resample to 16 kHz mono via OfflineAudioContext.
  const targetFrames = Math.max(
    1,
    Math.round((srcFrames / decoded.sampleRate) * TARGET_SAMPLE_RATE),
  );
  const offline = new OfflineAudioContext(1, targetFrames, TARGET_SAMPLE_RATE);
  const srcBuffer = offline.createBuffer(1, srcFrames, decoded.sampleRate);
  srcBuffer.copyToChannel(mono, 0);
  const node = offline.createBufferSource();
  node.buffer = srcBuffer;
  node.connect(offline.destination);
  node.start(0);
  const rendered = await offline.startRendering();
  const float = rendered.getChannelData(0);
  const pcm = floatToInt16(float);
  return buildWav(pcm, TARGET_SAMPLE_RATE);
}

export default function Recorder({ onWavReady, disabled }: Props) {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const meterCtxRef = useRef<AudioContext | null>(null);
  const meterRafRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);
  const elapsedRafRef = useRef<number | null>(null);

  const cleanupMeter = useCallback(() => {
    if (meterRafRef.current !== null) {
      cancelAnimationFrame(meterRafRef.current);
      meterRafRef.current = null;
    }
    if (elapsedRafRef.current !== null) {
      cancelAnimationFrame(elapsedRafRef.current);
      elapsedRafRef.current = null;
    }
    if (meterCtxRef.current) {
      meterCtxRef.current.close().catch(() => {});
      meterCtxRef.current = null;
    }
    setLevel(0);
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const reset = useCallback(() => {
    cleanupMeter();
    stopStream();
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setElapsed(0);
    setError(null);
    setState("idle");
    onWavReady(null);
  }, [cleanupMeter, onWavReady, previewUrl, stopStream]);

  useEffect(() => {
    return () => {
      cleanupMeter();
      stopStream();
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async () => {
    setError(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    onWavReady(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const meterCtx = new (window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext)();
      meterCtxRef.current = meterCtx;
      const source = meterCtx.createMediaStreamSource(stream);
      const analyser = meterCtx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);

      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = Math.abs(buf[i] - 128) / 128;
          if (v > peak) peak = v;
        }
        setLevel(peak);
        meterRafRef.current = requestAnimationFrame(tick);
      };
      meterRafRef.current = requestAnimationFrame(tick);

      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        setState("processing");
        cleanupMeter();
        stopStream();
        try {
          const raw = new Blob(chunksRef.current, {
            type: recorder.mimeType || "audio/webm",
          });
          const wav = await blobToWav16k(raw);
          const url = URL.createObjectURL(wav);
          setPreviewUrl(url);
          setState("ready");
          onWavReady(wav);
        } catch (err) {
          console.error(err);
          setError(
            err instanceof Error ? err.message : "Failed to process audio",
          );
          setState("error");
        }
      };

      startedAtRef.current = performance.now();
      const updateElapsed = () => {
        setElapsed((performance.now() - startedAtRef.current) / 1000);
        elapsedRafRef.current = requestAnimationFrame(updateElapsed);
      };
      elapsedRafRef.current = requestAnimationFrame(updateElapsed);

      recorder.start();
      setState("recording");
    } catch (err) {
      console.error(err);
      cleanupMeter();
      stopStream();
      setError(err instanceof Error ? err.message : "Microphone unavailable");
      setState("error");
    }
  };

  const stop = () => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
  };

  const statusLabel =
    state === "idle"
      ? "Pronto"
      : state === "recording"
        ? "Gravando"
        : state === "processing"
          ? "Processando"
          : state === "ready"
            ? "Gravado"
            : "Erro";

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Status row */}
      <div className="flex w-full items-center justify-center gap-3 text-[13px] text-[color:var(--color-ink-muted)]">
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              state === "recording"
                ? "bg-[color:var(--color-pastel-red-ink)] pulse-dot"
                : state === "ready"
                  ? "bg-[color:var(--color-pastel-green-ink)]"
                  : state === "error"
                    ? "bg-[color:var(--color-pastel-red-ink)]"
                    : "bg-[#cfcfcc]"
            }`}
          />
          {statusLabel}
        </span>
        <span aria-hidden className="text-[#cfcfcc]">·</span>
        <span className="tabular-nums">
          {elapsed > 0 ? `${elapsed.toFixed(1)}s` : "0.0s"}
        </span>
      </div>

      {/* Waveform / level meter — fixed height so layout is stable */}
      <div className="relative h-9 w-full overflow-hidden rounded border border-[var(--color-rule)] bg-[#fafaf9]">
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            className="h-[60%] w-full origin-center transition-transform duration-75 ease-out"
            style={{
              background:
                state === "recording"
                  ? "linear-gradient(90deg, transparent, rgba(159,47,45,0.18), transparent)"
                  : "linear-gradient(90deg, transparent, rgba(0,0,0,0.04), transparent)",
              transform: `scaleY(${
                state === "recording" ? 0.3 + level * 1.4 : 0.25
              })`,
            }}
          />
        </div>
        {/* Center axis */}
        <div className="pointer-events-none absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-[var(--color-rule)]" />
      </div>

      {/* Action row */}
      <div className="flex w-full flex-col items-center gap-2">
        {state === "idle" || state === "error" ? (
          <button
            type="button"
            onClick={start}
            disabled={disabled}
            className="inline-flex items-center gap-2 rounded-full bg-[#c8362f] px-5 py-2 text-[14px] font-medium text-white transition-all duration-150 hover:bg-[#a82d27] active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-[#d9a8a6]"
          >
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-full bg-white"
            />
            Gravar
          </button>
        ) : state === "recording" ? (
          <button
            type="button"
            onClick={stop}
            className="inline-flex items-center gap-2 rounded-full border border-[var(--color-rule)] bg-white px-5 py-2 text-[14px] font-medium text-[color:var(--color-ink)] transition-all duration-150 hover:border-[#cfcfcc] active:scale-[0.98]"
          >
            <span
              aria-hidden
              className="inline-block h-2 w-2 bg-[color:var(--color-ink)]"
            />
            Parar
          </button>
        ) : state === "processing" ? (
          <span className="text-[13px] text-[color:var(--color-ink-muted)]">
            Processando áudio…
          </span>
        ) : (
          <>
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-2 rounded-full border border-[var(--color-rule)] bg-white px-5 py-2 text-[14px] font-medium text-[color:var(--color-ink)] transition-all duration-150 hover:border-[#cfcfcc] active:scale-[0.98]"
            >
              Regravar
            </button>
            <span className="text-[12px] text-[color:var(--color-ink-muted)]">
              Ouça antes de enviar
            </span>
          </>
        )}
      </div>

      {previewUrl && (
        <audio
          src={previewUrl}
          controls
          preload="auto"
          className="w-full"
          style={{ height: 40 }}
        />
      )}

      {error && (
        <p className="rounded-md border border-[#f3c8ca] bg-[var(--color-pastel-red-bg)] px-3 py-2 text-[12px] text-[color:var(--color-pastel-red-ink)]">
          {error}
        </p>
      )}
    </div>
  );
}
