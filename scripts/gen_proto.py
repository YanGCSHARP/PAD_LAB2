"""Regenerates gRPC Python stubs into libs/common/common/protos (requires grpcio-tools)."""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "libs" / "common"

subprocess.run(
    [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{ROOT}",
        f"--python_out={ROOT}",
        f"--pyi_out={ROOT}",
        f"--grpc_python_out={ROOT}",
        "common/protos/catalog.proto",
    ],
    check=True,
)
print("stubs generated in", ROOT / "common" / "protos")
