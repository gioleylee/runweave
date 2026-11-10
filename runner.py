"""Run an artifact DAG with isolated work directories and verifiable caching."""

import argparse
import hashlib
import json
import ntpath
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def names(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must be a list of nonempty strings")
    return value


def safe_paths(value, label):
    paths = names(value, label)
    for path in paths:
        if any(part in ("", ".", "..") or ntpath.isreserved(part) for part in path.split("/")) or any(
            mark in path for mark in ("\\", ":", "\x00")
        ):
            raise ValueError(f"{label}: expected a relative slash-separated path: {path!r}")
    if len(paths) != len({path.casefold() for path in paths}):
        raise ValueError(f"{label}: duplicate paths")
    return tuple(paths)


@dataclass(frozen=True)
class Step:
    name: str
    deps: tuple
    inputs: tuple
    outputs: tuple
    command: tuple


def plan(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), dict) or not payload["steps"]:
        raise ValueError("expected a nonempty steps object")
    steps = {}
    for name, spec in payload["steps"].items():
        if not name or not isinstance(spec, dict):
            raise ValueError("each step needs a name and a definition")
        step = Step(name, tuple(names(spec.get("deps", []), "deps")),
                    safe_paths(spec.get("inputs", []), "inputs"),
                    safe_paths(spec.get("outputs", []), "outputs"),
                    tuple(names(spec.get("command"), "command")))
        if not step.command or not step.outputs or {p.casefold() for p in step.inputs} & {p.casefold() for p in step.outputs}:
            raise ValueError(f"{name}: specify a command and outputs distinct from inputs")
        if len(set(step.deps)) != len(step.deps):
            raise ValueError(f"{name}: duplicate dependencies")
        steps[name] = step
    order = []
    visiting, done = set(), set()

    def visit(name):
        if name in done:
            return
        if name in visiting:
            raise ValueError(f"cycle involving {name}")
        if name not in steps:
            raise ValueError(f"unknown dependency {name}")
        visiting.add(name)
        for dep in steps[name].deps:
            visit(dep)
        visiting.remove(name)
        done.add(name)
        order.append(steps[name])

    for name in steps:
        visit(name)
    return order


def regular_file(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError(f"expected a regular file within {root}: {relative}")
    return path


def copy_to(root, relative, source):
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def output_manifest(directory, outputs):
    return {path: digest(regular_file(directory / "files", path)) for path in outputs}


def verify(directory, outputs):
    expected = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if output_manifest(directory, outputs) != expected:
        raise ValueError(f"cache verification failed: {directory}")


def run(project, payload, cache):
    project, cache = Path(project).resolve(), Path(cache).resolve()
    steps = plan(payload)
    cache.mkdir(parents=True, exist_ok=True)
    results = {}
    for step in steps:
        sources = {path: regular_file(project, path) for path in step.inputs}
        occupied = {path.casefold() for path in (*step.inputs, *step.outputs)}
        for dependency in step.deps:
            for path in results[dependency]["outputs"]:
                if path.casefold() in occupied:
                    raise ValueError(f"{step.name}: overlapping input/output path {path}")
                occupied.add(path.casefold())
                sources[path] = regular_file(results[dependency]["directory"] / "files", path)
        argv = [sys.executable if arg == "{python}" else arg for arg in step.command]
        fingerprints = {path: digest(source) for path, source in sources.items()}
        key = hashlib.sha256(json_bytes({
            "version": 1, "runtime": [platform.system(), platform.machine(), sys.version],
            "argv": argv, "outputs": step.outputs, "inputs": fingerprints,
        })).hexdigest()
        directory = cache / key
        hit = directory.is_dir()
        if not hit:
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=cache) as workspace:
                temporary = Path(workspace)
                work = temporary / "work"
                work.mkdir()
                for path, source in sources.items():
                    copy_to(work, path, source)
                    if digest(work / path) != fingerprints[path]:
                        raise ValueError(f"{step.name}: input changed while preparing {path}")
                subprocess.run(argv, cwd=work, check=True, stdout=sys.stderr)
                stage = temporary / "entry"
                for path in step.outputs:
                    copy_to(stage / "files", path, regular_file(work, path))
                manifest = output_manifest(stage, step.outputs)
                (stage / "manifest.json").write_bytes(json_bytes(manifest))
                try:
                    os.rename(stage, directory)
                except OSError:
                    if not directory.is_dir():
                        raise
                    hit = True
        verify(directory, step.outputs)
        results[step.name] = {"key": key, "directory": directory, "outputs": step.outputs, "cached": hit}
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pipeline", type=Path)
    args = parser.parse_args()
    project = args.pipeline.resolve().parent
    try:
        payload = json.loads(args.pipeline.read_text(encoding="utf-8-sig"))
        result = run(project, payload, project / ".runweave-cache")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, default=str))
