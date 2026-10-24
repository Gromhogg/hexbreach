"""Build and parse Ethernet / IPv4 / IPv6 / TCP / UDP / DNS / HTTP.

parse() returns a Packet whose field map (field name -> byte range) drives the
DISSECT and CHECKSUM puzzles and the field manual. Builders always emit valid
checksums, so build -> parse round-trips.
"""
import ipaddress
import struct

LINKTYPE_NULL = 0
LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_LINUX_SLL = 113
LINKTYPE_IPV4 = 228
LINKTYPE_IPV6 = 229

ETH_IPV4 = 0x0800
ETH_ARP = 0x0806
ETH_VLAN = 0x8100
ETH_IPV6 = 0x86DD

PROTO_ICMP = 1
PROTO_TCP = 6
PROTO_UDP = 17
PROTO_ICMPV6 = 58

TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_PSH = 0x08
TCP_ACK = 0x10
TCP_URG = 0x20

ETHERTYPES = {ETH_IPV4: "IPv4", ETH_ARP: "ARP", ETH_IPV6: "IPv6", ETH_VLAN: "802.1Q"}
IP_PROTOS = {PROTO_ICMP: "ICMP", PROTO_TCP: "TCP", PROTO_UDP: "UDP", PROTO_ICMPV6: "ICMPv6"}
DNS_TYPES = {1: "A", 2: "NS", 5: "CNAME", 12: "PTR", 15: "MX", 16: "TXT", 28: "AAAA", 65: "HTTPS"}
HTTP_METHODS = (b"GET", b"POST", b"PUT", b"HEAD", b"DELETE", b"OPTIONS", b"PATCH")

