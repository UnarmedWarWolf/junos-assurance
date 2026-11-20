"""Parsers for the background monitoring commands (pure Python, no Qt)."""
import re

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>]")
PHYSICAL_PREFIXES = ("ge-", "xe-", "et-", "fe-", "mge-")

# Background commands used by the dashboard (editable in Settings)
MONITOR_COMMANDS = {
    "terse": "show interfaces terse | no-more",
    "descriptions": "show interfaces descriptions | no-more",
    "flaps": 'show interfaces | match "Physical interface|Last flapped" | no-more',
    "optics": 'show interfaces diagnostics optics | match "Physical interface|Lane|power|threshold" | no-more',
}


def clean_text(text: str) -> str:
    """Strip ANSI escapes, bells, backspace edits and carriage returns."""
    text = ANSI_RE.sub("", text)
    text = text.replace("\x07", "").replace("\x00", "")
    while "\x08" in text:
        new = re.sub("[^\x08\n]\x08", "", text, count=1)
        if new == text:
            text = text.replace("\x08", "")
            break
        text = new
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\r+\n", "\n", text)
    text = re.sub(r"\r", "", text)
    return text


def is_physical(name: str) -> bool:
    return name.lower().startswith(PHYSICAL_PREFIXES) and "." not in name


# ---------------------------------------------------------------- terse
_TERSE_RE = re.compile(r"^(\S+)\s+(up|down)\s+(up|down)\b", re.I)


def parse_terse(text: str) -> dict:
    """{iface: {'admin': 'up', 'link': 'down'}} for physical ports."""
    out = {}
    for line in text.splitlines():
        m = _TERSE_RE.match(line.strip())
        if m and is_physical(m.group(1)):
            out[m.group(1)] = {"admin": m.group(2).lower(), "link": m.group(3).lower()}
    return out


# ---------------------------------------------------------- descriptions
_DESC_RE = re.compile(r"^(\S+)\s+(up|down)\s+(up|down)\s+(.*)$", re.I)


def parse_descriptions(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = _DESC_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(4).strip()
    return out


# ---------------------------------------------------------------- flaps
_PHYS_RE = re.compile(r"Physical interface:\s*([^,\s]+),\s*([^,]+),\s*Physical link is (\w+)", re.I)
_FLAP_RE = re.compile(r"Last flapped\s*:\s*(.+?)\s*$", re.I)


def parse_ago(text: str):
    """'(1w2d 03:04 ago)' / '(2d 03:15 ago)' / '(00:13:16 ago)' -> seconds or None."""
    m = re.search(r"\(([^)]*)ago\)", text)
    if not m:
        return None
    s = m.group(1)
    total = 0
    for unit, mult in (("y", 365 * 86400), ("w", 7 * 86400), ("d", 86400)):
        mm = re.search(r"(\d+)" + unit, s)
        if mm:
            total += int(mm.group(1)) * mult
    t = re.search(r"(\d+):(\d+)(?::(\d+))?", s)
    if t:
        h, mi, se = int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)
        total += h * 3600 + mi * 60 + se
    return total


def fmt_age(seconds) -> str:
    if seconds is None:
        return "Never"
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h ago"
    if h:
        return f"{h}h {m}m ago"
    return f"{m}m ago"


def parse_flaps(text: str) -> list:
    rows, cur = [], None
    for line in text.splitlines():
        pm = _PHYS_RE.search(line)
        if pm:
            cur = {"interface": pm.group(1), "admin": pm.group(2).strip(),
                   "link": pm.group(3), "last_flapped": "Never", "age": None}
            rows.append(cur)
            continue
        fm = _FLAP_RE.search(line)
        if fm and cur is not None:
            val = fm.group(1)
            cur["age"] = parse_ago(val)
            cur["last_flapped"] = re.sub(r"\s*\(.*\)\s*$", "", val).strip() or val
    return [r for r in rows if is_physical(r["interface"])]


