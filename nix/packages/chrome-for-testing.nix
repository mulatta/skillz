# Pre-built Chrome for Testing for macOS, matching nixpkgs Chromium.
# nixpkgs Chromium is Linux-only, so fetch Google's official Darwin binary to
# keep paperfetch-cli self-contained on every supported platform.
{
  lib,
  stdenvNoCC,
  fetchzip,
}:
let
  version = "151.0.7922.71";
  dir = "mac-arm64";
in
stdenvNoCC.mkDerivation {
  pname = "chrome-for-testing";
  inherit version;

  src = fetchzip {
    url = "https://storage.googleapis.com/chrome-for-testing-public/${version}/${dir}/chrome-${dir}.zip";
    hash = "sha256-AWw9eArW1d+zdyfJiDFJ8SjQrI/IMcbpEeTRVj9A9AA=";
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
    cp -R "chrome-${dir}/Google Chrome for Testing.app" "$out/Applications/"
    binpath="$out/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$binpath" > "$out/bin/chromium"
    chmod +x "$out/bin/chromium"
    runHook postInstall
  '';

  meta = {
    description = "Chrome for Testing ${version} (prebuilt, macOS)";
    homepage = "https://googlechromelabs.github.io/chrome-for-testing/";
    platforms = [ "aarch64-darwin" ];
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    mainProgram = "chromium";
  };
}
