"""Stage a legacy layout for wiki/build/build.py (engine expects old top-level names)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from secretary.config import core_root, flatten_paths, instance_root, load_config


def _link_dir(link: Path, target: Path) -> None:
    """Create a passthrough link so writes under `link` land in `target`.

    Prefers a real symlink (works on POSIX; on Windows requires Developer
    Mode or admin — see WinError 1314). Falls back to an NTFS directory
    junction on Windows, which any unprivileged user can create and which
    writes through to `target` just like a symlink for local paths.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OSError(
            f"Could not create symlink or junction for {link} -> {target}: "
            f"{result.stderr or result.stdout}"
        )


def _legacy_symlinks(instance: Path, flat: dict[str, str]) -> list[tuple[str, Path]]:
    """Map legacy build.py roots → instance paths."""
    links: list[tuple[str, Path]] = []

    articles = flat.get("wiki.articles")
    if articles:
        # build.py reads SECRETARY/wiki/articulos
        wiki_root = (instance / articles).parent
        links.append(("wiki", wiki_root))

    mail_state = flat.get("mail.state")
    if mail_state:
        links.append(("correo", (instance / mail_state).parent))
    elif (instance / "extractores" / "correo").is_dir():
        links.append(("correo", instance / "extractores" / "correo"))

    for legacy, key in (
        ("whatsapp", "whatsapp.memory"),
        ("reuniones", "meetings.memory"),
        ("job-search", "job_search.inbox"),
    ):
        rel = flat.get(key)
        if rel:
            links.append((legacy, (instance / rel).parent))
        else:
            fallback = instance / "extractores" / legacy
            if fallback.is_dir():
                links.append((legacy, fallback))

    return links


@contextmanager
def staged_build_root() -> Iterator[Path]:
    """Yield a temp directory with symlinks; cleaned up on exit."""
    instance = instance_root()
    cfg = load_config()
    flat = flatten_paths(cfg.get("paths", {}))

    with tempfile.TemporaryDirectory(prefix="secretary-build-") as tmp:
        root = Path(tmp)
        for name, target in _legacy_symlinks(instance, flat):
            link = root / name
            if not link.exists():
                _link_dir(link, target)
        yield root


def run_wiki_build() -> int:
    """Invoke engine build.py against a staged instance layout."""
    build_py = core_root() / "wiki" / "build" / "build.py"
    if not build_py.is_file():
        raise FileNotFoundError(f"No existe {build_py}")

    with staged_build_root() as staged:
        env = os.environ.copy()
        env["SECRETARY_DATA"] = str(staged)
        result = subprocess.run(
            [sys.executable, str(build_py)],
            env=env,
            cwd=str(build_py.parent),
        )
        return result.returncode


def run_wiki_serve(port: int = 8123) -> int:
    """Invoke wiki/serve.py to serve the generated wiki."""
    serve_py = core_root() / "wiki" / "serve.py"
    if not serve_py.is_file():
        raise FileNotFoundError(f"No existe {serve_py}")

    result = subprocess.run(
        [sys.executable, str(serve_py), str(port)],
        cwd=str(serve_py.parent),
    )
    return result.returncode