# ---------------------------------------------------------------- optics
_DBM_RE = re.compile(r"(-?\s*(?:\d+(?:\.\d+)?|inf))\s*dBm", re.I)


def _dbm(value: str):
    m = _DBM_RE.search(value)
    if not m:
        return None
    v = m.group(1).replace(" ", "").lower()
    if "inf" in v:
        return -40.0
    try:
        return float(v)
    except ValueError:
        return None


def parse_optics(text: str) -> dict:
    """{iface: {'tx': [dBm..], 'rx': [dBm..], 'thr': {...}, 'alarms': [..]}}"""
    data, cur = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"Physical interface:\s*(\S+)", line, re.I)
        if m:
            cur = data.setdefault(m.group(1).rstrip(","), {"tx": [], "rx": [], "thr": {}, "alarms": []})
            continue
        if cur is None or ":" not in line:
            continue
        key, _, val = line.partition(":")
        k = key.strip().lower()
        v = val.strip()
        if "threshold" in k:
            d = _dbm(v)
            if d is None:
                continue
            side = "rx" if ("rx" in k or "receiver" in k) else ("tx" if ("output" in k or "tx" in k) else None)
            if side:
                lvl = ("high" if "high" in k else "low") + "_" + ("alarm" if "alarm" in k else "warn")
                cur["thr"][f"{side}_{lvl}"] = d
            continue
        if ("alarm" in k or "warning" in k) and v.lower() in ("on", "off"):
            if v.lower() == "on" and "power" in k:
                cur["alarms"].append(("alarm" if "alarm" in k else "warning", key.strip()))
            continue
        d = _dbm(v)
        if d is None:
            continue
        if "output power" in k or "tx power" in k:
            cur["tx"].append(d)
        elif "receiver power" in k or "optical power" in k or "rx power" in k:
            cur["rx"].append(d)
    return data


def evaluate_optics(entry: dict, warn_default=-12.0, alarm_default=-15.0):
    """Return (health, worst_rx, reason). Health: OK / Warning / Critical / No Light / N/A."""
    rx = entry.get("rx") or []
    if not rx:
        return "N/A", None, "No receive reading (DAC / no optic)"
    worst = min(rx)
    thr = entry.get("thr", {})
    low_alarm = thr.get("rx_low_alarm", alarm_default)
    low_warn = thr.get("rx_low_warn", warn_default)
    high_alarm = thr.get("rx_high_alarm")
    high_warn = thr.get("rx_high_warn")
    alarms = entry.get("alarms", [])
    if worst <= -30:
        return "No Light", worst, "Receiver sees no light"
    if worst < low_alarm:
        return "Critical", worst, f"Rx {worst:.2f} dBm below alarm threshold {low_alarm:.2f}"
    if high_alarm is not None and max(rx) > high_alarm:
        return "Critical", max(rx), f"Rx above high alarm threshold {high_alarm:.2f}"
    if any(a[0] == "alarm" for a in alarms):
        return "Critical", worst, "; ".join(a[1] for a in alarms)
    if worst < low_warn:
        return "Warning", worst, f"Rx {worst:.2f} dBm below warning threshold {low_warn:.2f}"
    if high_warn is not None and max(rx) > high_warn:
        return "Warning", max(rx), f"Rx above high warning threshold {high_warn:.2f}"
    if alarms:
        return "Warning", worst, "; ".join(a[1] for a in alarms)
    return "OK", worst, "Within thresholds"


HEALTH_ORDER = {"No Light": 0, "Critical": 1, "Warning": 2, "OK": 3, "N/A": 4}

# Junos prompt like  user@switch>  or  user@switch#
PROMPT_RE = re.compile(r"(?:^|\n)([\w.\-]+)@([\w.\-]+)([>#%]) ?$")


def find_prompt(text: str):
    """Return (user, host, mode_char) if text ends with a Junos prompt."""
    m = PROMPT_RE.search(text[-300:])
    return (m.group(1), m.group(2), m.group(3)) if m else None


