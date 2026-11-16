The unmodified `clhca.c`, `clhca.h`, `clhca_data.h` and ISC `LICENSE` are copied
from Elichika's reviewed `modtools/webtools/core/resources/cri_hca` snapshot.
That snapshot identifies vgmstream commit
`6802153425adde134e49394fc653455166d7d2f2`; attribution remains in the source.

Compile `clhca.c` as C and link its object with the native audio provider and
`libm`. The provider uses libc allocation and needs no shared C++ runtime.
Its SIFAS HCA key and AWB subkey transformation are the existing Python decoder's
verified defaults. Other ADX encryption is rejected explicitly.

`fixtures/` contains the pre-existing mechanically authored CC0 sine ADX/PCM
fixtures. `audio-fixtures.json` records their independent FFmpeg PCM hashes.
They test codec/transport behavior; they are not game assets or an MV proof.
