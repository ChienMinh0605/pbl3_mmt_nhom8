"""Package the committed source snapshot without local runtime data."""

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def package_source(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        archive = Path(temp) / output.name
        subprocess.run(
            [
                "git", "archive", "--format=zip", "--prefix=wifi-device-sherlock/",
                f"--output={archive}", "HEAD",
            ],
            cwd=root,
            check=True,
        )
        archive.replace(output)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    output = root.parent / "output" / "WiFi_Device_Sherlock_Source.zip"
    package_source(root, output)
    print(output)
