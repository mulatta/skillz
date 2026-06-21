# Pre-built Chrome for Testing for macOS, matching the nixpkgs Chromium
# milestone. nixpkgs Chromium is Linux-only (built from source), so on darwin we
# pull Google's official prebuilt CfT binary from the CDN to stay self-contained.
# 149.0.7827.115 is the CfT build for the same 149.0.7827 milestone as nixpkgs
# Chromium 149.0.7827.114 (CfT does not publish that exact patch).
{
  lib,
  stdenvNoCC,
  fetchzip,
}:
let
  version = "149.0.7827.115";
  platforms = {
    "aarch64-darwin" = {
      dir = "mac-arm64";
      hash = "sha256-Pg8tE6BunHoUbZA50yJq3bY4OwH2OHFNmkpA/F76p40=";
    };
    "x86_64-darwin" = {
      dir = "mac-x64";
      hash = "sha256-QhiXGltZ/e7xtKdFbYGZsC+yskzrxn7Ba+zw/Iny0pw=";
    };
  };
  system = stdenvNoCC.hostPlatform.system;
  p = platforms.${system} or (throw "chrome-for-testing: unsupported system ${system}");
in
stdenvNoCC.mkDerivation {
  pname = "chrome-for-testing";
  inherit version;

  src = fetchzip {
    url = "https://storage.googleapis.com/chrome-for-testing-public/${version}/${p.dir}/chrome-${p.dir}.zip";
    hash = p.hash;
    stripRoot = false;
  };

  dontConfigure = true;
  dontBuild = true;

  # Keep the .app intact and expose a bin/chromium that `exec`s the inner binary
  # by its real path. A symlink breaks Chrome's relative framework lookup (dyld
  # resolves @executable_path against the symlink's dir, not the .app), and a
  # space-free bin path avoids spaces in the consumer's wrapper env value.
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/Applications" "$out/bin"
    cp -R "chrome-${p.dir}/Google Chrome for Testing.app" "$out/Applications/"
    binpath="$out/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$binpath" > "$out/bin/chromium"
    chmod +x "$out/bin/chromium"
    runHook postInstall
  '';

  meta = {
    description = "Chrome for Testing ${version} (prebuilt, macOS)";
    homepage = "https://googlechromelabs.github.io/chrome-for-testing/";
    platforms = [
      "aarch64-darwin"
      "x86_64-darwin"
    ];
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    mainProgram = "chromium";
  };
}
