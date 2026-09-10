"""Real HTTP fixture for readiness checks, independent of external DNS."""

import http.server
import os
import shlex
import socketserver
import subprocess
import sys


class LoopbackHTTPServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves a display-only hostname before listen(). On
        # hosted macOS runners that reverse lookup can outlast readiness.
        # These fixtures need actual HTTP and socket behavior, not external DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def command(port):
    argv = [sys.executable, __file__, str(port)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


if __name__ == "__main__":
    with LoopbackHTTPServer(("127.0.0.1", int(sys.argv[1])), http.server.SimpleHTTPRequestHandler) as server:
        print(f"Serving on {server.server_address}", flush=True)
        server.serve_forever()
