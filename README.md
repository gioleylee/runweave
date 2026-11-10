# RunWeave

Run a small research or analytics workflow as a directed acyclic graph. Each step declares an argument vector, source files, dependencies, and expected outputs. Steps with identical declared inputs can reuse verified artifacts from a local cache.

## Try it

Use Python 3.13. No packages are required.

```sh
python runner.py example/pipeline.json
python runner.py example/pipeline.json
python -m unittest -v
```

The example normalizes a CSV, then aggregates its sales by region. The second run should report both steps as cached. Each step's result points to a directory whose `files/` subdirectory holds the named artifacts. Edit only `example/report.py` to invalidate the report while reusing normalization.

## Cache and execution

- A step receives a copy of its declared project inputs and all outputs from its direct dependencies. Files keep their relative paths. The step runs in a fresh working directory.
- The cache key hashes the argument vector, runtime identity, expected output paths, and input file digests. The special argument `{python}` resolves to the current interpreter.
- The runner verifies each output before publishing an entry with a same-filesystem rename. Readers verify the output digests again on a hit. A failed command leaves no entry for that step.
- Commands are trusted local code. Working-directory isolation does not restrict filesystem or network access. Package versions, external tools, and environment variables can affect results. For reliable caching, declare lockfiles and local configuration as inputs and run in a controlled environment.

The tests cover selective invalidation, corrupted cache detection, dependency cycles, unsafe paths, and failure cleanup.
