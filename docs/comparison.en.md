# Comparison

[← README](README.en.md) · [Русский](comparison.md) · **English**

| | Drydock | Sync client | rclone |
|---|---|---|---|
| Remembers files that can no longer be downloaded | yes, writes them to the inventory | no | no |
| Verifies the hash before renaming | yes | yes | yes, `check` |
| Comes back to unavailable files by itself | yes, round after round | no | manually or on a schedule |
| Telegram-sized volumes | yes, 3.9 / 1.9 GB | no | no |
| Deletes from the cloud by strictness level | yes, three levels | no | manually |
| A window instead of a command line | yes | yes | no |
| Survives storage failures | partially: `500`, broken transfer | no | partially |

## Which one to pick

- **Sync client** — when the cloud works and you want the files in two places.
- **rclone** — when you need a script, a schedule and a move to another cloud.
- **Drydock** — when the cloud no longer serves: you need to know what was
  there, take what is still served, and keep a record of the rest.
