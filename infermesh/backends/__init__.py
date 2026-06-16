# SPDX-License-Identifier: Apache-2.0
"""Hardware/engine backends. ALL vendor-specific code lives under here.

Each backend implements :class:`infermesh.core.backend.InferenceBackend` and is
registered with :class:`infermesh.core.factory.BackendFactory`. Backend modules
import their heavy engine deps lazily so that importing the package does not
require the engine to be installed.
"""
