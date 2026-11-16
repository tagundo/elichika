"""Fixed authenticated panel origins; bind the pair atomically before serving."""
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

from elichika_ios.security import authenticated_handler

PANEL_PORTS = (("admin", 8772), ("tools", 8770))


def bind_panels(modules, token, language="en", experimental_device=False, *, ports=None, management=None):
    """Bind the contract ports, or explicit isolated fixture ports in host tests.

    The runtime never supplies an override. Port zero and fallback allocation
    are forbidden: a changed origin would lose access to Web Storage settings.
    A partial bind failure closes all sockets already owned by this call.
    """
    selected = tuple(port for _, port in PANEL_PORTS) if ports is None else tuple(ports)
    if len(modules) != len(PANEL_PORTS) or len(selected) != len(PANEL_PORTS):
        raise ValueError("Both admin and tools listeners are required")
    if any(type(port) is not int or not 1 <= port <= 65535 for port in selected) or len(set(selected)) != len(selected):
        raise ValueError("Panel ports must be distinct fixed TCP ports; automatic allocation is forbidden")
    servers = []
    try:
        for (name, _), port, module in zip(PANEL_PORTS, selected, modules):
            handler = authenticated_handler(module.Handler, token, language, experimental_device,
                                            management=management if name == "admin" else None)
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError as error:
                detail = error.strerror or str(error)
                raise RuntimeError(f"The {name} panel could not bind 127.0.0.1:{port}: {detail}") from error
            server.daemon_threads = True
            servers.append(server)
        return servers
    except BaseException:
        for server in servers:
            server.server_close()
        raise


def panel_urls(servers, token):
    return ["http://127.0.0.1:%d/?%s" % (server.server_port, urlencode({"session": token})) for server in servers]
