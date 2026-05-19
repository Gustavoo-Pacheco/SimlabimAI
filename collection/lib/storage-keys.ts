import storage from "@shared/storage.json";

export const RAW_AUDIO_PREFIX = storage.rawAudioPrefix;
export const FILE_EXTENSION = storage.fileExtension;

export function buildStorageKey(songSlug: string, takeUuid: string): string {
  return storage.keyTemplate
    .replace("{songSlug}", songSlug)
    .replace("{takeUuid}", takeUuid);
}
