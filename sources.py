"""Where the bytes come from.

Puzzles never know which mode is active. They ask a ByteSource for a buffer
or a parsed packet, so the three data modes are just three sources:

    RandomSource  RAW       random bytes
    SynthSource   PROTOCOL  synthesized, valid packets
    PcapSource    LIVE      the player's own .pcap/.pcapng files

The pcap and pcapng readers are deliberately minimal and have no dependencies.
"""
import os
import struct

import packets
from packets import (TCP_ACK, TCP_FIN, TCP_PSH, TCP_RST, TCP_SYN, build_dns_query, build_dns_response,
                     build_http_request, build_http_response, frame_tcp, frame_udp, parse)


class ByteSource:
    mode = "?"
    has_packets = False

    def buffer(self, n, rng, palette=None, level=1):
        """n bytes of dump. palette is a hint: 'use about this many distinct
        byte values', which only a source with free choice can honour."""
        raise NotImplementedError

    def packet(self, rng, level=1, need=()):
        """A parsed Packet containing every layer named in need, or None if
        this source has no packets."""
        return None

    def node_name(self, rng):
        raise NotImplementedError

    def describe(self):
        return self.mode


# ------------------------------------------------------------------- RAW

class RandomSource(ByteSource):
    mode = "RAW"

    def buffer(self, n, rng, palette=None, level=1):
        if palette:
            values = rng.sample(range(256), palette)
            return bytearray(rng.choice(values) for _ in range(n))
        return bytearray(rng.getrandbits(8) for _ in range(n))

    def node_name(self, rng):
        return "node-%04X" % rng.getrandbits(16)

    def describe(self):
        return "random bytes"


# -------------------------------------------------------------- PROTOCOL

OUIS = ["3c:22:fb", "f4:5c:89", "a4:83:e7", "b8:27:eb", "dc:a6:32", "00:50:56", "00:1a:2b", "70:85:c2",
        "ac:de:48", "00:25:90"]
PUBLIC_FIRST = [8, 13, 23, 34, 52, 64, 93, 104, 142, 151, 185, 198, 203]
TCP_SERVICES = [80, 443, 443, 22, 25, 8080, 3306, 5432, 6379, 8443]
HOSTS = ["vault.orbital.bank", "ids.blackwall.net", "db.zaibatsu.corp", "cdn.neonmarket.io",
         "auth.kowloon.grid", "mail.helix.systems", "relay.deepnet.org", "api.chromeline.co",
         "files.nullsec.dev", "ns1.undercity.net", "intranet.monolith.corp", "www.example.com"]
PATHS = ["/", "/index.html", "/login", "/api/v2/accounts", "/admin/config", "/static/app.js",
         "/vault/keys", "/status", "/users/42/profile", "/download/manifest.bin"]
AGENTS = ["curl/8.4.0", "Mozilla/5.0 (X11; Linux x86_64)", "netrunner/2.0.77", "python-requests/2.31"]
SYSLOG = ["<34>Oct 11 22:14:15 gate su: 'su root' failed for operator on /dev/pts/8",
          "<13>Feb  5 17:32:18 relay sshd[4721]: Accepted publickey for deploy",
          "<86>Mar 29 03:07:44 vault sudo: session opened for user root",
          "<30>Aug 19 11:50:02 edge dhcpd: DHCPACK on 10.0.0.87 via eth0"]
BODIES = [b"<html><body><h1>It works!</h1></body></html>\n",
          b'{"status":"ok","session":"7f3a9c","role":"admin"}\n',
          b"<html><head><title>401</title></head><body>ACCESS DENIED</body></html>\n",
          b"user=operator&token=deadbeefcafe&remember=1\n"]

