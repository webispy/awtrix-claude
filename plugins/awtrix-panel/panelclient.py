"""Talk to pixelwired. Standard library only, on purpose.

Vendored from the pixelwire repository rather than imported from wherever the daemon happens to be
installed. The wire - one line of JSON over a unix socket - is the compatibility boundary between
the two, so consuming it by copying the forty lines that speak it is the honest shape. It also
means this plugin needs nothing on sys.path but itself.

A hook or a plugin that wants to put something on the panel should not have to install a serial
library to say so - the daemon owns the port, and this is the whole client side of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket

# The daemon's own directory. It used to live under the Claude plugin's state, which was a
# directory named after one client holding the socket every client has to find.
HOME = os.environ.get("PIXELWIRE_HOME") or os.path.expanduser("~/.local/state/pixelwire")

# Who we say we are. The daemon namespaces layers by this, so another client drawing its own `bars`
# does not collide with ours and cannot drop ours. It is a claim rather than a credential - the
# socket's permissions are the boundary - but it is what stops two cooperating programs treading on
# each other, which is the failure that actually happens.
CLIENT = "awtrix-panel"


def socket_path(home: str = HOME) -> str:
    """Beside the state by default, but AF_UNIX caps a path near 104 bytes and a deep state
    directory blows through that. Fall back to a short name keyed on the home, so two homes get
    two sockets and both halves derive the same answer."""
    inside = os.path.join(home, "pixelwired.sock")
    if len(inside.encode()) <= 100:
        return inside
    tag = hashlib.sha1(os.path.abspath(home).encode()).hexdigest()[:8]
    return f"/tmp/pixelwired-{os.getuid()}-{tag}.sock"


SOCKET = socket_path()


def request(payload: dict, sock_path: str = SOCKET, timeout: float = 2.0) -> dict | None:
    """One request, one reply. None when no server is listening - which is not an error, it is
    how a client learns it has to start one."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(sock_path)
    except OSError:
        return None
    try:
        s.sendall((json.dumps({"client": CLIENT, **payload}) + "\n").encode())
        data = s.recv(1 << 16).decode("utf-8", "replace")
        return json.loads(data.splitlines()[0]) if data.strip() else None
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def layer(name: str, frames: list, z: int = 0, fps: float = 0.0,
          clip: list | None = None, **kw) -> dict | None:
    # Tied to this process. The renderer is resident for as long as its layers mean anything, so
    # if it is killed rather than asked to stop, the daemon reaps what it drew instead of leaving a
    # creature walking for a window that closed.
    req = {"op": "layer", "name": name, "frames": frames, "z": z, "fps": fps,
           "expire": {"pid": True}}
    if clip:
        req["clip"] = list(clip)
    return request(req, **kw)


def layers(**kw) -> dict | None:
    """Every layer on the panel, whoever owns it."""
    return request({"op": "layers"}, **kw)


def drop(name: str, **kw) -> dict | None:
    return request({"op": "drop", "name": name}, **kw)


def clear(**kw) -> dict | None:
    return request({"op": "clear"}, **kw)


def stat(**kw) -> dict | None:
    return request({"op": "stat"}, **kw)
