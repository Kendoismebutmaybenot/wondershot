# Online runtime dependencies

`sources.zip` contains source code and license notices for the native WebRTC libraries built on the player's PC. It contains no game files, credentials, profiles or binaries. `sources.json` pins the archive size, SHA-256 and upstream revisions. Unused tests, documentation assets and the media-only SRTP dependency are omitted; this runtime uses data channels only. Generated Mbed TLS source files are included so building needs no Perl or Python packages.

- [libdatachannel](https://github.com/paullouisageneau/libdatachannel), MPL-2.0, with its pinned libjuice, usrsctp, plog and nlohmann/json dependencies and their notices.
- [Mbed TLS](https://github.com/Mbed-TLS/mbedtls), Apache-2.0 OR GPL-2.0-or-later, with the applicable bundled dependency notices.

The archive preserves the license files shipped with each component. Revisions are recorded in the manifest. The build uses the GNU GPL v3-compatible license options. `nx2/wonder_online.py` verifies the archive before extraction and builds it incrementally with the Builder's compiler. Portable CMake and Ninja are fetched from their official releases with pinned size and SHA-256; their upstream packages include their notices.