# (first subnet it appears in, kind, layers it contains)
SYNTH_KINDS = [
    (1, "tcp_ctl", {"Ethernet", "IPv4", "TCP"}),
    (1, "udp", {"Ethernet", "IPv4", "UDP"}),
    (2, "tcp_data", {"Ethernet", "IPv4", "TCP"}),
    (2, "tcp_opts", {"Ethernet", "IPv4", "TCP"}),
    (3, "dns_q", {"Ethernet", "IPv4", "UDP", "DNS"}),
    (3, "dns_r", {"Ethernet", "IPv4", "UDP", "DNS"}),
    (4, "http_req", {"Ethernet", "IPv4", "TCP", "HTTP"}),
    (4, "http_resp", {"Ethernet", "IPv4", "TCP", "HTTP"}),
    (5, "ip_opts", {"Ethernet", "IPv4", "TCP"}),
]


def rand_mac(rng):
    return "%s:%02x:%02x:%02x" % (rng.choice(OUIS), rng.getrandbits(8), rng.getrandbits(8), rng.getrandbits(8))


def rand_private_ip(rng):
    kind = rng.randrange(3)
    if kind == 0:
        return "192.168.%d.%d" % (rng.randrange(0, 5), rng.randrange(2, 250))
    if kind == 1:
        return "10.%d.%d.%d" % (rng.randrange(0, 4), rng.randrange(0, 255), rng.randrange(2, 250))
    return "172.%d.%d.%d" % (rng.randrange(16, 32), rng.randrange(0, 255), rng.randrange(2, 250))


def rand_public_ip(rng):
    return "%d.%d.%d.%d" % (rng.choice(PUBLIC_FIRST), rng.randrange(1, 255), rng.randrange(0, 255),
                            rng.randrange(1, 255))


class _Endpoints:
    """One client talking to one server through one gateway."""

    def __init__(self, rng, sport=None, dport=None):
        self.cmac, self.gmac = rand_mac(rng), rand_mac(rng)
        self.cip, self.sip = rand_private_ip(rng), rand_public_ip(rng)
        self.sport = sport or rng.randrange(49152, 65535)
        self.dport = dport or rng.choice(TCP_SERVICES)
        self.cttl = rng.choice([64, 64, 128])
        self.sttl = rng.choice([64, 128, 255]) - rng.randrange(4, 22)
        self.cid, self.sid = rng.getrandbits(16), rng.getrandbits(16)
        self.cseq, self.sseq = rng.getrandbits(32), rng.getrandbits(32)

    def c2s(self, **tcp):
        self.cid = (self.cid + 1) & 0xFFFF
        return frame_tcp(self.cmac, self.gmac, self.cip, self.sip, self.sport, self.dport,
                         ttl=self.cttl, ident=self.cid, **tcp)

    def s2c(self, **tcp):
        self.sid = (self.sid + 1) & 0xFFFF
        return frame_tcp(self.gmac, self.cmac, self.sip, self.cip, self.dport, self.sport,
                         ttl=self.sttl, ident=self.sid, **tcp)


def _syn_options(rng):
    # MSS 1460, SACK permitted, timestamps, NOP, window scale 7
    return (b"\x02\x04\x05\xb4" + b"\x04\x02" + b"\x08\x0a" + struct.pack("!II", rng.getrandbits(32), 0)
            + b"\x01" + b"\x03\x03\x07")


def _tls_record(rng, size):
    return b"\x17\x03\x03" + struct.pack("!H", size) + bytes(rng.getrandbits(8) for _ in range(size))


def _ntp(rng):
    return b"\x23\x02\x06\xec" + bytes(12) + bytes(rng.getrandbits(8) for _ in range(32))


