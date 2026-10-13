# Video Vault

Password-protect your videos and play them back with a built-in player. **Everything is in one file: `video_vault.py`.**

| You want to… | Run |
|---|---|
| Protect videos (Creator window) | `python video_vault.py` |
| Play a protected file | `python video_vault.py clip.vvault` |
| Make a single Windows program | `python video_vault.py build` |
| Check that everything works | `python video_vault.py selftest` |

On Windows use `py video_vault.py …`. The first run installs the missing packages (`PySide6`, `cryptography`) by itself, so you only need Python 3.10 or newer.

## Quick start

1. Run `python video_vault.py`.
2. Drag one or more videos (or a folder) into the window.
3. Type a password, or press **Generate strong password**, and write it down.
4. Choose the output type and press **Create protected files**.

Output types:

* **Windows program (.exe)**: a standalone program that asks for the password and plays the video. Needs the built `VideoVault.exe` (see below).
* **Protected file (.vvault)**: a small file that any copy of Video Vault can open. Best when you have many videos.

## Building the `.exe`

```
python video_vault.py build
```

This creates `dist\VideoVault.exe` (name it with `--name`, use your own icon with `--icon my.ico`). Run the build on Windows to get a Windows program.

`VideoVault.exe` is both the Creator and the starting point for protected programs: when you create an `.exe`, the Creator copies itself and attaches the encrypted video. A program with a video attached opens the password prompt and the player. Without one, it opens the Creator. No Python is needed to run it.

## Features

**Password protection**
* At least 10 characters; common and weak passwords are refused; strength meter and a generator.
* Confirmation field, and the password is never stored. A key derived from it (scrypt) protects the video, and the original file name is encrypted too.
* Change the password of an existing file later (*Change password of existing file…*). Only a 4 KB header is rewritten, so it is instant even for large videos.
* Limited attempts in the player: 5 tries, then a lockout of 30 s, 60 s, 2 min and so on (up to 1 hour), remembered between launches.

**Player**
* Play/pause, click-to-seek bar, volume, mute, speed, full screen, subtitle track menu.
* Keys: `Space` play/pause, `←/→` seek 5 s (`Shift` for 30 s), `↑/↓` volume, `F` or `F11` full screen, `M` mute, `Esc` leave full screen. Double-click the video for full screen. You can drop a `.vvault` file onto the window.
* Decrypts in memory while playing. No plain video is written to disk, unless the media engine fails and you accept the temporary-file fallback (it is deleted when the player closes).
* Integrity check before playback (can be switched off in the ⚙ menu).

**Creator**
* Drag-and-drop, batch processing, per-file and overall progress bars, original and output sizes.
* Settings: default save folder, English / العربية (with right-to-left layout), log file, verify-after-create, which program to embed.
* Log panel, plus a log file in `%APPDATA%\VideoVault\vault.log`. Passwords are never logged.
* Cancel at any time; unfinished output files are removed.

## Security notes

* Encryption is AES-256-GCM with a random key per file, in 1 MiB blocks. Any change, cut-off or reordering is detected.
* **The attempt limit is a convenience, not a lock.** It slows down someone using your player. A person who copies the file can guess passwords offline with their own tools, so the real protection is a **long, random password**. Use the generator.
* **A forgotten password cannot be recovered.** There is no backdoor.
* Anyone with the file can see its approximate size and that it is a Video Vault file.

## Limitations

* Every protected `.exe` is a full copy of the program (about 85 MB on Linux) plus the video. For many videos, use `.vvault` files and keep one program.
* Only subtitles embedded in the video (for example in `.mkv`) are offered; external `.srt` files are not loaded.
* Unsigned programs built with PyInstaller are sometimes flagged by antivirus or SmartScreen. Code signing avoids that.
* Files made by the old `video2code` script use a different format and cannot be opened.
* Subtitles, sound, full screen and the Arabic layout depend on the machine's media backend; test them once on your own computer.

## What was tested

Tested on Linux (no sound device, no real screen):
* All built-in self-tests (`selftest`) pass from source and from the built program: encryption round trip, seeking, wrong password, tampering, truncation, password change, `.exe`-style output, attempt limiter, English/Arabic strings.
* An offscreen run of the real windows: batch creation, then unlock and play. The video decoded, seeking worked, an embedded subtitle track was found, and the 5-try lockout worked.
* The built program copied itself as a stub and its copy decrypted a video.

Not tested: the Windows build itself, audio output, full-screen mode and the right-to-left layout on a real display. Please try these once before relying on them.