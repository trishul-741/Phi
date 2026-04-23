function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function scrubPasswordValues(html: string): string {
  return html.replace(
    /(<input[^>]+type=["']?password["']?[^>]*value=["'])[^"']*(["'][^>]*>)/gi,
    "$1[redacted]$2",
  );
}

export function extractVisibleText(maxChars: number): string {
  const text = document.body?.innerText ?? document.documentElement.innerText ?? "";
  return collapseWhitespace(text).slice(0, maxChars);
}

export function extractRawHtml(maxChars: number): string {
  const html = document.documentElement.outerHTML ?? "";
  return scrubPasswordValues(html).slice(0, maxChars);
}