class SynthSource(ByteSource):
    mode = "PROTOCOL"
    has_packets = True

    def packet(self, rng, level=1, need=()):
        need = set(need)
        cands = [k for k in SYNTH_KINDS if k[0] <= level and need <= k[2]]
        if not cands:
            cands = [k for k in SYNTH_KINDS if need <= k[2]]
        if not cands:
            return None
        # favour whatever is new at this depth so later subnets feel different
        weights = [3 if k[0] == int(level) else 1 for k in cands]
        kind = rng.choices(cands, weights)[0][1]
        return parse(self.make(kind, rng))

    def make(self, kind, rng):
        if kind == "tcp_ctl":
            ep = _Endpoints(rng)
            which = rng.randrange(5)
            win = rng.choice([64240, 65535, 29200, 8192, 1024])
            if which == 0:
                return ep.c2s(seq=ep.cseq, flags=TCP_SYN, window=win)
            if which == 1:
                return ep.s2c(seq=ep.sseq, ack=ep.cseq + 1, flags=TCP_SYN | TCP_ACK, window=win)
            if which == 2:
                return ep.c2s(seq=ep.cseq, ack=ep.sseq, flags=TCP_ACK, window=win)
            if which == 3:
                return ep.c2s(seq=ep.cseq, ack=ep.sseq, flags=TCP_FIN | TCP_ACK, window=win)
            return ep.s2c(seq=ep.sseq, flags=TCP_RST, window=0)
        if kind == "udp":
            cmac, gmac = rand_mac(rng), rand_mac(rng)
            cip = rand_private_ip(rng)
            if rng.random() < 0.5:
                return frame_udp(cmac, gmac, cip, rand_public_ip(rng), rng.randrange(49152, 65535), 123,
                                 _ntp(rng), ttl=64, ident=rng.getrandbits(16))
            return frame_udp(cmac, gmac, cip, rand_private_ip(rng), rng.randrange(49152, 65535), 514,
                             rng.choice(SYSLOG).encode(), ttl=64, ident=rng.getrandbits(16))
        if kind == "tcp_data":
            if rng.random() < 0.6:
                ep = _Endpoints(rng, dport=443)
                payload = _tls_record(rng, rng.randrange(24, 90))
            else:
                ep = _Endpoints(rng, dport=22)
                payload = b"SSH-2.0-OpenSSH_9.%d\r\n" % rng.randrange(0, 9)
            send = ep.c2s if rng.random() < 0.5 else ep.s2c
            return send(seq=ep.cseq, ack=ep.sseq, flags=TCP_PSH | TCP_ACK, payload=payload,
                        window=rng.choice([501, 2048, 65535]))
        if kind == "tcp_opts":
            ep = _Endpoints(rng)
            return ep.c2s(seq=ep.cseq, flags=TCP_SYN, window=64240, options=_syn_options(rng))
        if kind in ("dns_q", "dns_r"):
            cmac, gmac = rand_mac(rng), rand_mac(rng)
            cip, resolver = rand_private_ip(rng), rng.choice(["8.8.8.8", "1.1.1.1", "9.9.9.9", "10.0.0.1"])
            sport, txid, host = rng.randrange(49152, 65535), rng.getrandbits(16), rng.choice(HOSTS)
            if kind == "dns_q":
                return frame_udp(cmac, gmac, cip, resolver, sport, 53,
                                 build_dns_query(txid, host, rng.choice([1, 1, 1, 28, 15])),
                                 ident=rng.getrandbits(16))
            addrs = [rand_public_ip(rng) for _ in range(rng.randrange(1, 3))]
            return frame_udp(gmac, cmac, resolver, cip, 53, sport, build_dns_response(txid, host, addrs),
                             ttl=rng.randrange(50, 60), ident=rng.getrandbits(16))
        if kind == "http_req":
            ep = _Endpoints(rng, dport=rng.choice([80, 80, 8080]))
            payload = build_http_request(rng.choice(["GET", "GET", "POST", "HEAD"]), rng.choice(PATHS),
                                         rng.choice(HOSTS), [("User-Agent", rng.choice(AGENTS)),
                                                             ("Accept", "*/*")])
            return ep.c2s(seq=ep.cseq, ack=ep.sseq, flags=TCP_PSH | TCP_ACK, payload=payload, window=502)
        if kind == "http_resp":
            ep = _Endpoints(rng, dport=rng.choice([80, 80, 8080]))
            status, reason = rng.choice([(200, "OK"), (200, "OK"), (301, "Moved Permanently"),
                                         (403, "Forbidden"), (404, "Not Found"),
                                         (500, "Internal Server Error")])
            payload = build_http_response(status, reason, rng.choice(BODIES),
                                          [("Server", "nginx/1.24.0"), ("Content-Type", "text/html")])
            return ep.s2c(seq=ep.sseq, ack=ep.cseq, flags=TCP_PSH | TCP_ACK, payload=payload, window=509)
        if kind == "ip_opts":
            ep = _Endpoints(rng)
            options = rng.choice([b"\x94\x04\x00\x00",                      # router alert
                                  b"\x07\x07\x04\x00\x00\x00\x00\x00"])     # record route + EOL
            ep.cid = (ep.cid + 1) & 0xFFFF
            return frame_tcp(ep.cmac, ep.gmac, ep.cip, ep.sip, ep.sport, ep.dport, ttl=ep.cttl,
                             ident=ep.cid, ip_options=options, seq=ep.cseq, ack=ep.sseq, flags=TCP_ACK,
                             window=4096)
        raise ValueError(kind)

    def flow(self, rng, level=1):
        """A short conversation as a list of raw frames."""
        kinds = ["tcp"] + (["dns"] if level >= 3 else []) + (["http", "http"] if level >= 4 else [])
        kind = rng.choice(kinds)
        if kind == "dns":
            cmac, gmac, cip = rand_mac(rng), rand_mac(rng), rand_private_ip(rng)
            sport, txid, host = rng.randrange(49152, 65535), rng.getrandbits(16), rng.choice(HOSTS)
            return [frame_udp(cmac, gmac, cip, "8.8.8.8", sport, 53, build_dns_query(txid, host)),
                    frame_udp(gmac, cmac, "8.8.8.8", cip, 53, sport,
                              build_dns_response(txid, host, [rand_public_ip(rng)]), ttl=57)]
        ep = _Endpoints(rng, dport=80 if kind == "http" else None)
        c, s = ep.cseq, ep.sseq
        frames = [ep.c2s(seq=c, flags=TCP_SYN, window=64240),
                  ep.s2c(seq=s, ack=c + 1, flags=TCP_SYN | TCP_ACK, window=65160),
                  ep.c2s(seq=c + 1, ack=s + 1, flags=TCP_ACK, window=502)]
        if kind == "http":
            req = build_http_request("GET", rng.choice(PATHS), rng.choice(HOSTS),
                                     [("User-Agent", rng.choice(AGENTS))])
            resp = build_http_response(200, "OK", rng.choice(BODIES), [("Server", "nginx/1.24.0")])
        else:
            req = _tls_record(rng, rng.randrange(20, 60))
            resp = _tls_record(rng, rng.randrange(30, 100))
        frames += [ep.c2s(seq=c + 1, ack=s + 1, flags=TCP_PSH | TCP_ACK, window=502, payload=req),
                   ep.s2c(seq=s + 1, ack=c + 1 + len(req), flags=TCP_ACK, window=509),
                   ep.s2c(seq=s + 1, ack=c + 1 + len(req), flags=TCP_PSH | TCP_ACK, window=509, payload=resp),
                   ep.c2s(seq=c + 1 + len(req), ack=s + 1 + len(resp), flags=TCP_FIN | TCP_ACK, window=501)]
        return frames

    def buffer(self, n, rng, palette=None, level=1):
        out = bytearray()
        while len(out) < n:
            for frame in self.flow(rng, level):
                out += frame
        return out[:n]

    def node_name(self, rng):
        return "%s:%d" % (rand_public_ip(rng) if rng.random() < 0.6 else rand_private_ip(rng),
                          rng.choice(TCP_SERVICES + [53, 123, 21, 23, 445, 3389]))

    def describe(self):
        return "synthesized packets"