# name -> (layer, label, description). Order here is the order the field manual shows.
FIELD_INFO = {
    "eth.dst": ("Ethernet", "Destination MAC Address",
                "Hardware address of the next hop on the local link. ff:ff:ff:ff:ff:ff is broadcast."),
    "eth.src": ("Ethernet", "Source MAC Address",
                "Hardware address of the sender. The first 3 bytes (the OUI) identify the vendor."),
    "eth.type": ("Ethernet", "EtherType",
                 "What the frame carries: 0800 IPv4, 0806 ARP, 86DD IPv6, 8100 VLAN tag."),
    "ip.ver_ihl": ("IPv4", "Version / IHL",
                   "High nibble: version (4). Low nibble: IHL, the header length in 32-bit words (5 = 20 bytes)."),
    "ip.dscp": ("IPv4", "DSCP / ECN", "Quality-of-service marking. Usually 00."),
    "ip.len": ("IPv4", "Total Length", "Length of the whole IP packet, header plus payload, in bytes."),
    "ip.id": ("IPv4", "Identification", "ID shared by all fragments of one datagram."),
    "ip.frag": ("IPv4", "Flags / Fragment Offset",
                "3 flag bits + 13-bit offset. 4000 = Don't Fragment, 2000 = More Fragments."),
    "ip.ttl": ("IPv4", "Time to Live",
               "TTL: a hop limit, decremented by every router. Typical start: 64 (Linux/macOS), 128 (Windows)."),
    "ip.proto": ("IPv4", "Protocol", "What the payload is: 01 ICMP, 06 TCP, 11 UDP."),
    "ip.checksum": ("IPv4", "Header Checksum",
                    "One's-complement sum over the IP header only. All header words, this one included, add up to FFFF."),
    "ip.src": ("IPv4", "Source Address", "Sender's IP address: 4 bytes, one per number of the dotted-decimal form."),
    "ip.dst": ("IPv4", "Destination Address",
               "Receiver's IP address: 4 bytes, one per number of the dotted-decimal form."),
    "ip.options": ("IPv4", "Options",
                   "Only present when IHL > 5. Pushes everything after it deeper into the frame."),
    "ipv6.vtf": ("IPv6", "Version / Traffic Class / Flow Label",
                 "4 bits version (6), 8 bits traffic class, 20 bits flow label."),
    "ipv6.plen": ("IPv6", "Payload Length", "Bytes after the fixed 40-byte header."),
    "ipv6.next": ("IPv6", "Next Header", "Same numbering as IPv4 Protocol: 06 TCP, 11 UDP, 3A ICMPv6."),
    "ipv6.hlim": ("IPv6", "Hop Limit", "IPv6's name for Time to Live."),
    "ipv6.src": ("IPv6", "Source Address", "Sender's IP address, 16 bytes."),
    "ipv6.dst": ("IPv6", "Destination Address", "Receiver's IP address, 16 bytes."),
    "tcp.sport": ("TCP", "Source Port", "Sender's port. Clients use a random high (ephemeral) port."),
    "tcp.dport": ("TCP", "Destination Port",
                  "Receiver's port. 0050 = 80 HTTP, 01BB = 443 HTTPS, 0016 = 22 SSH."),
    "tcp.seq": ("TCP", "Sequence Number", "Position of this segment's first data byte in the stream."),
    "tcp.ack": ("TCP", "Acknowledgment Number", "Next sequence number expected from the other side."),
    "tcp.offset": ("TCP", "Data Offset", "High nibble: TCP header length in 32-bit words (5 = 20 bytes)."),
    "tcp.flags": ("TCP", "Flags", "02 SYN, 12 SYN+ACK, 10 ACK, 18 PSH+ACK, 11 FIN+ACK, 04 RST."),
    "tcp.window": ("TCP", "Window", "How many bytes the sender is willing to receive."),
    "tcp.checksum": ("TCP", "Checksum",
                     "Covers a pseudo-header (IP addresses, protocol, length), the TCP header and the payload."),
    "tcp.urgent": ("TCP", "Urgent Pointer", "Only meaningful with the URG flag. Almost always 0000."),
    "tcp.options": ("TCP", "Options",
                    "Present when Data Offset > 5: MSS, window scale, SACK permitted, timestamps."),
    "udp.sport": ("UDP", "Source Port", "Sender's port."),
    "udp.dport": ("UDP", "Destination Port", "Receiver's port. 0035 = 53 DNS, 007B = 123 NTP."),
    "udp.len": ("UDP", "Length", "UDP header (8 bytes) plus payload, in bytes."),
    "udp.checksum": ("UDP", "Checksum",
                     "Same pseudo-header scheme as TCP. On IPv4, 0000 means 'not computed'."),
    "dns.id": ("DNS", "Transaction ID", "Random ID. The response echoes it so the client can match it up."),
    "dns.flags": ("DNS", "Flags", "0100 = standard query, recursion desired. 8180 = response, no error."),
    "dns.qdcount": ("DNS", "Questions", "Number of entries in the question section. Nearly always 1."),
    "dns.ancount": ("DNS", "Answer RRs", "Number of answer resource records (RRs). 0 in a query."),
    "dns.nscount": ("DNS", "Authority RRs", "Number of authority resource records."),
    "dns.arcount": ("DNS", "Additional RRs", "Number of additional resource records."),
    "dns.qname": ("DNS", "Query Name",
                  "Length-prefixed labels ending in 00: 07 'example' 03 'com' 00."),
    "dns.qtype": ("DNS", "Query Type", "0001 A, 001C AAAA, 000F MX, 0010 TXT, 0005 CNAME."),
    "dns.qclass": ("DNS", "Query Class", "0001 = IN (Internet). Practically always."),
    "http.method": ("HTTP", "Method", "GET, POST, HEAD... plain ASCII at the very start of the TCP payload."),
    "http.path": ("HTTP", "Request Target", "The path being asked for, between the method and the version."),
    "http.version": ("HTTP", "Version", "HTTP/1.1. Ends the first line of a request, starts a response."),
    "http.status": ("HTTP", "Status Code", "Three ASCII digits: 200 OK, 301 moved, 404 not found, 500 error."),
    "http.host": ("HTTP", "Host Header", "The site name the client wants. Lets one IP serve many sites."),
}

