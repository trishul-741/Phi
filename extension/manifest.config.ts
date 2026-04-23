import { defineManifest } from "@crxjs/vite-plugin";

export default defineManifest({
  manifest_version: 3,
  name: "PhishGuard",
  version: "2.0.0",
  description: "Two-stage non-visual phishing protection for everyday browsing.",
  icons: {
    16: "icons/icon-16.png",
    32: "icons/icon-32.png",
    48: "icons/icon-48.png",
    128: "icons/icon-128.png",
  },
  permissions: [
    "activeTab",
    "storage",
    "tabs",
    "scripting",
  ],
  host_permissions: [
    "http://127.0.0.1:8000/*",
    "http://localhost:8000/*",
    "http://localhost:3000/*",
    "http://127.0.0.1:3000/*",
    "http://*/*",
    "https://*/*",
  ],
  action: {
    default_popup: "popup.html",
    default_title: "PhishGuard",
    default_icon: {
      16: "icons/icon-16.png",
      32: "icons/icon-32.png",
      48: "icons/icon-48.png",
      128: "icons/icon-128.png",
    },
  },
  options_page: "options.html",
  background: {
    service_worker: "src/background/index.ts",
    type: "module",
  },
  content_scripts: [
    {
      matches: ["http://*/*", "https://*/*"],
      js: ["src/content/index.tsx"],
      run_at: "document_idle",
    },
  ],
});
