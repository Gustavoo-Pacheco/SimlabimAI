import slugRules from "@shared/slugs.json";
import stylesJson from "@shared/styles.json";

export const SLUG_RE = new RegExp(slugRules.pattern);
export const SLUG_MIN = slugRules.minLength;
export const SLUG_MAX = slugRules.maxLength;

export class BadInput extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BadInput";
  }
}

export function isSlug(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= SLUG_MIN &&
    value.length <= SLUG_MAX &&
    SLUG_RE.test(value)
  );
}

export function assertSlug(value: unknown, label: string): string {
  if (!isSlug(value)) {
    throw new BadInput(
      `${label} must match ${SLUG_RE} (length ${SLUG_MIN}-${SLUG_MAX})`,
    );
  }
  return value;
}

/**
 * Turns user-typed free text into a slug matching SLUG_RE.
 * - lowercase
 * - strips diacritics (á → a, ç → c)
 * - replaces non-alphanumeric runs with single hyphens
 * - trims leading/trailing hyphens
 * - truncates to SLUG_MAX
 *
 * Returns "" when the input has no slug-able characters.
 */
export function slugify(input: string): string {
  return input
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, SLUG_MAX);
}

// TypeScript needs a literal tuple to preserve narrow type inference for `Style`.
// `shared/styles.json` is the cross-language mirror (read by Python in dataset/ and model/).
// The drift guard below asserts they match at module load — change either, change both.
export const STYLES = ["cantar", "cantarolar", "assobiar"] as const;
export type Style = (typeof STYLES)[number];

if (
  stylesJson.values.length !== STYLES.length ||
  stylesJson.values.some((v, i) => v !== STYLES[i])
) {
  throw new Error(
    "shared/styles.json drift — update STYLES in collection/lib/slugs.ts (or vice versa)",
  );
}

export function isStyle(value: unknown): value is Style {
  return typeof value === "string" && (STYLES as readonly string[]).includes(value);
}

export function assertStyle(value: unknown): Style {
  if (!isStyle(value)) {
    throw new BadInput(`style must be one of ${STYLES.join(", ")}`);
  }
  return value;
}