# ------------------------------------------------------------------ LIVE

PCAP_MAGICS = {b"\xd4\xc3\xb2\xa1": "<", b"\xa1\xb2\xc3\xd4": ">",      # microsecond timestamps
               b"\x4d\x3c\xb2\xa1": "<", b"\xa1\xb2\x3c\x4d": ">"}      # nanosecond timestamps
PCAPNG_SHB = 0x0A0D0D0A
MAX_FRAMES = 20000            # packets kept across all captures
MAX_FILE_BYTES = 64 << 20     # read at most this much of any one capture


class CaptureError(Exception):
    pass


def read_pcap(data):
    """Classic libpcap file -> list of (linktype, frame bytes, original length)."""
    if len(data) < 24 or data[:4] not in PCAP_MAGICS:
        raise CaptureError("not a pcap file")
    e = PCAP_MAGICS[data[:4]]
    linktype = struct.unpack(e + "I", data[20:24])[0] & 0x0FFFFFFF
    frames, off = [], 24
    while off + 16 <= len(data) and len(frames) < MAX_FRAMES:
        incl, orig = struct.unpack(e + "II", data[off + 8:off + 16])
        off += 16
        if off + incl > len(data):
            break                       # truncated final record: keep what we have
        frames.append((linktype, data[off:off + incl], orig))
        off += incl
    return frames


