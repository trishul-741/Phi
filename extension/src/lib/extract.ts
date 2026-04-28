function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function scrubPasswordValues(html: string): string {
  return html.replace(
    /(<input[^>]+type=["']?password["']?[^>]*value=["'])[^"']*(["'][^>]*>)/gi,
    "$1[redacted]$2",
  );
}

export async function waitForDOMSettled(timeoutMs: number = 3000): Promise<void> {
  return new Promise((resolve) => {
    if (document.readyState === "complete" && (document.body?.innerText.length || 0) > 50) {
      return resolve();
    }
    
    let timer: number;
    const observer = new MutationObserver(() => {
      const isSettled = (document.body?.innerText.length || 0) > 50 || 
                        (document.querySelector('div[id="root"]')?.innerHTML.length || 0) > 50 ||
                        (document.querySelector('div[id="app"]')?.innerHTML.length || 0) > 50;
      if (isSettled) {
        observer.disconnect();
        clearTimeout(timer);
        resolve();
      }
    });
    
    observer.observe(document, { childList: true, subtree: true });
    
    timer = window.setTimeout(() => {
      observer.disconnect();
      resolve();
    }, timeoutMs);
  });
}

export async function extractVisibleText(maxChars: number): Promise<string> {
  await waitForDOMSettled();
  const text = document.body?.innerText ?? document.documentElement.innerText ?? "";
  return collapseWhitespace(text).slice(0, maxChars);
}

export async function extractRawHtml(maxChars: number): Promise<string> {
  await waitForDOMSettled();
  const html = document.documentElement.outerHTML ?? "";
  return scrubPasswordValues(html).slice(0, maxChars);
}
