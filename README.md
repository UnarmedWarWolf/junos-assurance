# Junos Assurance

A desktop GUI (Windows and macOS) for reaching Junos switches through a jump host, styled after Cisco DNA Center's
Assurance view. Built for ISP engineers who are new to the Junos CLI.

## Run it

### Windows
* **With Python installed:** double-click `run_windows.bat`. It finds a working Python 3.9 or newer.
  The first run installs the required packages for your user account; after that the app opens
  straight away. If something goes wrong, run `run_windows.bat console` from a Command Prompt to keep
  the error messages visible. If Python is missing, install it from python.org and tick
  **"Add python.exe to PATH"** during setup.
* **Without Python on each PC:** run `build_windows_exe.bat` once on any Windows machine that has
  Python. It produces `dist\JunosAssurance\JunosAssurance.exe`. Zip the `dist\JunosAssurance`
  folder and share it; engineers just unzip it and run the `.exe`.

Settings are stored in `%APPDATA%\JunosAssurance\`. Passwords go into Windows Credential Manager
(entries named *JunosAssurance*). Unexpected errors are written to `error.log` in the same folder.

### macOS
Double-click `run_mac.command`. If macOS blocks it, right-click and choose **Open**. Settings are
stored in `~/.junos_assurance/` and passwords in the Keychain.

### Manual
```
py -3 -m pip install --user -r requirements.txt
py -3 main.py
```
Requires Python 3.9 or newer.

## Connecting through the jump host

The jump host (bastion) is in its own domain. The app connects the same way as `ssh -J`:

1. It logs in to the **jump host** with your **P-Number** and **password + VIP code**.
2. It opens a tunnel through the jump host to the switch on port 22. The jump host looks up the switch
   name, so names in the jump host's domain work.
3. It logs in to the **switch** inside that tunnel. By default it uses the same P-Number and password.
   If the switches use a different account, tick **Switch uses a different login** and enter the
   switch username and password. If the switch rejects the login, the VIP box opens so you can retry
   with password + a new code.
4. When the Junos prompt (`P1234567@switch>`) appears, the dashboard starts filling in.

Steps:
1. Enter the **Jump host** (`host` or `host:port`), **Username (P-Number)**, **Password** and the
   **Switch hostname**. These are remembered, along with your recent switch names. If
   **Remember passwords** is ticked, passwords are saved in the system keychain, never in a file.
2. Click **Connect**, or press Enter in the hostname box. Type your VIP code in the small box and press
   Enter.

**⚙ Settings → Connection**
| Setting | Use |
|---|---|
| Connection method | **Jump host** (default) tunnels straight to the switch. **Bastion shell** logs in to a shell on the bastion and types `ssh <switch>` for you. (Automatic falls back to this when the jump host blocks tunnels.) |
| Jump host login name | `{username}` by default. Use `DOMAIN\{username}` or `{username}@jump.example.com` if the jump host domain needs it. |
| Switch domain suffix | Added to short switch names. For example, `net.example.com` turns `qfx-01` into `qfx-01.net.example.com`. Leave it blank if the jump host resolves short names. |
| Switch login | *Password only* (you're asked for a VIP code if it's rejected) or *Password + a new VIP code* every time. |

## Screen layout

* **KPI tiles:** ports up, admin-up/link-down count, recent flaps, optics health.
* **Flap List:** ports that flapped within the window (24 h by default). Ports that flapped in the last
  hour are marked *Critical*. "Seen" counts flaps detected while the app was open.
* **Admin Up · Link Down:** enabled ports with no link, with their descriptions.
* **Port Health (Optics):** Rx/Tx light levels checked against each optic's own alarm/warning
  thresholds (with fallback thresholds in Settings). *No Light* means Rx is about −40 dBm.
* These refresh in the background every 120 s (configurable), or when you click **Refresh now**.
  Background commands run in a queue with your own commands, so the CLI output never gets mixed up.
* **Double-click** any dashboard row to put `show interfaces <port> extensive` in the CLI.
* **Export…** saves all dashboard tables to one Excel workbook.

## CLI

Always visible. Type any command and press Enter. Use ↑/↓ for history, end a line with `?` for Junos
help, and use **Ctrl+C** to stop a running command. **Save CLI ▾** saves the session as a Word
(.docx) or Excel (.xlsx) file, keeping the colours.

Colours: **red** = down/failed/error · **amber** = warning · **green** = up/enabled/OK ·
**purple** = interface names (xe-0/0/0, ge-1/0/13, et-0/0/48, ae0…).

## Automation Commands

The **Select a command** drop-down groups commands by category: Basic, Flaps, Optics Diagnostics,
Chassis / Hardware, Layer 2 / Routing, Logs, Connectivity. Hover over a command to see what it does.
Commands marked `…` need a value, such as an interface name. A pop-up explains the value and offers
interface autocomplete. If the value is optional, you can choose **Run as is** to skip it.
Output appears in the **Automation Output** panel and in the CLI. Use **Save to Excel…** (or the last
item in the drop-down) to save it. The Excel file has a *Table* sheet split into columns and a *Raw*
sheet.

To add commands, edit `CATALOG` in `app/commands.py`. Use `{name}` for a required value and
`[[ ... {name}]]` for an optional part.

## Files

```
main.py              start-up
run_windows.bat      Windows launcher
build_windows_exe.bat  build a stand-alone .exe
run_mac.command      macOS launcher
app/main_window.py   layout and behaviour
app/ssh_session.py   jump-host tunnel / bastion shell, command queue
app/commands.py      automation command catalog
app/parsers.py       parsing for terse / descriptions / flaps / optics
app/exporters.py     Word and Excel export
app/theme.py         colours, highlighting rules, stylesheet
app/widgets.py       tiles, tables, CLI console, dialogs
app/config.py        saved settings and keychain password
```