# name -> (offset within its layer or None if it moves, size or None if variable)
FIELD_LAYOUT = {
    "eth.dst": (0, 6), "eth.src": (6, 6), "eth.type": (12, 2),
    "ip.ver_ihl": (0, 1), "ip.dscp": (1, 1), "ip.len": (2, 2), "ip.id": (4, 2), "ip.frag": (6, 2),
    "ip.ttl": (8, 1), "ip.proto": (9, 1), "ip.checksum": (10, 2), "ip.src": (12, 4), "ip.dst": (16, 4),
    "ip.options": (20, None),
    "ipv6.vtf": (0, 4), "ipv6.plen": (4, 2), "ipv6.next": (6, 1), "ipv6.hlim": (7, 1),
    "ipv6.src": (8, 16), "ipv6.dst": (24, 16),
    "tcp.sport": (0, 2), "tcp.dport": (2, 2), "tcp.seq": (4, 4), "tcp.ack": (8, 4), "tcp.offset": (12, 1),
    "tcp.flags": (13, 1), "tcp.window": (14, 2), "tcp.checksum": (16, 2), "tcp.urgent": (18, 2),
    "tcp.options": (20, None),
    "udp.sport": (0, 2), "udp.dport": (2, 2), "udp.len": (4, 2), "udp.checksum": (6, 2),
    "dns.id": (0, 2), "dns.flags": (2, 2), "dns.qdcount": (4, 2), "dns.ancount": (6, 2),
    "dns.nscount": (8, 2), "dns.arcount": (10, 2), "dns.qname": (12, None), "dns.qtype": (None, 2),
    "dns.qclass": (None, 2),
    "http.method": (0, None), "http.path": (None, None), "http.version": (None, 8),
    "http.status": (None, 3), "http.host": (None, None),
}

LAYER_ORDER = ["Ethernet", "IPv4", "IPv6", "TCP", "UDP", "DNS", "HTTP"]
LAYER_NOTES = {
    "Ethernet": "Ethernet II header, 14 bytes. First thing in every frame on a wired or Wi-Fi capture.",
    "IPv4": "20 bytes without options. Starts at 0x0E in an Ethernet frame; first byte is almost always 45.",
    "IPv6": "Fixed 40 bytes. First nibble is 6. No header checksum.",
    "TCP": "20 bytes without options. Starts at 0x22 after a 20-byte IPv4 header.",
    "UDP": "Always 8 bytes: two ports, a length and a checksum.",
    "DNS": "12-byte header, then the question. Usually rides on UDP port 53.",
    "HTTP": "Plain ASCII in the TCP payload. Read it in the ASCII pane.",
}


# ---------------------------------------------------------------- helpers

def mac_bytes(mac):
    return bytes(int(p, 16) for p in mac.split(":"))


def mac_str(b):
    return ":".join("%02x" % x for x in b)


def ip_bytes(ip):
    if isinstance(ip, (bytes, bytearray)):
        return bytes(ip)
    return ipaddress.ip_address(ip).packed


def ip_str(b):
    if len(b) == 4:
        return ".".join(str(x) for x in b)
    return ipaddress.IPv6Address(bytes(b)).compressed


def _u16(raw, off):
    return (raw[off] << 8) | raw[off + 1]


def _u32(raw, off):
    return int.from_bytes(raw[off:off + 4], "big")


# -------------------------------------------------------------- checksums

def ones_sum(data):
    """Folded 16-bit one's-complement sum. A block containing a correct
    checksum sums to 0xFFFF."""
    data = bytes(data)
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data)) if data else 0
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total


def inet_checksum(data):
    return (~ones_sum(data)) & 0xFFFF


def pseudo_header(src, dst, proto, length):
    src, dst = ip_bytes(src), ip_bytes(dst)
    if len(src) == 4:
        return src + dst + struct.pack("!BBH", 0, proto, length)
    return src + dst + struct.pack("!IBBBB", length, 0, 0, 0, proto)


def l4_checksum(src, dst, proto, segment):
    """TCP/UDP checksum of a segment whose checksum field is zeroed."""
    return inet_checksum(pseudo_header(src, dst, proto, len(segment)) + bytes(segment))


def l4_sum(src, dst, proto, segment):
    """One's-complement sum over pseudo-header + segment; 0xFFFF when valid."""
    return ones_sum(pseudo_header(src, dst, proto, len(segment)) + bytes(segment))


