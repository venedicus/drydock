# Limitations

[← README](README.en.md) · [Русский](limitations.md) · **English**

## Not a sync tool

There is no write-back to the cloud. The program only reads and deletes — on
your decision. Keeping two copies in agreement is a different tool.

## It will not bring back what the cloud no longer serves

If the server answers `404`, the file is gone. Its inventory record remains —
name, size, hash, place in the tree — so you can look for a copy elsewhere,
but there is nothing to download.

## Windows only

The keystore is Windows DPAPI: the token is encrypted for the current user and
does not move to another machine. The program does not run on Linux or macOS.

## It is not a backup

This is a rescue operation: take what is still served. There is no scheduled
backup, no file versions, no rollback.

## Storage may refuse a large file

Sick machines often serve the first megabytes and break in the middle. The
probe sees such a file as unavailable; the download keeps `.part` and resumes
on the next attempt. If the file is never served whole, it cannot be rescued —
only its inventory record remains.

## Time estimates are rough

Loop duration is computed from recent download passes. Before any pass exists,
a fallback of 20 seconds per file is used. On real storage the rate varies by
an order of magnitude: from 2 to 23 seconds per file.

## Deletion is irreversible for the program

Drydock has no undo operation for cloud deletion; by default it bypasses the
Yandex.Disk trash to free quota. It deletes only verified files or files
selected manually by the user. Deletion based on a single `unavailable`/504
probe is disabled: availability changes, and that response does not prove the
file is lost forever. A preview always shows what will be removed.

## One instance per database

A second server notices the first and leaves its jobs alone, but two of them
on one database is a bad idea: two walks write one checkpoint, two downloads
write one `.part`.

## Job progress is still Russian

The interface is translated into six languages, but lines like “round 3: saved
12” are built on the server in Russian. That is the next task, not a forgotten
detail.
