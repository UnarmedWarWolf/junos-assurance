"""Automation command catalog.

Sources: the team's "Commands Notebook" (Junos - QFX/MX) and the Juniper
"CLI User Guide for Junos OS" (operational-mode monitoring commands).

Template syntax
    {name}        -> replaced by the parameter value
    [[ ... ]]     -> optional segment; dropped when any parameter inside is blank
                     (this is what "Run as is" / bypass uses)

To add your own commands, append a Command(...) to CATALOG below.
"""
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Param:
    name: str
    label: str
    description: str
    example: str = ""
    optional: bool = True


@dataclass
class Command:
    category: str
    name: str
    template: str
    description: str
    params: List[Param] = field(default_factory=list)

    @property
    def needs_input(self) -> bool:
        return bool(self.params)

    @property
    def can_bypass(self) -> bool:
        return all(p.optional for p in self.params)


IFACE = Param("interface", "Interface name",
              "Physical interface to query, e.g. xe-0/0/0, ge-0/0/13 or et-0/0/48. "
              "FPC 0 = 0/0/## interfaces, FPC 1 = 1/0/## interfaces.",
              "xe-0/0/0")
IFACE_REQ = Param(IFACE.name, IFACE.label, IFACE.description, IFACE.example, optional=False)

OPTICS_FILTERED = ('show interfaces diagnostics optics | match "xe| output power|laser receiver power| " '
                   '| except " alarm " | except "threshold" | except "warning|voltage|temperature|bias"')

