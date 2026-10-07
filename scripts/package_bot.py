"""Package source and an encrypted bootstrap; exclude plaintext secrets/runtime data."""

import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "backups",
    "dist",
    "private",
}


def main() -> None:
    output = ROOT / "dist" / "aera-bot-vps.zip"
    names = (
        subprocess.check_output(
            [
                "git",
                "-c",
                f"safe.directory={ROOT.as_posix()}",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            cwd=ROOT,
        )
        .decode("utf-8")
        .split("\0")
    )
    sources = []
    for name in sorted(set(names)):
        if not name:
            continue
        relative = Path(name)
        if EXCLUDED_PARTS.intersection(relative.parts):
            continue
        if relative.name.startswith(".env") and relative.name != ".env.example":
            continue
        if relative.suffix.lower() in {".db", ".log", ".zip", ".pyc"}:
            continue
        path = ROOT / relative
        if path.is_file() and not path.is_symlink():
            sources.append((path, relative.as_posix()))
    required = {"requirements.lock", "scripts/local_bot.py", "docs/VPS_UPLOAD.md"}
    bootstrap = ROOT / "private" / "bootstrap.enc"
    if bootstrap.is_file():
        sources.append((bootstrap, "private-bootstrap.enc"))
    assert required <= {name for _, name in sources}, "Source package incomplete"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, name in sources:
            if path.suffix in {".sh", ".service"}:
                archive.writestr(name, path.read_bytes().replace(b"\r\n", b"\n"))
            else:
                archive.write(path, name)
    print(f"Source ZIP ready: {output.name}; {len(sources)} files; {output.stat().st_size} bytes")
    print("Private .env, database, logs, virtual environment and backups excluded.")


if __name__ == "__main__":
    main()
