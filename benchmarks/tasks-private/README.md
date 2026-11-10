# Private task set

This directory documents the custody layout only. **Private task contents are
not in this repository.** They are held in external storage under multi-custody
and mounted at `benchmarks/tasks-private/` for a run.

## Layout

A private task has exactly the same shape as a public task
(`benchmarks/tasks-public/<id>/`), plus:

```json
"private": true
```

The loader refuses a `private: true` manifest unless the caller passes
`--allow-private`:

```bash
python3 -m aegis_bench run \
    --tasks-root ../../benchmarks/tasks-private \
    --allow-private \
    --task <private-id> --adapter <spec> --profile aegis-level3 \
    --plugin ../../build/lib/AegisPass.so --out /tmp/private-run
```

## Rules

1. **Never commit a private task.** `.gitignore` excludes everything here
   except this README. CI's hygiene gate also fails if a task manifest under
   this path is tracked.
2. **Never publish a private run.** Reports containing `private: true` rows
   carry a do-not-publish banner; releasing one requires the custody process
   below.
3. **Rotation.** At the end of each quarter, retire 20% of the private set and
   replace it with newly authored tasks. Retired tasks may be published after
   a rotation, but their reference sources are then public: do not reuse them
   for the next quarter.
4. **Custody.** Private task directories are stored in an access-controlled
   store; each maintainer holds a share. A run mounts the set read-only for
   the duration of the run, then unmounts it.
5. **No answers in public reports.** Public reports may state that a private
   set exists, its size and rotation date, but not task ids, hashes, code, or
   per-task results.

## Why not just hide the answers in the public repo?

Because the project's own threat model assumes a white-box adversary who has
the repository. A hidden answer directory committed to the repo is public the
moment the repo is cloned. The private set only works if it is genuinely
outside the repo.
