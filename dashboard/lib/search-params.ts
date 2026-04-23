export type PageSearchParams = Record<string, string | string[] | undefined>;

export function pickSearchParam(
  value: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}
