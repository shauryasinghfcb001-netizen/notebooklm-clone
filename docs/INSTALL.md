# Install on every system — NotebookLM Clone

One app, every OS. **Windows / macOS / Linux** run the full server + UI.
**iPhone / iPad / Android** install it as an app icon (PWA) talking to your computer.

> The server must be reachable from the device you use. Phone + PC on the
> same Wi-Fi is the easiest setup. On shared networks, set `AUTH_REQUIRED=1`
> (see README → Teams) so a login is required.

---

## 🪟 Windows
**Option A — double-click (easiest):** install Python 3.11+ from
python.org (tick **“Add python.exe to PATH”**), then double-click
`scripts\start-windows.bat`. The browser opens automatically.

**Option B — installer:** right-click `scripts\install-windows.ps1` →
*Run with PowerShell* (creates a desktop shortcut). Add `-Dense` for
semantic search: `install-windows.ps1 -Dense`.

**Option C — .exe:** on your Windows PC run `scripts\build-windows-exe.bat`,
then `dist\NotebookLM-Clone\NotebookLM-Clone.exe`. (TF-IDF mode; install
`winget install ffmpeg` for audio/video.)

Allow **Python** in the firewall prompt so phones can connect.

## 🍎 macOS
Double-click `scripts/start-macos.command` (needs Python 3.11+:
python.org or `brew install python`). If Gatekeeper blocks it, right-click →
*Open*. Works on Intel + Apple Silicon.

## 🐧 Linux
```bash
./scripts/install-linux.sh          # venv + deps + app-menu entry
./scripts/install-linux.sh --dense  # + semantic search (torch CPU)
./start.sh                          # run (or launch from the app menu)
```
Auto-start on login:
```bash
cp scripts/notebooklm-clone.service ~/.config/systemd/user/
systemctl --user enable --now notebooklm-clone
```
Docker instead: `docker compose up --build` (data persists in `./data`).

## 📱 iPhone / iPad (PWA — no App Store needed)
1. Start the server on your computer (above) and note its Wi-Fi IP
   (Windows: `ipconfig` · macOS/Linux: `ip addr` / `ifconfig`).
2. On iPhone Safari open `http://<computer-IP>:8000`.
3. **Share → Add to Home Screen → Add.** It now launches fullscreen
   like a native app, with its own icon.
4. Tip: keep the computer awake while using it; offline cache needs HTTPS,
   so the icon needs the server reachable (normal for a local-first app).
5. **Native app instead?** Build `ios/` in Xcode on a Mac — full guide in
   `ios/README-iOS.md` (needs Apple ID; TestFlight/App Store optional).

## 🤖 Android (PWA)
Same as iOS in Chrome: open `http://<computer-IP>:8000` → ⋮ menu →
**Install app / Add to Home screen**.

## 🩺 Troubleshooting
| Symptom | Fix |
|---|---|
| `python not found` | Install Python 3.11+ and tick “Add to PATH” (Windows) |
| Port 8000 busy | `PORT=8001 ./start.sh` (or `set PORT=8001` on Windows) |
| Phone can't reach server | Same Wi-Fi? Server bound to `0.0.0.0`? Firewall allows Python/port 8000? |
| Blank audio/video | exe builds need system `ffmpeg` on PATH |
| `.command` won't open | Right-click → Open (Gatekeeper), or `chmod +x scripts/*.command scripts/*.sh` |

Backups: `scripts/backup.sh` → timestamped `backup-*.tar.gz` of DB + files.
Uninstall: delete the folder (and `~/.local/share/applications/notebooklm-clone.desktop` on Linux).
