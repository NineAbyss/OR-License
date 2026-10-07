from __future__ import annotations

from pathlib import PurePosixPath

from harbor.agents.installed.base import CliFlag
from harbor.agents.installed.codex import Codex as HarborCodex


class Codex(HarborCodex):

    _REMOTE_CODEX_HOME = PurePosixPath("/home/agent/.codex")

    CLI_FLAGS = [
        *HarborCodex.CLI_FLAGS,
        CliFlag(
            "model_context_window",
            cli="-c",
            type="int",
            format="-c model_context_window={value}",
        ),
        CliFlag(
            "http_only_provider_base_url",
            cli="-c",
            type="str",
            format=(
                "-c model_provider=orle_http "
                "-c model_providers.orle_http.name=ORLE_HTTP "
                "-c model_providers.orle_http.base_url={value} "
                "-c model_providers.orle_http.env_key=OPENAI_API_KEY "
                "-c model_providers.orle_http.wire_api=responses "
                "-c model_providers.orle_http.supports_websockets=false "
                "-c features.responses_websockets=false "
                "-c features.responses_websockets_v2=false"
            ),
        ),
    ]