def read_pcapng(data):
    """pcapng file -> list of (linktype, frame bytes, original length)."""
    if len(data) < 12 or struct.unpack("<I", data[:4])[0] != PCAPNG_SHB:
        raise CaptureError("not a pcapng file")
    frames, off, e, linktypes = [], 0, "<", []
    while off + 12 <= len(data) and len(frames) < MAX_FRAMES:
        btype = struct.unpack(e + "I", data[off:off + 4])[0]
        if btype == PCAPNG_SHB:         # section header: sets byte order, resets interfaces
            bom = data[off + 8:off + 12]
            e = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">" if bom == b"\x1a\x2b\x3c\x4d" else None
            if e is None:
                raise CaptureError("bad pcapng byte-order magic")
            linktypes = []
        blen = struct.unpack(e + "I", data[off + 4:off + 8])[0]
        if blen < 12 or blen % 4 or off + blen > len(data):
            break
        body = data[off + 8:off + blen - 4]
        if btype == 1 and len(body) >= 8:                 # interface description
            linktypes.append(struct.unpack(e + "H", body[:2])[0])
        elif btype == 6 and len(body) >= 20:              # enhanced packet
            iface, _, _, caplen, orig = struct.unpack(e + "IIIII", body[:20])
            if iface < len(linktypes) and 20 + caplen <= len(body):
                frames.append((linktypes[iface], body[20:20 + caplen], orig))
        elif btype == 3 and len(body) >= 4 and linktypes:  # simple packet
            orig = struct.unpack(e + "I", body[:4])[0]
            frames.append((linktypes[0], body[4:4 + min(orig, len(body) - 4)], orig))
        elif btype == 2 and len(body) >= 20:              # obsolete packet block
            iface, _, _, _, caplen, orig = struct.unpack(e + "HHIIII", body[:20])
            if iface < len(linktypes) and 20 + caplen <= len(body):
                frames.append((linktypes[iface], body[20:20 + caplen], orig))
        off += blen
    return frames


def read_capture(path):
    with open(path, "rb") as fh:
        data = fh.read(MAX_FILE_BYTES)
    if data[:4] in PCAP_MAGICS:
        return read_pcap(data)
    if len(data) >= 4 and struct.unpack("<I", data[:4])[0] == PCAPNG_SHB:
        return read_pcapng(data)
    raise CaptureError("unrecognised capture format")


def write_pcap(path, frames, linktype=packets.LINKTYPE_ETHERNET, endian="<", nanos=False):
    magic = 0xA1B23C4D if nanos else 0xA1B2C3D4
    with open(path, "wb") as fh:
        fh.write(struct.pack(endian + "IHHiIII", magic, 2, 4, 0, 0, 262144, linktype))
        for i, frame in enumerate(frames):
            fh.write(struct.pack(endian + "IIII", 1700000000 + i, 0, len(frame), len(frame)))
            fh.write(frame)