# --------------------------------------------------------------- builders

def build_ethernet(dst, src, ethertype, payload=b""):
    return mac_bytes(dst) + mac_bytes(src) + struct.pack("!H", ethertype) + payload


def build_ipv4(src, dst, proto, payload=b"", ttl=64, ident=0, flags_frag=0x4000, dscp=0, options=b""):
    if len(options) % 4:
        raise ValueError("IPv4 options must be padded to 4 bytes")
    ihl = 5 + len(options) // 4
    total = ihl * 4 + len(payload)
    hdr = struct.pack("!BBHHHBBH4s4s", (4 << 4) | ihl, dscp, total, ident, flags_frag, ttl, proto, 0,
                      ip_bytes(src), ip_bytes(dst)) + options
    hdr = hdr[:10] + struct.pack("!H", inet_checksum(hdr)) + hdr[12:]
    return hdr + payload


def build_ipv6(src, dst, next_header, payload=b"", hop_limit=64, flow=0):
    hdr = struct.pack("!IHBB", (6 << 28) | (flow & 0xFFFFF), len(payload), next_header, hop_limit)
    return hdr + ip_bytes(src) + ip_bytes(dst) + payload


def build_tcp(src_ip, dst_ip, sport, dport, seq=0, ack=0, flags=TCP_ACK, window=65535,
              payload=b"", options=b"", urgent=0):
    if len(options) % 4:
        raise ValueError("TCP options must be padded to 4 bytes")
    offset = 5 + len(options) // 4
    seg = struct.pack("!HHIIBBHHH", sport, dport, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF, offset << 4,
                      flags, window, 0, urgent) + options + payload
    csum = l4_checksum(src_ip, dst_ip, PROTO_TCP, seg)
    return seg[:16] + struct.pack("!H", csum) + seg[18:]


def build_udp(src_ip, dst_ip, sport, dport, payload=b""):
    seg = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    csum = l4_checksum(src_ip, dst_ip, PROTO_UDP, seg) or 0xFFFF
    return seg[:6] + struct.pack("!H", csum) + seg[8:]


def encode_qname(name):
    out = b""
    for label in name.strip(".").split("."):
        raw = label.encode("ascii")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def build_dns_query(txid, name, qtype=1):
    return struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0) + encode_qname(name) + struct.pack("!HH", qtype, 1)


def build_dns_response(txid, name, addrs, qtype=1, ttl=300):
    out = struct.pack("!HHHHHH", txid, 0x8180, 1, len(addrs), 0, 0)
    out += encode_qname(name) + struct.pack("!HH", qtype, 1)
    for addr in addrs:
        rdata = ip_bytes(addr)
        out += b"\xc0\x0c" + struct.pack("!HHIH", qtype, 1, ttl, len(rdata)) + rdata
    return out


