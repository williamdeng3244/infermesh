# SPDX-License-Identifier: Apache-2.0
"""VLLMBackend launch-arg assembly (Milestone 5).

Pure unit test of the sidecar command builder — does NOT require vllm or a GPU.
"""

from infermesh.backends.vllm.vllm_backend import VLLMBackend
from infermesh.core.backend import ModelSpec


def test_build_launch_cmd_basics_and_boolean_flags():
    spec = ModelSpec(
        model_id="qwen-0.5b",
        source="Qwen/Qwen2.5-0.5B-Instruct",
        backend="vllm",
        max_context=4096,
        quantization="awq",
        extra={"vllm_args": {
            "enforce-eager": True,              # store_true -> "--enforce-eager"
            "gpu-memory-utilization": 0.8,      # value -> "--gpu-memory-utilization 0.8"
            "max-model-len": 4096,
            "disable-log-stats": False,         # False -> omitted
            "some-none": None,                  # None  -> omitted
        }},
    )
    cmd = VLLMBackend._build_launch_cmd(spec, 9001)

    assert "vllm.entrypoints.openai.api_server" in cmd
    assert cmd[cmd.index("--model") + 1] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert cmd[cmd.index("--port") + 1] == "9001"
    assert cmd[cmd.index("--served-model-name") + 1] == "qwen-0.5b"
    assert cmd[cmd.index("--max-model-len") + 1] == "4096"
    assert cmd[cmd.index("--quantization") + 1] == "awq"

    # boolean True -> bare flag
    assert "--enforce-eager" in cmd
    # value flag
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.8"
    # False / None -> omitted entirely
    assert "--disable-log-stats" not in cmd
    assert "--some-none" not in cmd


def test_build_launch_cmd_minimal_spec():
    spec = ModelSpec(model_id="m", source="/models/m", backend="vllm")
    cmd = VLLMBackend._build_launch_cmd(spec, 8000)
    assert cmd[cmd.index("--model") + 1] == "/models/m"
    assert "--max-model-len" not in cmd   # no max_context
    assert "--quantization" not in cmd    # no quantization
