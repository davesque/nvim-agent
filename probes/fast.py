# /// script
# dependencies = ["msgpack"]
# ///
"""
Call one method with a timeout to test which requests are served while blocked.
"""
import json, socket, sys, msgpack
s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1])
s.sendall(msgpack.packb([0, 1, sys.argv[2], json.loads(sys.argv[3])]))
u = msgpack.Unpacker(raw=False)
try:
    while True:
        u.feed(s.recv(65536))
        for m in u:
            print(m); sys.exit()
except socket.timeout:
    print("TIMEOUT")
