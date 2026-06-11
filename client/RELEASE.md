# JCC S17 AI Assistant Release

## Build Installer

Install dependencies first:

```powershell
cd D:\JCC\jcc-s17-ai\client
npm install
```

Build the React app and generate a Windows x64 NSIS installer:

```powershell
npm run dist:win
```

## Output

The installer is generated in:

```text
D:\JCC\jcc-s17-ai\client\dist-release
```

The expected artifact is a Windows x64 installer for:

```text
JCC S17 AI Assistant
```

## Install

Open the generated `.exe` installer in `dist-release`, follow the installer prompts, and launch `JCC S17 AI Assistant` from the desktop shortcut or Start Menu.

## Notes

The app only performs screenshot recognition and recommendation display. It does not operate the game, does not inject into the game process, and does not read game memory.

The default backend address is:

```text
http://127.0.0.1:8000
```

Users can change the backend address in the Settings page.