def write_pcapng(path, frames, linktype=packets.LINKTYPE_ETHERNET, endian="<"):
    def block(btype, body):
        body += b"\x00" * (-len(body) % 4)
        total = len(body) + 12
        return struct.pack(endian + "II", btype, total) + body + struct.pack(endian + "I", total)

    with open(path, "wb") as fh:
        fh.write(block(PCAPNG_SHB, struct.pack(endian + "IHHq", 0x1A2B3C4D, 1, 0, -1)))
        fh.write(block(1, struct.pack(endian + "HHI", linktype, 0, 262144)))
        for i, frame in enumerate(frames):
            fh.write(block(6, struct.pack(endian + "IIIII", 0, 0, i, len(frame), len(frame)) + frame))


class PcapSource(ByteSource):
    """Packets from the player's own captures. Nothing leaves the machine:
    files are read from disk, parsed in memory and never written or sent."""
    mode = "LIVE"
    has_packets = True
    MIN_USABLE = 12

    def __init__(self, directory, fallback=None):
        self.directory = directory
        self.fallback = fallback or SynthSource()
        self.files, self.errors = [], []
        self.packets = []           # usable parsed packets, capture order
        self.endpoints = []
        self._by_layer = {}
        self._load()

    def _load(self):
        names = []
        if os.path.isdir(self.directory):
            names = sorted(f for f in os.listdir(self.directory)
                           if f.lower().endswith((".pcap", ".pcapng", ".cap")))
        seen = set()
        for name in names:
            try:
                frames = read_capture(os.path.join(self.directory, name))
            except (CaptureError, OSError, struct.error) as exc:
                self.errors.append("%s: %s" % (name, exc))
                continue
            self.files.append(name)
            for linktype, frame, _orig in frames:
                if len(self.packets) >= MAX_FRAMES:
                    break
                pkt = parse(frame, linktype)
                # usable = we could read an IP header out of it
                if not (pkt.has("IPv4") or pkt.has("IPv6")):
                    continue
                self.packets.append(pkt)
                i = pkt.info
                for ip, port in ((i["src_ip"], i.get("sport")), (i["dst_ip"], i.get("dport"))):
                    key = (ip, port)
                    if port is not None and key not in seen:
                        seen.add(key)
                        self.endpoints.append(key)
        for idx, pkt in enumerate(self.packets):
            for layer in pkt.layer_names():
                self._by_layer.setdefault(layer, []).append(idx)

    @property
    def using_fallback(self):
        return len(self.packets) < self.MIN_USABLE

    def packet(self, rng, level=1, need=()):
        if self.using_fallback:
            return self.fallback.packet(rng, level, need)
        need = set(need)
        pools = [set(self._by_layer.get(layer, ())) for layer in need]
        cands = sorted(set.intersection(*pools)) if pools else None
        if cands is None:
            # no requirement: deeper subnets lean towards parsed application layers
            rich = [i for layer in ("DNS", "HTTP") for i in self._by_layer.get(layer, ())]
            if level >= 3 and rich and rng.random() < 0.5:
                return self.packets[rng.choice(rich)]
            return rng.choice(self.packets)
        if not cands:
            return self.fallback.packet(rng, level, need)
        return self.packets[rng.choice(cands)]

    def buffer(self, n, rng, palette=None, level=1):
        if self.using_fallback:
            return self.fallback.buffer(n, rng, palette, level)
        out = bytearray()
        i = rng.randrange(len(self.packets))
        while len(out) < n:
            out += self.packets[i % len(self.packets)].raw
            i += 1
        return out[:n]

    def node_name(self, rng):
        if self.using_fallback or not self.endpoints:
            return self.fallback.node_name(rng)
        ip, port = rng.choice(self.endpoints)
        return "%s:%d" % (ip, port)

    def describe(self):
        if not self.files:
            return "captures/ is empty: using synthesized packets"
        if self.using_fallback:
            return "%d file(s) but only %d usable packets: using synthesized packets" % (
                len(self.files), len(self.packets))
        return "%d file(s), %d usable packets" % (len(self.files), len(self.packets))


def make_source(mode, captures_dir=None):
    if mode == "RAW":
        return RandomSource()
    if mode == "PROTOCOL":
        return SynthSource()
    if mode == "LIVE":
        return PcapSource(captures_dir or "captures")
    raise ValueError(mode)
