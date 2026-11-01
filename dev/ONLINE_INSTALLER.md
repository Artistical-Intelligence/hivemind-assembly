# One download to install HA

For `v0.38.0-beta.1`, download and run **Hivemind_Assembly_0.38.0-beta.1_Install.exe**.
You do not need to download the two `.bin` files manually. No separate Python,
PowerShell script, Node, Java or download manager is required by this installer.

The initial download is approximately 2.23 GB. Setup obtains the existing tested
beta's original installer and data, verifies exact SHA-256 hashes and lengths,
then runs the offline installer. The application itself is unchanged by this
packaging update. The installer is unsigned; its checksum is listed separately
in `ONLINE-SHA256SUMS.txt`.

## Retained files

By default, complete verified files are retained in:

`%LOCALAPPDATA%\Hivemind Assembly\InstallerCache\0.38.0-beta.1`

The small Install.exe, original Setup.exe, both Setup-*.bin files, checksums and
instructions are kept together. They are not removed when installation finishes
or when HA is uninstalled. Keep or copy that entire folder for offline recovery.
Running Install.exe again checks and reuses the saved files, without downloading
valid copies again. Matching offline files beside Install.exe are also accepted
only after verification and are copied rather than moved.

A changed cached file is retained under a `.rejected-...` filename and is never
executed. Only the missing/changed file is downloaded again. Completed downloads
survive failed attempts. An interrupted individual download may restart from its
beginning; byte-range resumption is not promised. Failed downloads or failed child
installation never count as success, and there is no automatic installation retry.

Advanced: `/CACHE="D:\HA Offline\0.38.0-beta.1"` chooses another local cache folder.
Keep this separate from the HA application directory. Linked paths, junctions and
network shares are rejected. No command-line switch can change the pinned download
URLs, expected hashes, or payload executable.

## Offline alternative

The original three-file offline installer stays available on the same beta release:
`Hivemind_Assembly_0.38.0-beta.1_Setup.exe`, `..._Setup-1.bin`, and `..._Setup-2.bin`.
Place all three together and run Setup.exe. This remains useful for downloading
once elsewhere, archiving the release, or installing without internet access.

Back up your existing HA data and close HA before upgrading. The normal per-user
installation is retained; projects, histories, profiles and settings remain in
`%LOCALAPPDATA%\UnifiedWorkbench`, separate from the application and installer cache.

## Verification boundary

The downloader embeds exact release hashes and public HTTPS URLs. A remote manifest
cannot change what it executes. This does not provide publisher code-signing, a
sandbox, or protection against an administrator or equally privileged process that
can alter files during execution. Independent source review and the existing beta's
live-account/remote-device acceptance remain open. Stable publication rules are
unchanged. Compiled fixture checks and actual Windows installer results are attached
to the release when publication succeeds.
