"""packets.py: build -> parse round trips, checksums, and odd input."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import packets  # noqa: E402
import sources  # noqa: E402
from packets import (PROTO_TCP, PROTO_UDP, TCP_ACK, TCP_PSH, TCP_SYN, build_dns_query, build_dns_response,
                     build_ethernet, build_http_request, build_http_response, build_ipv6, build_tcp,
                     frame_tcp, frame_udp, inet_checksum, l4_sum, ones_sum, parse)

CMAC, GMAC = "3c:22:fb:4a:9e:10", "f4:5c:89:b2:07:c1"

# A 54-byte frame as Wireshark's bytes pane shows it: Ethernet + IPv4 + TCP,
# no payload, an ACK to port 443. Stand-in for the frame in the design
# screenshot; paste the real bytes here to test against that exact packet.
WIRESHARK_54 = bytes.fromhex(
    "f45c89b207c13c22fb4a9e1008004500"
    "00281c464000400619c2c0a801178efa"
    "b40ecc7801bb5a3f21c89b0e44d15010"
    "080078f10000")


def checksums_ok(pkt):
    """IPv4 header and TCP/UDP checksums of a parsed frame both validate."""
    raw, i = pkt.raw, pkt.info
    s = i["ip_start"]
    if ones_sum(raw[s:s + i["ip_hlen"]]) != 0xFFFF:
        return False
    if i.get("l4") in ("TCP", "UDP"):
        return l4_sum(raw[s + 12:s + 16], raw[s + 16:s + 20], i["ip_proto"],
                      raw[i["l4_start"]:i["l4_end"]]) == 0xFFFF
    return True


class ChecksumTest(unittest.TestCase):
    def test_known_ipv4_header(self):
        # the worked example from the Wikipedia "IPv4 header checksum" article
        hdr = bytes.fromhex("450000730000400040110000c0a80001c0a800c7")
        self.assertEqual(inet_checksum(hdr), 0xB861)
        self.assertEqual(ones_sum(hdr[:10] + b"\xb8\x61" + hdr[12:]), 0xFFFF)

    def test_odd_length_is_padded(self):
        self.assertEqual(ones_sum(b"\x01"), 0x0100)
        self.assertEqual(ones_sum(b""), 0)

    def test_every_synth_kind_validates(self):
        syn, rng = sources.SynthSource(), random.Random(3)
        for _, kind, layers in sources.SYNTH_KINDS:
            for _ in range(200):
                pkt = parse(syn.make(kind, rng))
                self.assertEqual(pkt.layer_names() & layers, layers, kind)
                self.assertTrue(checksums_ok(pkt), kind)

    def test_single_byte_corruption_always_breaks_it(self):
        rng = random.Random(9)
        frame = bytearray(WIRESHARK_54)
        for off in range(14, 34):
            bad = bytearray(frame)
            bad[off] ^= rng.randrange(1, 256)
            self.assertNotEqual(ones_sum(bad[14:34]), 0xFFFF)

    def test_fix_checksums_repairs_blank_checksums(self):
        frame = bytearray(frame_tcp(CMAC, GMAC, "10.0.0.5", "93.184.216.34", 50000, 80, payload=b"hello"))
        frame[24:26] = b"\x00\x00"      # IPv4 header checksum
        frame[50:52] = b"\x00\x00"      # TCP checksum
        self.assertFalse(checksums_ok(parse(frame)))
        fixed = packets.fix_checksums(frame, parse(frame))
        self.assertTrue(checksums_ok(parse(fixed)))


class RoundTripTest(unittest.TestCase):
    def test_wireshark_54_byte_frame(self):
        self.assertEqual(len(WIRESHARK_54), 54)
        pkt = parse(WIRESHARK_54)
        self.assertEqual([name for name, _, _ in pkt.layers], ["Ethernet", "IPv4", "TCP"])
        self.assertEqual(pkt.info["dport"], 443)
        f = pkt.fields["tcp.dport"]
        self.assertEqual((f.start, f.end, f.value), (36, 38, "443"))
        self.assertEqual(WIRESHARK_54[36:38], b"\x01\xbb")
        self.assertEqual(pkt.fields["ip.src"].value, "192.168.1.23")
        self.assertEqual(pkt.fields["ip.dst"].value, "142.250.180.14")
        self.assertEqual(pkt.fields["ip.ttl"].value, "64")
        self.assertEqual(pkt.fields["tcp.flags"].value, "0x10 ACK")
        self.assertTrue(checksums_ok(pkt))

    def test_tcp(self):
        frame = frame_tcp(CMAC, GMAC, "192.168.1.23", "93.184.216.34", 51000, 22, ttl=128, ident=0xBEEF,
                          seq=1000, ack=2000, flags=TCP_PSH | TCP_ACK, window=4096, payload=b"SSH-2.0-x\r\n")
        pkt = parse(frame)
        v = {name: f.value for name, f in pkt.fields.items()}
        self.assertEqual(v["eth.src"], CMAC)
        self.assertEqual(v["eth.dst"], GMAC)
        self.assertEqual(v["eth.type"], "0x0800 IPv4")
        self.assertEqual(v["ip.ttl"], "128")
        self.assertEqual(v["ip.id"], "0xBEEF")
        self.assertEqual(v["ip.proto"], "6 TCP")
        self.assertEqual(v["ip.len"], str(len(frame) - 14))
        self.assertEqual((v["tcp.sport"], v["tcp.dport"]), ("51000", "22"))
        self.assertEqual((v["tcp.seq"], v["tcp.ack"], v["tcp.window"]), ("1000", "2000", "4096"))
        self.assertEqual(v["tcp.flags"], "0x18 PSH+ACK")
        self.assertEqual(pkt.layer_range("Payload"), (54, len(frame)))
        self.assertEqual(frame[pkt.fields["ip.dst"].start:pkt.fields["ip.dst"].end], bytes([93, 184, 216, 34]))
        self.assertTrue(checksums_ok(pkt))

    def test_fields_tile_the_headers(self):
        """Within each header, fields cover every byte exactly once."""
        syn, rng = sources.SynthSource(), random.Random(1)
        for _, kind, _ in sources.SYNTH_KINDS:
            pkt = parse(syn.make(kind, rng))
            for layer in ("Ethernet", "IPv4", "TCP", "UDP"):
                span = pkt.layer_range(layer)
                if span is None:
                    continue
                covered = sorted(i for f in pkt.fields.values() if f.layer == layer for i in range(f.start, f.end))
                self.assertEqual(covered, list(range(*span)), (kind, layer))

    def test_udp_dns(self):
        query = frame_udp(CMAC, GMAC, "192.168.1.23", "8.8.8.8", 53124, 53, build_dns_query(0xABCD, "www.example.com", 28))
        pkt = parse(query)
        v = {name: f.value for name, f in pkt.fields.items()}
        self.assertEqual(v["udp.dport"], "53")
        self.assertEqual(v["udp.len"], str(len(query) - 34))
        self.assertEqual(v["dns.id"], "0xABCD")
        self.assertEqual(v["dns.flags"], "0x0100 query")
        self.assertEqual(v["dns.qname"], "www.example.com")
        self.assertEqual(v["dns.qtype"], "28 AAAA")
        q = pkt.fields["dns.qname"]
        self.assertEqual(query[q.start:q.end], b"\x03www\x07example\x03com\x00")
        self.assertTrue(checksums_ok(pkt))

        resp = parse(frame_udp(GMAC, CMAC, "8.8.8.8", "192.168.1.23", 53, 53124,
                               build_dns_response(0xABCD, "www.example.com", ["93.184.216.34", "1.2.3.4"])))
        self.assertEqual(resp.fields["dns.flags"].value, "0x8180 response")
        self.assertEqual(resp.fields["dns.ancount"].value, "2")
        self.assertEqual(resp.fields["dns.qname"].value, "www.example.com")
        self.assertTrue(checksums_ok(resp))

    def test_http(self):
        req = build_http_request("POST", "/api/v2/accounts", "db.zaibatsu.corp", [("Accept", "*/*")])
        pkt = parse(frame_tcp(CMAC, GMAC, "10.0.0.5", "93.184.216.34", 50000, 80, payload=req))
        raw = pkt.raw
        got = {n: raw[f.start:f.end] for n, f in pkt.fields.items() if n.startswith("http.")}
        self.assertEqual(got, {"http.method": b"POST", "http.path": b"/api/v2/accounts",
                               "http.version": b"HTTP/1.1", "http.host": b"db.zaibatsu.corp"})
        resp = parse(frame_tcp(GMAC, CMAC, "93.184.216.34", "10.0.0.5", 80, 50000,
                               payload=build_http_response(404, "Not Found", b"nope")))
        s = resp.fields["http.status"]
        self.assertEqual(resp.raw[s.start:s.end], b"404")
        self.assertEqual(resp.fields["http.version"].value, "HTTP/1.1")

    def test_ip_and_tcp_options_shift_offsets(self):
        opts = b"\x94\x04\x00\x00"
        pkt = parse(frame_tcp(CMAC, GMAC, "10.0.0.5", "10.0.0.6", 50000, 443, ip_options=opts,
                              flags=TCP_SYN, options=b"\x02\x04\x05\xb4"))
        self.assertEqual(pkt.layer_range("IPv4"), (14, 38))
        self.assertEqual(pkt.layer_range("TCP"), (38, 62))
        self.assertEqual((pkt.fields["ip.options"].start, pkt.fields["ip.options"].end), (34, 38))
        self.assertEqual((pkt.fields["tcp.dport"].start, pkt.fields["tcp.options"].start), (40, 58))
        self.assertEqual(pkt.info["dport"], 443)
        self.assertTrue(checksums_ok(pkt))

    def test_ipv6_tcp(self):
        src, dst = "2001:db8::1", "2001:db8::2"
        seg = build_tcp(src, dst, 50000, 443, flags=TCP_SYN)
        pkt = parse(build_ethernet(GMAC, CMAC, packets.ETH_IPV6, build_ipv6(src, dst, PROTO_TCP, seg)))
        self.assertEqual([n for n, _, _ in pkt.layers], ["Ethernet", "IPv6", "TCP"])
        self.assertEqual(pkt.fields["ipv6.src"].value, src)
        self.assertEqual(pkt.fields["ipv6.next"].value, "6 TCP")
        self.assertEqual(pkt.info["dport"], 443)
        self.assertEqual(l4_sum(src, dst, PROTO_TCP, seg), 0xFFFF)

    def test_other_link_types(self):
        ip = frame_udp(CMAC, GMAC, "10.0.0.5", "10.0.0.6", 5000, 6000, b"hi")[14:]
        raw = parse(ip, packets.LINKTYPE_RAW)
        self.assertEqual(raw.layer_range("IPv4"), (0, 20))
        self.assertEqual(raw.info["dport"], 6000)
        loop = parse(b"\x02\x00\x00\x00" + ip, packets.LINKTYPE_NULL)
        self.assertEqual(loop.layer_range("IPv4"), (4, 24))
        self.assertNotIn("eth.dst", loop.fields)


class RobustnessTest(unittest.TestCase):
    def test_every_truncation_parses(self):
        syn, rng = sources.SynthSource(), random.Random(2)
        for _, kind, _ in sources.SYNTH_KINDS:
            frame = syn.make(kind, rng)
            for cut in range(len(frame) + 1):
                pkt = parse(frame[:cut])
                for f in pkt.fields.values():
                    self.assertLessEqual(f.end, cut)
                for _, start, end in pkt.layers:
                    self.assertTrue(0 <= start < end <= cut)

    def test_garbage_parses(self):
        rng = random.Random(4)
        for _ in range(3000):
            blob = bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 120)))
            for linktype in (0, 1, 101, 113, 999):
                parse(blob, linktype)

    def test_garbage_after_a_valid_ethernet_ip_prefix(self):
        rng = random.Random(5)
        for _ in range(3000):
            proto = rng.choice([PROTO_TCP, PROTO_UDP])
            port = rng.choice([53, 80, 443, 5353])
            head = bytearray(frame_udp(CMAC, GMAC, "10.0.0.5", "10.0.0.6", port, port, b"")[:34])
            head[23] = proto
            pkt = parse(bytes(head) + bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 80))))
            for f in pkt.fields.values():
                self.assertLessEqual(f.end, len(pkt.raw))


if __name__ == "__main__":
    unittest.main()
