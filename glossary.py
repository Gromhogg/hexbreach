"""Terms and definitions for the menu's TERMS page.

Each entry is (term, definition, real). real is False for words that belong
to this game and not to networking or security: the page marks those, so
nobody walks away thinking "tool slots" are a thing.
"""

REAL, GAME = True, False

TERMS = [
    ("ASCII", "A standard that gives each letter, digit and symbol a number from 0 to 127. "
              "41 is 'A', 61 is 'a', 20 is a space.", REAL),
    ("big-endian", "Most significant byte first. Network protocols use it, so port 443 (0x01BB) is sent as "
                   "01 BB. Also called network byte order.", REAL),
    ("bit", "One binary digit, 0 or 1. Eight bits make a byte.", REAL),
    ("brute force", "Trying every possible value until one works. Slow and noisy, but it always gets there.", REAL),
    ("buffer", "A block of memory that holds data in transit. Writing past its end is a buffer overflow.", REAL),
    ("byte", "Eight bits: a value from 0 to 255, written as two hex digits, 00 to FF.", REAL),
    ("checksum", "A small value computed from data and sent along with it, so the receiver can tell whether the "
                 "data was damaged. IPv4, TCP and UDP all use the Internet checksum.", REAL),
    ("ciphertext", "Data after encryption. With XOR, ciphertext = plaintext XOR key.", REAL),
    ("code page", "A table that gives every byte value a character. Code page 437, from the first IBM PCs, "
                  "has a symbol for all 256, so a dump shown in it has no dots.", REAL),
    ("cryptojacking", "Running a cryptocurrency miner on someone else's machine without permission. "
                      "Easy to spot: the processor runs flat out.", REAL),
    ("daemon", "A program that runs in the background with nobody driving it, such as a web server or a "
               "logging service. Here, a tool that is always on.", REAL),
    ("datagram", "A self-contained message sent without first setting up a connection. UDP sends datagrams.", REAL),
    ("dissector", "The part of a tool like Wireshark that splits a packet into its named fields.", REAL),
    ("DNS", "Domain Name System. Turns a name like example.com into an IP address. Usually UDP port 53.", REAL),
    ("Ethernet", "The usual link layer in wired and Wi-Fi captures. Its 14-byte header holds two MAC addresses "
                 "and an EtherType.", REAL),
    ("EtherType", "Two bytes in the Ethernet header that say what the frame carries: 0800 is IPv4, "
                  "86DD is IPv6, 0806 is ARP.", REAL),
    ("exploit", "Code or input that takes advantage of a particular vulnerability to make a system do something "
                "it should not.", REAL),
    ("field", "A run of bytes in a header with a fixed meaning, such as Time to Live or Destination Port.", REAL),
    ("file carving", "Recovering files from raw bytes by spotting their signatures, with no file system to say "
                     "where they are.", REAL),
    ("file signature", "Fixed bytes at the start of a file that identify its format, e.g. 1F 8B for gzip. "
                       "Also called a magic number.", REAL),
    ("firewall", "A filter that allows or blocks traffic according to rules, such as address and port.", REAL),
    ("foothold", "A machine inside a network that an intruder controls and works from.", REAL),
    ("frame", "One unit of data at the link layer, e.g. an Ethernet frame: a header, then the packet it "
              "carries.", REAL),
    ("header", "The bytes at the front of a frame, packet or segment that describe it: addresses, lengths, "
               "flags. The payload follows.", REAL),
    ("hex dump", "A listing of raw bytes: the offset on the left, the bytes in hex, then the same bytes as "
                 "ASCII.", REAL),
    ("hexadecimal", "Base 16: digits 0-9, then A-F. One hex digit is 4 bits, so two digits make a byte. "
                    "0x in front marks a hex number.", REAL),
    ("hop", "One step from one machine to the next on the way across a network.", REAL),
    ("HTTP", "The protocol of the web. Requests and responses begin with plain ASCII lines, such as "
             "GET /index.html HTTP/1.1.", REAL),
    ("IDS", "Intrusion detection system. Watches traffic or machines for signs of an attack and raises "
            "an alert.", REAL),
    ("IDS evasion", "Changing an attack so an intrusion detection system's rules no longer match it, "
                    "while the target still acts on it.", REAL),
    ("Snort rule", "A line telling an intrusion detection system what to look for in traffic, such as a "
                   "byte pattern, and what to do when it is found. Snort is a well-known IDS.", REAL),
    ("alert log", "What an IDS writes when a rule fires: one entry per alert, with the time, the addresses "
                  "and ports, and what matched. An intruder who gets in tries to take their own entries out "
                  "of it.", REAL),
    ("record", "Data laid out as fields of fixed size, one record after another, so the Nth starts at N "
               "times the record size. Logs, tables and file headers read this way in a hex dump.", REAL),
    ("IHL", "Internet Header Length: the low nibble of an IPv4 packet's first byte, counted in 32-bit words. "
            "5 means 20 bytes.", REAL),
    ("IP address", "The number that identifies a machine on an IP network. IPv4: 4 bytes, written "
                   "192.168.1.42. IPv6: 16 bytes.", REAL),
    ("IPv4", "Internet Protocol version 4. Its header is 20 bytes without options, and in most packets "
             "starts with the byte 45.", REAL),
    ("IPv6", "Internet Protocol version 6. A fixed 40-byte header, 16-byte addresses, no header checksum.", REAL),
    ("key", "The secret value used to encrypt and decrypt. A repeating XOR key is applied to the data over "
            "and over.", REAL),
    ("known-plaintext attack", "Recovering a key because you know part of the original data. "
                               "With XOR: key = ciphertext XOR plaintext.", REAL),
    ("log", "A record a system keeps of what happened on it. Investigators read logs; intruders try to "
            "clear them.", REAL),
    ("MAC address", "The 6-byte hardware address of a network interface, e.g. 3c:22:fb:4a:1d:07. "
                    "The first 3 bytes identify the maker.", REAL),
    ("magic number", "Another name for a file signature.", REAL),
    ("nibble", "Half a byte: 4 bits, one hex digit.", REAL),
    ("node", "Any device on a network. Here, each stop on the map.", REAL),
    ("offset", "A position counted in bytes from the start, beginning at 0. Offset 0x0010 is the 17th byte.", REAL),
    ("one's complement", "A way of adding in which a carry out of the top is added back in at the bottom. "
                         "The Internet checksum is a one's-complement sum.", REAL),
    ("packet", "A unit of data at the network layer: an IP header and its payload. Loosely, any captured "
               "frame.", REAL),
    ("packet loss", "Packets that never reach the other end. Bytes they carried are simply missing until "
                    "they are sent again.", REAL),
    ("packet filter", "Rules that pick which packets to keep or drop, such as 'tcp port 80'.", REAL),
    ("payload", "The data a header carries: whatever follows the header. Also, the code an exploit delivers.", REAL),
    ("pcap, pcapng", "The file formats packet captures are saved in. Wireshark writes pcapng by default.", REAL),
    ("plaintext", "Data before encryption, or after decryption.", REAL),
    ("port", "A 16-bit number that identifies a service on a machine: 80 HTTP, 443 HTTPS, 53 DNS, 22 SSH.", REAL),
    ("port scan", "Probing a machine's ports to see which services answer. Loud: it is the first thing an "
                  "IDS looks for.", REAL),
    ("protocol", "An agreed format and set of rules for exchanging data, such as TCP, DNS or HTTP.", REAL),
    ("proxy", "A machine that relays traffic on your behalf, so the far end sees its address, not yours.", REAL),
    ("pseudo-header", "Fields borrowed from the IP header (the addresses, protocol and length) that the TCP "
                      "and UDP checksums also cover.", REAL),
    ("rate limiting", "Capping how much traffic a source may send or receive per second. Defences use it "
                      "to slow down anything suspicious.", REAL),
    ("segment", "One unit of TCP data: a TCP header and its payload.", REAL),
    ("sequence number", "A TCP header field: where in the stream a segment's first byte goes. The first one "
                        "is picked at random when the connection opens, and it wraps past FFFFFFFF to 0.", REAL),
    ("reassembly", "Putting a stream back together from its segments, in order of sequence number, keeping "
                   "one copy of anything resent. Wireshark's Follow TCP Stream shows the result.", REAL),
    ("retransmission", "A segment sent again because it seemed lost. The receiver already has those bytes, "
                       "so it keeps one copy.", REAL),
    ("snapshot", "A saved copy of a system's state, which it can be restored to later.", REAL),
    ("spoofing", "Forging the source address on traffic so that it appears to come from somewhere else.", REAL),
    ("strings", "A utility that prints the runs of readable text found inside a binary file.", REAL),
    ("subnet", "A range of IP addresses that share a prefix, such as 192.168.1.0/24. Here it also names each "
               "of the five levels of a run, which is the game's use of the word.", REAL),
    ("TCP", "Transmission Control Protocol. Reliable, ordered and connection-based. Its header is 20 bytes "
            "without options.", REAL),
    ("TCP flags", "Bits in the TCP header: SYN opens a connection, ACK acknowledges, FIN closes, RST aborts, "
                  "PSH pushes data through.", REAL),
    ("Time to Live", "TTL. A counter in the IP header that every router lowers by one. At zero the packet "
                     "is dropped.", REAL),
    ("UDP", "User Datagram Protocol. No connection and no guarantees. Its header is always 8 bytes.", REAL),
    ("VPN", "Virtual private network. An encrypted tunnel into another network, which then appears to be "
            "where you are. The far end sees the VPN's address, not yours, but the tunnel is slower.", REAL),
    ("Wireshark", "A free packet analyser. Its bottom pane, 'packet bytes', is the hex dump this game is "
                  "built on.", REAL),
    ("XOR", "Exclusive or. Each output bit is 1 if the two input bits differ. XORing twice with the same key "
            "gives back the original.", REAL),
    ("zero padding", "Bytes of 00 that fill unused space. XOR leaves the key showing through them: it repeats "
                     "there in plain sight. In an XOR node, find that pattern and click it before typing the key.", REAL),
    ("XOR by hand", "Both bytes are shown as bits. Go along them: type 0 where the two bits match, 1 where they "
                    "differ. The game writes each 4 bits as a hex digit.", REAL),

    ("black market", "Where credits buy tools and tool slots. Press B on the map, or wait for the one that opens when an IDS goes down.",
     GAME),
    ("credits", "Money. Earned by solving nodes and spent at the black market.", GAME),
    ("double XOR", "A dump encrypted twice: a block of it with one key, then all of it with another. The first "
                   "key you find uncovers the known bytes of the second. Rare, and never one of a run's first "
                   "three XORs.", GAME),
    ("footprint", "Each traceable tool you carry adds 10% to every TRACE gain. The idea behind it is real: "
                  "what you run on a target can be found there.", GAME),
    ("jack in", "Connecting to a node, which starts its timer. A phrase from cyberpunk fiction.", GAME),
    ("tool slots", "How many tools you can carry at once. Real software has no such limit.", GAME),
    ("TRACE", "A meter from 0 to 100%: how close the defenders are to finding you. It rises on its own, "
              "faster the deeper you go; mistakes and timeouts add more, and at 100% the run ends.", GAME),
    ("traceable", "Said of a tool that acts on the target and so leaves evidence there. See footprint.", GAME),
    ("HUNT (node)", "Click every occurrence of a byte pattern in the dump. In real work: a pattern search.", GAME),
    ("CARVE (node)", "Find the files embedded in a stream by their signatures and say what each is. "
                     "See file carving.", GAME),
    ("DISSECT (node)", "Select the bytes that hold a named header field. See dissector.", GAME),
    ("PAYLOAD (node)", "Pick bytes, alternating row and column, to place target sequences in a buffer. "
                       "They overlap: the last byte of one is the first byte of the next. "
                       "The row and column rule is the game's own.", GAME),
    ("XOR (node)", "Recover the repeating key a dump was XORed with. It has four levels of its own: a run's first "
                   "XOR is level 1, and each one solved moves the next one up. See XOR by hand, zero padding.", GAME),
    ("REASSEMBLE (node)", "A stream arrived in segments, out of order. Drag each one to offset seq minus the "
                          "stream's first seq. Some are from outside the stream; leave those.", GAME),
    ("CHECKSUM (node)", "One header byte is corrupted. Change a byte so the checksum validates again.", GAME),
    ("IDS (node)", "The boss, and one of several games. ALERT LOG: the IDS's log of alerts as fixed-size "
                   "entries; find every copy of your address in SOURCE, clear that entry's ALERT byte, "
                   "then commit the log.", GAME),
]


def search(query):
    """Entries matching a query, best first: terms that start with it, then
    terms that contain it, then entries whose definition mentions it. An empty
    query is everything, in alphabetical order."""
    q = query.strip().lower()
    entries = sorted(TERMS, key=lambda e: e[0].lower())
    if not q:
        return entries
    ranked = []
    for entry in entries:
        term, text = entry[0].lower(), entry[1].lower()
        rank = 0 if term.startswith(q) else 1 if q in term else 2 if q in text else None
        if rank is not None:
            ranked.append((rank, entry))
    return [entry for _, entry in sorted(ranked, key=lambda r: r[0])]
