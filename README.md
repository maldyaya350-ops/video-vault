<div align="center">

# Video Vault
### The secure fortress for your videos.. Instant playback, zero disk footprint, and zero complex software.

[English Documentation 🇬🇧](./README_EN.md) | [العربية 🇸🇦](#)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Qt6](https://img.shields.io/badge/Qt6-UI%2FRTL-green?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

</div>

---

> *"Most encryption tools treat you like an adversary. They force you to decrypt a gigabyte-sized file entirely onto your hard drive just to watch it, or make you mount complex virtual drives. I thought to myself: why can't we build something that respects our privacy and works smartly? That is how Video Vault was born."*

---


## What Makes Video Vault Different?

If you have ever tried protecting your videos with 7-Zip, GPG, or virtual container tools like VeraCrypt, you always face the same dilemma: either plaintext files left exposed on your hard drive, or unnecessary complexity that frustrates everyday users.

**Video Vault** solves this difficult equation through innovative engineering:

- **Plaintext-Free Encrypted Playback:** The player reads and decrypts only **1 MiB blocks at a time**, streaming them directly into the media player via an in-memory `QIODevice`. Your hard drive remains clean and secure at all times.
- **Self-Contained Executable (`.exe`):** The Creator bundles everything together. It copies its own runtime stub, appends the encrypted payload and trailer, and generates a standalone `.exe` that asks for a password and plays instantly. The recipient needs zero software installed.
- **Real Security Architecture:** A random per-file data key wrapped by a `scrypt`-derived key (64 MiB memory cost). Every single block is authenticated via `AES-256-GCM`, ensuring any tampering, truncation, or reordering is detected immediately.
- **Instant Password Changes:** Because updates apply exclusively to the lightweight 4 KB header, changing a password takes milliseconds—even for massive video files.
- **Full Bilingual & RTL Support:** Designed from the ground up to seamlessly support Arabic and English layouts with native right-to-left alignment.

---

## Quick Start

Because great software should be effortless to use:

1. Download the latest release from the [Releases](../../releases) section.
2. Run the Creator tool, select your video file, and set a password.
3. Enjoy a clean, independent, and secure playback experience.

```bash
git clone [https://github.com/maldyaya350-ops/video-vault.git](https://github.com/maldyaya350-ops/video-vault.git)
cd video-vault
pip install -r requirements.txt
python build_exe.bat
```

# or click on this file build_exe.bat
