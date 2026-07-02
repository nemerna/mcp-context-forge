"""Monkey-patch MCP SDK to advertise UI extension support on both sides.

**Client side** (outbound connections to backend MCP servers):
    The upstream MCP SDK hardcodes ``experimental=None`` and omits
    ``extensions``, so backend servers like insights-mcp see no UI
    support and return text-only fallback instead of ``structuredContent``.

**Server side** (inbound connections from Cursor):
    ``Server.get_capabilities()`` doesn't include ``extensions``, so
    Cursor doesn't know the gateway supports the ``io.modelcontextprotocol/ui``
    protocol and won't trigger widget rendering.

This module patches both ``ClientSession.initialize`` and
``Server.get_capabilities`` so the full widget pipeline works end-to-end.

Import this module once at application startup (e.g. in ``main.py``).
"""

import logging
from typing import Any, Dict

from mcp import types
from mcp.client.session import (
    ClientSession,
    SUPPORTED_PROTOCOL_VERSIONS,
    _default_elicitation_callback,
    _default_list_roots_callback,
    _default_sampling_callback,
)
from mcp.server.lowlevel import NotificationOptions, Server

logger = logging.getLogger(__name__)

_UI_CAPABILITY: Dict[str, Dict[str, Any]] = {"io.modelcontextprotocol/ui": {}}


# ---------------------------------------------------------------------------
# Client-side patch: advertise UI in outbound initialize requests
# ---------------------------------------------------------------------------

async def _ui_aware_initialize(self) -> types.InitializeResult:
    """ClientSession.initialize replacement that advertises UI capabilities."""
    sampling = (
        (self._sampling_capabilities or types.SamplingCapability())
        if self._sampling_callback is not _default_sampling_callback
        else None
    )
    elicitation = (
        types.ElicitationCapability(
            form=types.FormElicitationCapability(),
            url=types.UrlElicitationCapability(),
        )
        if self._elicitation_callback is not _default_elicitation_callback
        else None
    )
    roots = (
        types.RootsCapability(listChanged=True)
        if self._list_roots_callback is not _default_list_roots_callback
        else None
    )

    result = await self.send_request(
        types.ClientRequest(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocolVersion=types.LATEST_PROTOCOL_VERSION,
                    capabilities=types.ClientCapabilities(
                        sampling=sampling,
                        elicitation=elicitation,
                        experimental=_UI_CAPABILITY,
                        roots=roots,
                        tasks=self._task_handlers.build_capability(),
                        extensions=_UI_CAPABILITY,
                    ),
                    clientInfo=self._client_info,
                ),
            )
        ),
        types.InitializeResult,
    )

    if result.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
        raise RuntimeError(f"Unsupported protocol version from the server: {result.protocolVersion}")

    self._server_capabilities = result.capabilities

    await self.send_notification(types.ClientNotification(types.InitializedNotification()))

    return result


# ---------------------------------------------------------------------------
# Server-side patch: advertise UI in capabilities sent to Cursor
# ---------------------------------------------------------------------------

_original_get_capabilities = Server.get_capabilities


def _ui_aware_get_capabilities(
    self,
    notification_options: NotificationOptions,
    experimental_capabilities: dict,
) -> types.ServerCapabilities:
    """Server.get_capabilities replacement that includes extensions."""
    caps = _original_get_capabilities(self, notification_options, experimental_capabilities)
    caps.extensions = _UI_CAPABILITY
    return caps


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_applied = False


def apply():
    """Apply both monkey-patches (idempotent)."""
    global _applied
    if _applied:
        return
    _applied = True

    ClientSession.initialize = _ui_aware_initialize
    logger.info("Patched ClientSession.initialize to advertise io.modelcontextprotocol/ui")

    Server.get_capabilities = _ui_aware_get_capabilities
    logger.info("Patched Server.get_capabilities to advertise io.modelcontextprotocol/ui")
