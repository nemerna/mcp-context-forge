"""Monkey-patch MCP ClientSession.initialize to advertise UI extension support.

When ContextForge proxies tool calls to backend MCP servers like insights-mcp,
the backend checks whether the calling client supports interactive dashboards
via the ``experimental`` field in ``ClientCapabilities``.  The upstream MCP SDK
hardcodes ``experimental=None``, which causes backend servers to return
text-only fallback responses instead of rich UI content.

This module wraps ``ClientSession.initialize`` so that all outbound client
connections advertise ``{"io.modelcontextprotocol/ui": {}}``.

Import this module once at application startup (e.g. in ``main.py``).
"""

import logging

from mcp import types
from mcp.client.session import (
    ClientSession,
    SUPPORTED_PROTOCOL_VERSIONS,
    _default_elicitation_callback,
    _default_list_roots_callback,
    _default_sampling_callback,
)

logger = logging.getLogger(__name__)

_UI_EXPERIMENTAL = {"io.modelcontextprotocol/ui": {}}

_original_initialize = ClientSession.initialize


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
                        experimental=_UI_EXPERIMENTAL,
                        roots=roots,
                        tasks=self._task_handlers.build_capability(),
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


def apply():
    """Apply the monkey-patch (idempotent)."""
    if ClientSession.initialize is not _ui_aware_initialize:
        ClientSession.initialize = _ui_aware_initialize
        logger.info("Patched ClientSession.initialize to advertise io.modelcontextprotocol/ui")