CATALOG: List[Command] = [
    # ---------------------------------------------------------------- Basic
    Command("Basic", "Interface descriptions", "show interfaces descriptions | no-more",
            "Lists every interface that has a description configured, with its admin and link state. "
            "Good first command to orient yourself on a new switch."),
    Command("Basic", "Interfaces – terse", "show interfaces terse[[ {interface}]] | no-more",
            "One line per interface/unit showing Admin and Link state plus protocol and address. "
            "Leave the interface blank to list everything.", [IFACE]),
    Command("Basic", "Software version", "show version | no-more",
            "Hostname, model and the Junos software release running on the device."),
    Command("Basic", "Logged-in users", "show system users | no-more",
            "Who is currently logged in to the device, from where, and how long they have been idle."),
    Command("Basic", "System uptime", "show system uptime | no-more",
            "Current time, when the system booted, last configuration commit and load averages."),

    # ---------------------------------------------------------------- Flaps
    Command("Flaps", "Flap summary – FPC 0 ports", 'show interfaces *e-0/0/* | match "physical|flap" | no-more',
            "For every ge-/xe- port on FPC 0 shows the physical state line and the 'Last flapped' "
            "timestamp. Use this to spot ports that have bounced recently."),
    Command("Flaps", "Flap summary – choose FPC", 'show interfaces *e-{fpc}/0/* | match "physical|flap" | no-more',
            "Same as the FPC 0 flap summary but for the FPC you choose (FPC 1 = 1/0/## interfaces).",
            [Param("fpc", "FPC slot", "FPC number: 0 for 0/0/## ports, 1 for 1/0/## ports.", "1", optional=False)]),
    Command("Flaps", "Up/down flap script (all)", 'op up-down.py flap all | match "up down"',
            "Runs the up-down.py op script installed on the box and lists every interface that has "
            "recorded up/down transitions."),
    Command("Flaps", "Flap history from logs", "show log messages | match {interface} | last 30 | no-more",
            "Historical syslog entries for one interface (last 30 lines) – shows the up/down "
            "flaps with timestamps.", [IFACE_REQ]),
    Command("Flaps", "Interface extensive", "show interfaces {interface} extensive | no-more",
            "Full detail for one interface: flap time, error counters (CRC, framing), "
            "traffic statistics and MAC/PCS statistics.", [IFACE_REQ]),

    # -------------------------------------------------------- Optics Diagnostics
    Command("Optics Diagnostics", "Optics power summary (filtered)", OPTICS_FILTERED,
            "Transmit (output) and receive power for every xe- optic, with alarm, threshold, warning, "
            "voltage, temperature and bias lines removed so only the light levels remain."),
    Command("Optics Diagnostics", "Optics power – all ports",
            'show interfaces diagnostics optics | match "physical|output power |receiver power " | no-more',
            "Physical interface name followed by laser output (Tx) and receiver (Rx) power for every optic."),
    Command("Optics Diagnostics", "Optics diagnostics – one port",
            "show interfaces diagnostics optics[[ {interface}]] | no-more",
            "Complete DOM readout for one port: Tx/Rx power, bias current, temperature, voltage and every "
            "alarm/warning threshold. Leave blank to show all ports.", [IFACE]),

    # ------------------------------------------------------------ Chassis
    Command("Chassis / Hardware", "Slotted SFPs (PIC)", "show chassis pic fpc-slot {fpc} pic-slot {pic} | no-more",
            "Lists the optics installed in a PIC with part numbers and types. FPC 0 = 0/0/## interfaces, "
            "FPC 1 = 1/0/##. PIC slot is always 0 on QFX but varies on MX960.",
            [Param("fpc", "FPC slot", "FPC number (0 for 0/0/## ports, 1 for 1/0/## ports).", "0", optional=False),
             Param("pic", "PIC slot", "PIC number – always 0 on QFX, varies on MX960.", "0", optional=False)]),
    Command("Chassis / Hardware", "Hardware inventory", "show chassis hardware | no-more",
            "Hardware inventory: chassis, FPCs, PICs and transceivers with serial and part numbers."),
    Command("Chassis / Hardware", "Chassis alarms", "show chassis alarms | no-more",
            "Active chassis alarm status (power, fans, temperature, hardware faults)."),
    Command("Chassis / Hardware", "Environment", "show chassis environment | no-more",
            "Temperatures, fan and power-supply status for the router or switch."),
    Command("Chassis / Hardware", "Craft interface", "show chassis craft-interface | no-more",
            "Information currently on the craft display / front panel LEDs."),
    Command("Chassis / Hardware", "Routing engine", "show chassis routing-engine | no-more",
            "Routing Engine status: CPU and memory utilisation, uptime and temperature."),
    Command("Chassis / Hardware", "System alarms", "show system alarms | no-more",
            "Software / system alarms (e.g. rescue configuration not set, licence warnings)."),
    Command("Chassis / Hardware", "System storage", "show system storage | no-more",
            "Free and used space on the device file systems."),

    # -------------------------------------------------------- Layer 2 / Routing
    Command("Layer 2 / Routing", "LLDP neighbors", "show lldp neighbors | no-more",
            "Directly connected neighbours learned by LLDP – local port, neighbour name and port."),
    Command("Layer 2 / Routing", "Ethernet switching table", "show ethernet-switching table[[ interface {interface}]] | no-more",
            "MAC address table. Optionally limit it to one interface.", [IFACE]),
    Command("Layer 2 / Routing", "Route summary", "show route summary | no-more",
            "Number of routes in each routing table, broken down by protocol."),
    Command("Layer 2 / Routing", "Route lookup", "show route {prefix} | no-more",
            "Active route entries for one destination prefix or address.",
            [Param("prefix", "Prefix / address", "IP address or prefix to look up.", "10.0.0.0/8", optional=False)]),
    Command("Layer 2 / Routing", "Forwarding table summary", "show route forwarding-table summary | no-more",
            "Summary of the entries in the kernel forwarding table."),
    Command("Layer 2 / Routing", "OSPF neighbors", "show ospf neighbor | no-more",
            "OSPF adjacency state for each neighbour."),
    Command("Layer 2 / Routing", "BGP summary", "show bgp summary | no-more",
            "BGP peers with state, uptime and received/accepted prefix counts."),

    # ---------------------------------------------------------------- Logs
    Command("Logs", "Last 100 log messages", "show log messages | last 100 | no-more",
            "The most recent 100 entries from the main syslog file."),
    Command("Logs", "Search log messages", 'show log messages | match "{pattern}" | last 50 | no-more',
            "Search the syslog for a word or regex (e.g. an interface, 'SNMP_TRAP_LINK_DOWN', 'LACP').",
            [Param("pattern", "Search text", "Text or regular expression to match in the log.", "LINK_DOWN", optional=False)]),
    Command("Logs", "Commit history", "show system commit | no-more",
            "Recent configuration commits: who committed, when and how."),

    # ---------------------------------------------------------- Connectivity
    Command("Connectivity", "Ping host", "ping {host} count 5 | no-more",
            "Checks reachability of a remote system (5 packets).",
            [Param("host", "Host / IP", "Address or hostname to ping.", "8.8.8.8", optional=False)]),
    Command("Connectivity", "Traceroute", "traceroute {host} | no-more",
            "Shows the hop-by-hop path to a remote system.",
            [Param("host", "Host / IP", "Address or hostname to trace to.", "8.8.8.8", optional=False)]),
    Command("Connectivity", "Wait / spacer (60 s)", "ping 127.0.0.1 count 2 interval 60 | no-more",
            "Pauses about 60 seconds. Useful to space out commands since Junos has no CLI 'wait' command."),
]


def categories():
    seen = []
    for c in CATALOG:
        if c.category not in seen:
            seen.append(c.category)
    return seen


_OPT_RE = re.compile(r"\[\[(.*?)\]\]")
_VAR_RE = re.compile(r"\{(\w+)\}")


def render(cmd: Command, values: dict) -> str:
    """Build the final command line. Raises ValueError if a required value is missing."""
    values = {k: (v or "").strip() for k, v in (values or {}).items()}

    def opt(m):
        seg = m.group(1)
        names = _VAR_RE.findall(seg)
        if names and all(values.get(n) for n in names):
            return _VAR_RE.sub(lambda mm: values[mm.group(1)], seg)
        return ""

    text = _OPT_RE.sub(opt, cmd.template)
    missing = [n for n in _VAR_RE.findall(text) if not values.get(n)]
    if missing:
        labels = [p.label for p in cmd.params if p.name in missing] or missing
        raise ValueError("Required: " + ", ".join(labels))
    text = _VAR_RE.sub(lambda m: values[m.group(1)], text)
    return text.strip()
