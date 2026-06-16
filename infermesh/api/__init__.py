# SPDX-License-Identifier: Apache-2.0
"""infermesh protocol layer (OpenAI/Anthropic adapters and models).

Lifted from oMLX (https://github.com/jundot/omlx, Apache-2.0). This package
imports zero vendor SDKs. Submodules are imported explicitly by callers (e.g.
``from infermesh.api.adapters import OpenAIAdapter``) to avoid pulling optional
subsystems at package-import time.
"""
