import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from windowkeeper.config import Settings


@dataclass(frozen=True, slots=True)
class Compatibility:
    compatible: bool
    code: str
    detail: str
    observed_version: str | None = None
    observed_sha256: str | None = None


def inspect_codex(settings: Settings) -> Compatibility:
    executable = shutil.which(settings.codex_executable)
    if not executable:
        return Compatibility(
            False, "CODEX_NOT_FOUND", "The configured Codex executable was not found"
        )
    if settings.codex_version == "unverified" or settings.codex_sha256 == "unverified":
        return Compatibility(
            False,
            "CODEX_COMPATIBILITY_UNPINNED",
            "Set the validated Codex version and SHA-256 compatibility tuple",
        )
    try:
        observed_version = subprocess.run(  # noqa: S603
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        observed_sha256 = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    except (OSError, subprocess.SubprocessError) as error:
        return Compatibility(False, "CODEX_INSPECTION_FAILED", type(error).__name__)
    if observed_version != settings.codex_version or observed_sha256 != settings.codex_sha256:
        return Compatibility(
            False,
            "CODEX_COMPATIBILITY_MISMATCH",
            "Observed Codex version or digest does not match the validated tuple",
            observed_version,
            observed_sha256,
        )
    return Compatibility(
        True,
        "CODEX_COMPATIBLE",
        "Codex version and digest match",
        observed_version,
        observed_sha256,
    )