def strip_command_output(buffer: str, command: str) -> str:
    """Remove echoed command line, trailing prompt and {master:0} lines from captured output."""
    lines = buffer.split("\n")
    if lines and command.strip()[:20] and command.strip()[:20] in lines[0]:
        lines = lines[1:]
    lines = [ln for ln in lines if not re.fullmatch(r"\s*\{[\w:]+\}\s*", ln)]
    while lines and (not lines[-1].strip() or PROMPT_RE.search("\n" + lines[-1])):
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


# ------------------------------------------------------- interface detail
def parse_extensive(text: str) -> dict:
    """Parse `show interfaces <if> extensive` (optionally | match-filtered) into key counters."""
    d, section = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        m = _PHYS_RE.search(line)
        if m:
            d["admin"], d["link"] = m.group(2).strip(), m.group(3)
            continue
        if line.startswith("Description:"):
            d.setdefault("description", line.split(":", 1)[1].strip())
            continue
        m = re.search(r"\bSpeed:\s*([^,\s]+)", line)
        if m and "speed" not in d:
            d["speed"] = m.group(1)
        m = re.search(r"\bMTU:\s*(\d+)", line)
        if m and "mtu" not in d:
            d["mtu"] = int(m.group(1))
        m = re.match(r"(Input|Output) rate\s*:\s*(\d+)\s*bps\s*\((\d+)\s*pps\)", line)
        if m:
            p = "in" if m.group(1) == "Input" else "out"
            d.setdefault(f"{p}_bps", int(m.group(2)))
            d.setdefault(f"{p}_pps", int(m.group(3)))
            continue
        m = re.match(r"(Input|Output) errors\s*:\s*(.*)$", line)
        if m:
            section = "in" if m.group(1) == "Input" else "out"
            if m.group(2).strip().isdigit():
                d.setdefault(f"{section}_errors", int(m.group(2)))
            continue
        m = re.match(r"CRC/Align errors\s+(\d+)\s+(\d+)", line)
        if m:
            d["crc_rx"], d["crc_tx"] = int(m.group(1)), int(m.group(2))
            continue
        fm = _FLAP_RE.search(line)
        if fm:
            d.setdefault("last_flapped", fm.group(1))
            continue
        if section and re.match(r"(Errors|Carrier transitions):", line):
            for k, v in re.findall(r"([A-Za-z][A-Za-z /-]*?):\s*(\d+)", line):
                d.setdefault(f"{section}_{k.strip().lower()}", int(v))
    return d


def parse_lldp(text: str, iface: str = "") -> dict:
    """Parse `show lldp neighbors interface <if>` (detail) or the summary table."""
    d = {}
    wanted = (("system name", "system"), ("port id", "port_id"), ("port description", "port_desc"),
              ("chassis id", "chassis"))
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        for want, key in wanted:
            if k.startswith(want) and v and key not in d:
                d[key] = v
    if not d and iface:
        for line in text.splitlines():
            if line.strip().startswith(iface):
                cols = re.split(r"\s{2,}", line.strip())
                if len(cols) >= 5:
                    d = {"chassis": cols[2], "port_id": cols[3], "system": cols[4]}
                elif len(cols) == 4:
                    d = {"chassis": cols[1], "port_id": cols[2], "system": cols[3]}
    return d


def fmt_bps(bps) -> str:
    if bps is None:
        return "–"
    for unit, div in (("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        if bps >= div:
            return f"{bps / div:.2f} {unit}"
    return f"{int(bps)} bps"


_PORT_RE = re.compile(r"^([a-z]+)-(\d+)/(\d+)/(\d+)(?::(\d+))?$", re.I)


def split_port(name: str):
    """'xe-0/0/12' -> ('xe', 0, 0, 12, None); None if not a physical port name."""
    m = _PORT_RE.match(name)
    if not m:
        return None
    return (m.group(1).lower(), int(m.group(2)), int(m.group(3)), int(m.group(4)),
            int(m.group(5)) if m.group(5) is not None else None)
