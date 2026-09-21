# NBClone for iOS — native app (build on a Mac)

A true native iPhone/iPad app (SwiftUI, iOS 17+): notebooks, grounded chat
with citation chips, sources, all 9 Studio tools, notes, audio/video playback
with speed control, share sheets, and team login. It talks to your existing
server over your network — no backend changes needed.

> The `.xcodeproj` was generated on Linux and **has not been compiled** —
> first build happens on your Mac (steps below). Please report any error;
> the project generator is `ios/gen_project.py` (re-run after adding files).

## What you need
- A Mac with **Xcode 26 or later** (free from the Mac App Store)
- A free Apple ID (run on your own iPhone) or a paid Developer account
  (TestFlight / App Store)
- This repo's server running and reachable (see `docs/INSTALL.md`)

## Run it (5 minutes)
1. On the Mac: `git clone` this repo (or copy the folder), then open
   `ios/NotebookLMClone.xcodeproj` in Xcode.
2. Select the **NotebookLMClone** target → **Signing & Capabilities** →
   pick your **Team**, and change the **Bundle Identifier** to something
   unique (e.g. `com.yourname.nbclone`).
3. Pick a simulator (e.g. iPhone 17) and press **▶ Run**.
   - **Simulator:** the server URL is `http://127.0.0.1:8000` (simulator
     shares your Mac's localhost — start the server on the Mac first).
   - **Your iPhone:** connect iPhone + Mac to the same Wi-Fi, start the
     server on the Mac, and in the app's Settings enter
     `http://<mac-IP>:8000` (System Settings → Wi-Fi → Details for the IP).
4. Trust the developer on the iPhone if asked
   (Settings → General → VPN & Device Management).

## Put it on your phone properly
- **Free (7-day refresh):** Xcode → Window → Devices → install the build
  directly; re-install weekly, or use AltStore/SideStore to auto-refresh.
- **TestFlight (90 days, no Mac needed after upload):** needs the paid
  Apple Developer Program ($99/yr): Product → Archive → Distribute →
  App Store Connect → TestFlight → invite yourself.
- **App Store:** same Archive flow, then submit for review (needs an
  App Store Connect record, screenshots, and a privacy policy URL —
  ours is easy: “data stays on your own server”).

## Feature map (v1)
Chat + citations + suggested prompts + save-to-note · Sources (paste, URL,
YouTube, file import, Drive) with enable toggles + preview · Studio: report,
flashcards, quiz (interactive), mind map, data table (+CSV share, Sheets
push), audio (chapters, 0.75–2× speed), video, slides (+PPTX share),
infographic (+PNG share) · Notes + PDF export · Notebook share links ·
Team login/logout · Quotas display · Authed downloads (media plays offline
once fetched).

Deliberately v1-cut (PRs welcome): notebook members management, team
analytics screen, background downloads, push notifications, iCloud sync,
Apple TV/watch apps.

## Notes for developers
- Swift 5 mode, iOS 17 deployment target, no third-party dependencies.
- The app uses `NSAllowsLocalNetworking`, so plain-`http://` works for
  LAN IPs (no HTTPS setup needed at home). For use outside your home
  network, put the server behind HTTPS (Tailscale/Caddy) and use the
  `https://` URL instead.
- Login sessions are cookies; quit-and-relaunch needs a fresh login
  when `AUTH_REQUIRED=1` (v1 limitation).
- Re-generate the Xcode project after adding/removing Swift files:
  `python3 ios/gen_project.py`.
