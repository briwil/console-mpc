# Installing Console on the MPC Sample

1. Download `Console-MPC.zip` (the **card-latest** release of this repo; version releases are tagged `v…`).
2. Unzip it onto the **root** of the SD card (exFAT or FAT32), so the card has an `autorun` folder and a `Console` folder.
   The card's name doesn't matter. Only one `autorun` folder runs per card, so if the card already has one, remove it first.
3. Put the card in the MPC Sample and switch it on. The first start copies Console to the Sample's internal drive (about a
   minute; the normal MPC screen stays up meanwhile). Then the startup menu appears: **PAD 1 = Console, PAD 2 = MPC**.

Projects and presets are kept on the card in `Console/data`.

## How it works
- The firmware runs `autorun/autorun.sh` from the card (its `autorun.check` file is the checksum the firmware wants).
- That starts `Console/install.sh`, which compares `Console/VERSION` with what is installed. If it's new or missing it
  checks the files (`SHA256SUMS`), needs enough free room, unpacks `payload/console.tgz` (Console's code, the synths and effects, the
  bridge) and `payload/python.tgz` (only when the runtime changed) into `/data/UserData/console`, and then runs `boot.sh`.
  Nothing on the card is executed directly: the card is mounted `noexec`.
- Songs and presets live on the card (`Console/data`); the card is found by its device, not its label.

## Update / skip / remove
- **Update:** replace `autorun` and `Console` on the card with the new ones (keep `Console/data`) and switch on.
- **Skip Console for one start:** an empty file `NOCONSOLE` on the card root.
- **Remove:** an empty file `Console/UNINSTALL`, switch on once (Console comes off the Sample; songs on the card stay).
  Delete that file to install again. Or simply delete the `autorun` folder.
- If anything goes wrong: `Console/install-status.txt` on the card, `console/install.log` on the Sample. A start that never
  finishes is followed by the stock app at the next power-on.

## Developers
Put `authorized_keys` and `ssh_host_ed25519_key` in the card's `autorun` folder to get a key-only SSH server on the USB cable
(192.168.155.1, port 2222). Build the zip yourself with `tools/make-card.sh`; test the installer with `sh card/test/run.sh`.

## Risks
This relies on the firmware's `autorun` feature and its fixed checksum string; a firmware update may change that. Don't
update the Sample's firmware without checking this still works. Use at your own risk.
