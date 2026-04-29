# Patchright browsers — chromium + headless shell for anti-detection crawling
# The JS driver is no longer built here; the Python wheel bundles its own
# driver that matches the client protocol version.
{
  lib,
  linkFarm,
  callPackage,
  stdenv,
}:
let
  inherit (stdenv.hostPlatform) system;
  chromium = callPackage ./chromium.nix { };
  # aarch64-linux uses old builds CDN where headless is built into chromium
  chromiumHeadlessShell =
    if system == "aarch64-linux" then null else callPackage ./chromium-headless-shell.nix { };

  # Chromium revision from patchright 1.58.2
  chromiumRevision = "1208";
in
{
  browsers = linkFarm "patchright-browsers" (
    {
      "chromium-${chromiumRevision}" = chromium;
    }
    // lib.optionalAttrs (chromiumHeadlessShell != null) {
      "chromium_headless_shell-${chromiumRevision}" = chromiumHeadlessShell;
    }
  );
  inherit chromium chromiumHeadlessShell;
}
