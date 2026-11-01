# Limitations

[← README](README.en.md) · [Русский](limitations.md) · **English**

## Not a sync tool

There is no write-back to the cloud. The program only reads and deletes — on
your decision. Keeping two copies in agreement is a different tool.

## It will not bring back what the cloud no longer serves

If the server answers `404`, the file is gone. Its inventory record remains —
name, size, hash, place in the tree — so you can look for a copy elsewhere,
but there is nothing to download.

## The token is bound to the machine

Each system keeps the secret its own way: Windows uses DPAPI (the key is held
by the system and bound to your account), macOS uses the Keychain, Linux uses
libsecret. If a Linux box has no secret service, the fallback is a file with
0600 permissions and no encryption; the interface shows “no encryption”. The
store cannot be moved to another machine.

## 7-Zip is required

Archiving is done by an external 7-Zip: the installer from 7-zip.org on
Windows, the `p7zip-full` package on Linux, `brew install sevenzip` on macOS.
The program does not bundle it; without it inventory, probe and download work
as usual — only the archive step is unavailable.

## Shortcuts differ

`tools/make_shortcut.py` creates a `.lnk` on Windows, a menu entry on Linux
and a `.command` in `~/Applications` on macOS. No administrator rights
anywhere.

## It is not a backup

This is a rescue operation: take what is still served. There is no scheduled
backup, no file versions, no rollback.

## Storage may refuse a large file

Sick machines often serve the first megabytes and break in the middle. The
probe sees such a file as unavailable; the download keeps `.part` and resumes
on the next attempt. If the file is never served whole, it cannot be rescued —
only its inventory record remains.

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