def build_http_request(method, path, host, headers=()):
    lines = ["%s %s HTTP/1.1" % (method, path), "Host: %s" % host]
    lines += ["%s: %s" % kv for kv in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def build_http_response(status, reason, body=b"", headers=()):
    lines = ["HTTP/1.1 %d %s" % (status, reason)]
    lines += ["%s: %s" % kv for kv in headers]
    lines.append("Content-Length: %d" % len(body))
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def frame_tcp(src_mac, dst_mac, src_ip, dst_ip, sport, dport, ttl=64, ident=0, ip_options=b"", **tcp):
    seg = build_tcp(src_ip, dst_ip, sport, dport, **tcp)
    ip = build_ipv4(src_ip, dst_ip, PROTO_TCP, seg, ttl=ttl, ident=ident, options=ip_options)
    return build_ethernet(dst_mac, src_mac, ETH_IPV4, ip)


def frame_udp(src_mac, dst_mac, src_ip, dst_ip, sport, dport, payload=b"", ttl=64, ident=0):
    seg = build_udp(src_ip, dst_ip, sport, dport, payload)
    ip = build_ipv4(src_ip, dst_ip, PROTO_UDP, seg, ttl=ttl, ident=ident, flags_frag=0)
    return build_ethernet(dst_mac, src_mac, ETH_IPV4, ip)


# ----------------------------------------------------------------- parser

class Field:
    __slots__ = ("name", "start", "end", "value")

    def __init__(self, name, start, end, value):
        self.name, self.start, self.end, self.value = name, start, end, value

    layer = property(lambda self: FIELD_INFO[self.name][0])
    label = property(lambda self: FIELD_INFO[self.name][1])
    desc = property(lambda self: FIELD_INFO[self.name][2])

    def __repr__(self):
        return "Field(%s %d:%d %s)" % (self.name, self.start, self.end, self.value)


class Packet:
    """A frame plus its layer boundaries and field map."""

    def __init__(self, raw, linktype=LINKTYPE_ETHERNET):
        self.raw = bytes(raw)
        self.linktype = linktype
        self.layers = []      # (name, start, end)
        self.fields = {}      # name -> Field, in wire order
        self.info = {}

    def add_layer(self, name, start, end):
        if end > start:
            self.layers.append((name, start, end))

    def add(self, name, start, end, value):
        self.fields[name] = Field(name, start, end, value)

    def has(self, layer):
        return any(name == layer for name, _, _ in self.layers)

    def layer_range(self, layer):
        for name, start, end in self.layers:
            if name == layer:
                return start, end
        return None

    def field_at(self, idx):
        for f in self.fields.values():
            if f.start <= idx < f.end:
                return f
        return None

    def layer_names(self):
        return {name for name, _, _ in self.layers}

    def summary(self):
        i = self.info
        if "src_ip" not in i:
            return "%d bytes, %s" % (len(self.raw), "/".join(n for n, _, _ in self.layers) or "unknown")
        a, b = i["src_ip"], i["dst_ip"]
        if "sport" in i:
            a, b = "%s:%d" % (a, i["sport"]), "%s:%d" % (b, i["dport"])
        tag = i.get("app") or i.get("l4") or "IP"
        extra = " [%s]" % i["flags"] if i.get("flags") else ""
        return "%s %s > %s%s" % (tag, a, b, extra)


def tcp_flag_names(flags):
    names = [n for bit, n in ((TCP_SYN, "SYN"), (TCP_FIN, "FIN"), (TCP_RST, "RST"), (TCP_PSH, "PSH"),
                              (TCP_ACK, "ACK"), (TCP_URG, "URG")) if flags & bit]
    return "+".join(names) or "none"


def parse(raw, linktype=LINKTYPE_ETHERNET):
    """Parse as far as the bytes allow. Never raises on truncated or odd input."""
    p = Packet(raw, linktype)
    raw, n = p.raw, len(raw)
    ethertype, off = None, 0
    if linktype == LINKTYPE_ETHERNET:
        if n < 14:
            return p
        p.add_layer("Ethernet", 0, 14)
        p.add("eth.dst", 0, 6, mac_str(raw[0:6]))
        p.add("eth.src", 6, 12, mac_str(raw[6:12]))
        ethertype = _u16(raw, 12)
        p.add("eth.type", 12, 14, "0x%04X %s" % (ethertype, ETHERTYPES.get(ethertype, "?")))
        off = 14
        if ethertype == ETH_VLAN and n >= 18:
            p.add_layer("802.1Q", 14, 18)
            ethertype = _u16(raw, 16)
            off = 18
    elif linktype == LINKTYPE_NULL:
        if n < 4:
            return p
        family = int.from_bytes(raw[:4], "little")
        if family > 0xFFFF:
            family = int.from_bytes(raw[:4], "big")
        p.add_layer("Loopback", 0, 4)
        off = 4
        ethertype = ETH_IPV4 if family == 2 else ETH_IPV6 if family in (10, 24, 28, 30) else None
    elif linktype in (LINKTYPE_RAW, LINKTYPE_IPV4, LINKTYPE_IPV6):
        if n < 1:
            return p
        ethertype = {4: ETH_IPV4, 6: ETH_IPV6}.get(raw[0] >> 4)
    elif linktype == LINKTYPE_LINUX_SLL:
        if n < 16:
            return p
        p.add_layer("Linux SLL", 0, 16)
        ethertype = _u16(raw, 14)
        off = 16
    else:
        return p

    if ethertype == ETH_IPV4:
        _parse_ipv4(p, off)
    elif ethertype == ETH_IPV6:
        _parse_ipv6(p, off)
    else:
        p.add_layer(ETHERTYPES.get(ethertype, "Payload"), off, n)
    return p


def _parse_ipv4(p, off):
    raw, n = p.raw, len(p.raw)
    if n < off + 20:
        return p.add_layer("Payload", off, n)
    ver, ihl = raw[off] >> 4, raw[off] & 0x0F
    hl = ihl * 4
    if ver != 4 or ihl < 5 or n < off + hl:
        return p.add_layer("Payload", off, n)
    total = _u16(raw, off + 2)
    proto = raw[off + 9]
    p.add_layer("IPv4", off, off + hl)
    p.add("ip.ver_ihl", off, off + 1, "version 4, header %d bytes" % hl)
    p.add("ip.dscp", off + 1, off + 2, "0x%02X" % raw[off + 1])
    p.add("ip.len", off + 2, off + 4, str(total))
    p.add("ip.id", off + 4, off + 6, "0x%04X" % _u16(raw, off + 4))
    frag = _u16(raw, off + 6)
    flags = [name for bit, name in ((0x4000, "DF"), (0x2000, "MF")) if frag & bit]
    p.add("ip.frag", off + 6, off + 8, "%s, offset %d" % ("+".join(flags) or "no flags", frag & 0x1FFF))
    p.add("ip.ttl", off + 8, off + 9, str(raw[off + 8]))
    p.add("ip.proto", off + 9, off + 10, "%d %s" % (proto, IP_PROTOS.get(proto, "?")))
    p.add("ip.checksum", off + 10, off + 12, "0x%04X" % _u16(raw, off + 10))
    p.add("ip.src", off + 12, off + 16, ip_str(raw[off + 12:off + 16]))
    p.add("ip.dst", off + 16, off + 20, ip_str(raw[off + 16:off + 20]))
    if hl > 20:
        p.add("ip.options", off + 20, off + hl, "%d bytes" % (hl - 20))
    whole = hl <= total and off + total <= n
    end = off + total if whole else n
    p.info.update(src_ip=ip_str(raw[off + 12:off + 16]), dst_ip=ip_str(raw[off + 16:off + 20]),
                  ip_version=4, ip_start=off, ip_hlen=hl, ip_proto=proto, l4_complete=whole)
    body = off + hl
    if frag & 0x1FFF:
        p.add_layer("Fragment", body, end)
    elif proto == PROTO_TCP:
        _parse_tcp(p, body, end)
    elif proto == PROTO_UDP:
        _parse_udp(p, body, end)
    else:
        p.add_layer(IP_PROTOS.get(proto, "Payload"), body, end)
    p.add_layer("Padding", end, n)


def _parse_ipv6(p, off):
    raw, n = p.raw, len(p.raw)
    if n < off + 40 or raw[off] >> 4 != 6:
        return p.add_layer("Payload", off, n)
    plen = _u16(raw, off + 4)
    nxt = raw[off + 6]
    src, dst = ip_str(raw[off + 8:off + 24]), ip_str(raw[off + 24:off + 40])
    p.add_layer("IPv6", off, off + 40)
    p.add("ipv6.vtf", off, off + 4, "version 6, flow 0x%05X" % (_u32(raw, off) & 0xFFFFF))
    p.add("ipv6.plen", off + 4, off + 6, str(plen))
    p.add("ipv6.next", off + 6, off + 7, "%d %s" % (nxt, IP_PROTOS.get(nxt, "?")))
    p.add("ipv6.hlim", off + 7, off + 8, str(raw[off + 7]))
    p.add("ipv6.src", off + 8, off + 24, src)
    p.add("ipv6.dst", off + 24, off + 40, dst)
    whole = off + 40 + plen <= n and plen > 0
    end = off + 40 + plen if whole else n
    p.info.update(src_ip=src, dst_ip=dst, ip_version=6, ip_start=off, ip_hlen=40, l4_complete=whole)
    body = off + 40
    # skip the common extension headers
    while nxt in (0, 43, 60) and body + 8 <= end:
        ext = (raw[body + 1] + 1) * 8
        if body + ext > end:
            break
        p.add_layer("IPv6 ext", body, body + ext)
        nxt, body = raw[body], body + ext
    p.info["ip_proto"] = nxt
    if nxt == PROTO_TCP:
        _parse_tcp(p, body, end)
    elif nxt == PROTO_UDP:
        _parse_udp(p, body, end)
    else:
        p.add_layer(IP_PROTOS.get(nxt, "Payload"), body, end)
    p.add_layer("Padding", end, n)


def _parse_tcp(p, off, end):
    raw = p.raw
    if end - off < 20:
        return p.add_layer("Payload", off, end)
    hl = (raw[off + 12] >> 4) * 4
    if hl < 20 or off + hl > end:
        return p.add_layer("Payload", off, end)
    sport, dport, flags = _u16(raw, off), _u16(raw, off + 2), raw[off + 13]
    p.add_layer("TCP", off, off + hl)
    p.add("tcp.sport", off, off + 2, str(sport))
    p.add("tcp.dport", off + 2, off + 4, str(dport))
    p.add("tcp.seq", off + 4, off + 8, str(_u32(raw, off + 4)))
    p.add("tcp.ack", off + 8, off + 12, str(_u32(raw, off + 8)))
    p.add("tcp.offset", off + 12, off + 13, "header %d bytes" % hl)
    p.add("tcp.flags", off + 13, off + 14, "0x%02X %s" % (flags, tcp_flag_names(flags)))
    p.add("tcp.window", off + 14, off + 16, str(_u16(raw, off + 14)))
    p.add("tcp.checksum", off + 16, off + 18, "0x%04X" % _u16(raw, off + 16))
    p.add("tcp.urgent", off + 18, off + 20, str(_u16(raw, off + 18)))
    if hl > 20:
        p.add("tcp.options", off + 20, off + hl, "%d bytes" % (hl - 20))
    p.info.update(l4="TCP", sport=sport, dport=dport, flags=tcp_flag_names(flags),
                  l4_start=off, l4_hlen=hl, l4_end=end)
    body = off + hl
    if body >= end:
        return
    payload = raw[body:end]
    if _looks_like_http(payload):
        _parse_http(p, body, end)
    elif len(payload) >= 3 and 0x14 <= payload[0] <= 0x17 and payload[1] == 0x03 and payload[2] <= 0x04:
        p.info["app"] = "TLS"
        p.add_layer("TLS", body, end)
    else:
        p.add_layer("Payload", body, end)


def _parse_udp(p, off, end):
    raw = p.raw
    if end - off < 8:
        return p.add_layer("Payload", off, end)
    sport, dport = _u16(raw, off), _u16(raw, off + 2)
    p.add_layer("UDP", off, off + 8)
    p.add("udp.sport", off, off + 2, str(sport))
    p.add("udp.dport", off + 2, off + 4, str(dport))
    p.add("udp.len", off + 4, off + 6, str(_u16(raw, off + 4)))
    p.add("udp.checksum", off + 6, off + 8, "0x%04X" % _u16(raw, off + 6))
    p.info.update(l4="UDP", sport=sport, dport=dport, l4_start=off, l4_hlen=8, l4_end=end)
    body = off + 8
    if body >= end:
        return
    if (sport in (53, 5353) or dport in (53, 5353)) and end - body >= 12:
        _parse_dns(p, body, end)
    elif 443 in (sport, dport):
        p.info["app"] = "QUIC"
        p.add_layer("QUIC", body, end)
    else:
        p.add_layer("Payload", body, end)


def _parse_dns(p, off, end):
    raw = p.raw
    flags, qd = _u16(raw, off + 2), _u16(raw, off + 4)
    p.add_layer("DNS", off, end)
    p.info["app"] = "DNS"
    p.add("dns.id", off, off + 2, "0x%04X" % _u16(raw, off))
    p.add("dns.flags", off + 2, off + 4, "0x%04X %s" % (flags, "response" if flags & 0x8000 else "query"))
    p.add("dns.qdcount", off + 4, off + 6, str(qd))
    p.add("dns.ancount", off + 6, off + 8, str(_u16(raw, off + 6)))
    p.add("dns.nscount", off + 8, off + 10, str(_u16(raw, off + 8)))
    p.add("dns.arcount", off + 10, off + 12, str(_u16(raw, off + 10)))
    if qd < 1:
        return
    i, labels = off + 12, []
    while i < end:
        length = raw[i]
        if length == 0:
            i += 1
            break
        if length & 0xC0 or i + 1 + length > end:
            return
        labels.append(raw[i + 1:i + 1 + length].decode("ascii", "replace"))
        i += 1 + length
    else:
        return
    if not labels or i + 4 > end:
        return
    qtype = _u16(raw, i)
    p.add("dns.qname", off + 12, i, ".".join(labels))
    p.add("dns.qtype", i, i + 2, "%d %s" % (qtype, DNS_TYPES.get(qtype, "?")))
    p.add("dns.qclass", i + 2, i + 4, str(_u16(raw, i + 2)))
    p.info["qname"] = ".".join(labels)


def _looks_like_http(payload):
    if payload.startswith(b"HTTP/1."):
        return True
    return any(payload.startswith(m + b" ") for m in HTTP_METHODS)


def _parse_http(p, off, end):
    raw = p.raw
    payload = raw[off:end]
    eol = payload.find(b"\r\n")
    if eol < 0:
        return p.add_layer("Payload", off, end)
    line = payload[:eol]
    p.add_layer("HTTP", off, end)
    p.info["app"] = "HTTP"
    if line.startswith(b"HTTP/1."):
        p.add("http.version", off, off + 8, line[:8].decode("ascii", "replace"))
        if len(line) >= 12 and line[9:12].isdigit():
            p.add("http.status", off + 9, off + 12, line[9:].decode("ascii", "replace"))
    else:
        sp1 = line.find(b" ")
        sp2 = line.rfind(b" ")
        p.add("http.method", off, off + sp1, line[:sp1].decode("ascii", "replace"))
        if sp2 > sp1 + 1:
            p.add("http.path", off + sp1 + 1, off + sp2, line[sp1 + 1:sp2].decode("ascii", "replace"))
            if line[sp2 + 1:].startswith(b"HTTP/"):
                p.add("http.version", off + sp2 + 1, off + eol, line[sp2 + 1:].decode("ascii", "replace"))
    low = payload.lower()
    h = low.find(b"\r\nhost: ")
    if h >= 0:
        start = h + 8
        stop = payload.find(b"\r\n", start)
        if stop > start:
            p.add("http.host", off + start, off + stop, payload[start:stop].decode("ascii", "replace"))


# ------------------------------------------- checksum repair (LIVE captures)

def fix_checksums(raw, pkt):
    """Return a copy of raw with valid IPv4 and TCP/UDP checksums. Captures
    often have blank ones because the network card fills them in later."""
    raw = bytearray(raw)
    i = pkt.info
    if i.get("ip_version") == 4:
        s, hl = i["ip_start"], i["ip_hlen"]
        raw[s + 10:s + 12] = b"\x00\x00"
        raw[s + 10:s + 12] = struct.pack("!H", inet_checksum(raw[s:s + hl]))
    if i.get("l4") in ("TCP", "UDP") and i.get("l4_complete"):
        start, end = i["l4_start"], i["l4_end"]
        pos = start + (16 if i["l4"] == "TCP" else 6)
        raw[pos:pos + 2] = b"\x00\x00"
        s = i["ip_start"]
        if i["ip_version"] == 4:
            src, dst = raw[s + 12:s + 16], raw[s + 16:s + 20]
        else:
            src, dst = raw[s + 8:s + 24], raw[s + 24:s + 40]
        csum = l4_checksum(src, dst, i["ip_proto"], raw[start:end])
        if i["l4"] == "UDP" and csum == 0:
            csum = 0xFFFF
        raw[pos:pos + 2] = struct.pack("!H", csum)
    return raw
