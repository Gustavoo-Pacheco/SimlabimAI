export interface WavInfo {
  sampleRate: number;
  channels: number;
  bitsPerSample: number;
  dataBytes: number;
  durationSeconds: number;
}

export function parseWavHeader(bytes: Uint8Array): WavInfo {
  if (bytes.length < 44) throw new Error("WAV: file shorter than 44 bytes");

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (offset: number) =>
    String.fromCharCode(
      bytes[offset],
      bytes[offset + 1],
      bytes[offset + 2],
      bytes[offset + 3],
    );

  if (tag(0) !== "RIFF") throw new Error("WAV: missing RIFF tag");
  if (tag(8) !== "WAVE") throw new Error("WAV: missing WAVE tag");

  let offset = 12;
  let fmt: { sampleRate: number; channels: number; bitsPerSample: number } | null =
    null;
  let dataBytes = 0;

  while (offset + 8 <= bytes.length) {
    const chunkId = tag(offset);
    const chunkSize = view.getUint32(offset + 4, true);
    const bodyStart = offset + 8;
    if (chunkId === "fmt ") {
      const channels = view.getUint16(bodyStart + 2, true);
      const sampleRate = view.getUint32(bodyStart + 4, true);
      const bitsPerSample = view.getUint16(bodyStart + 14, true);
      fmt = { channels, sampleRate, bitsPerSample };
    } else if (chunkId === "data") {
      dataBytes = chunkSize;
      break;
    }
    offset = bodyStart + chunkSize + (chunkSize % 2);
  }

  if (!fmt) throw new Error("WAV: no fmt chunk");
  if (!dataBytes) throw new Error("WAV: no data chunk");

  const bytesPerSample = fmt.bitsPerSample / 8;
  const frames = dataBytes / (bytesPerSample * fmt.channels);
  const durationSeconds = frames / fmt.sampleRate;

  return {
    sampleRate: fmt.sampleRate,
    channels: fmt.channels,
    bitsPerSample: fmt.bitsPerSample,
    dataBytes,
    durationSeconds,
  };
}
