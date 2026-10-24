# How it works

[← README](README.en.md) · [Русский](how-it-works.md) · **English**

Five steps, each can be run separately.

## Inventory

A walk over the cloud tree. For every file `catalog.db` gets the name, size,
date, `md5`, `sha256` and its place in the tree — **before** any download
attempt. That is why a record survives even for a file that can no longer be
served.

- The walk is checkpointed: the folder queue lives in the database, so an
  interruption resumes where it stopped. “Start over” is a checkbox in Tools.
- When the walk finishes, a cross-check runs: a file present in the previous
  inventory and missing from the current one gets `vanished_at` and stops
  counting as alive.
- Folders are stored separately from files: the tree is built from them.

## Probe

An availability check without downloading. The storage is asked for the
**first and the last byte**: that shows not only “answers / does not answer”
but also “serves the beginning and breaks in the middle”.

| State | Meaning |
|---|---|
| `ok` | serves both bytes |
| `unavailable` | errors out or breaks |
| `gone` | `404` — the file does not exist |
| `api_error`, `unknown` | could not be determined |

The result lives 12 hours (`PROBE_TTL_HOURS`). After that “available” is a
memory, and the interface marks it as stale.

## Download

The file is written to `<name>.part`, hashed, and only when the hash matches
the inventory is it renamed to its real name. What that buys:

- a broken transfer stays `.part` and resumes from where it stopped;
- a mismatched hash is never passed off as a rescued file;
- if the inventory has no hash, the copy is marked `unverified` — it is on
  disk, but there is nothing to compare it with.

“Keep holed files” (`salvage`) reads in blocks and skips dead ranges: the
result is a file with holes, marked `salvaged`. Part of the content is better
than nothing, but such a file is not counted as verified.

## Loop

Repeats the download until stopped.

- The queue is **rebuilt on every pass**: rescued files drop out by
  themselves, so do files gone from the cloud.
- A file that just failed is set aside for 20 minutes
  (`LOOP_COOLDOWN_MIN`): a sick storage does not heal in a minute.
- A fresh `404` is skipped and re-checked once a day (`GONE_RECHECK_S`):
  that is an API answer, not a broken machine.
- A full disk stops the loop: when free space drops below the reserve
  (`RESERVE`), the download returns `no_space`.

## Archive

Packing what was rescued into 7z. Settings live in the Archive dialog:

- **volume size**: 3.9 GB (Telegram Premium), 1.9 GB (regular), or no split;
- **compression**: store (`-mx0`, fast), normal (`-mx5`), maximum (`-mx9`);
- after packing every volume is verified by `sha256`.

Freeing originals (`released`) is a separate action: files stay in the
archive, local copies are removed.

## Delete from cloud

Three strictness levels:

| Level | What it deletes |
|---|---|
| downloaded | a copy exists, hash matches |
| archived | the file is packed and the archive is verified |
| junk | by file name, even without a copy |

Before starting, the dialog shows how many files will go and how many are
blocked. Deletions are recorded in `cloud_deleted`; the inventory remembers.

## Interface

- **Four buttons** — inventory, loop, archive, delete. The number inside
  answers “how much with this selection”.
- **Lenses** “Now / Was / On disk” change every number at once: what the cloud
  holds, what the inventory had, what you have.
- **Health** — failure reasons reduced to plain words, nodes with failures,
  jobs for the week. Computed from the database, not from the log.
- **Tools** — everything else: previews, probe, autopilot, nodes, registering
  hand-rescued files, mirror sync, log, settings.
- **View** — scale (auto, 90–150%), density, theme, language.

## Data

Everything lives in one folder:

```
files/      mirror of the cloud, identical structure
meta/       previews
archives/   7z volumes
logs/       journal
catalog.db  inventory, probes, history, archives, jobs
```

`catalog.db` is plain SQLite: `resources`, `probe`, `probe_history`, `local`,
`cloud_deleted`, `archives`, `archive_volumes`, `jobs`.
