# Chrome headless shell for patchright (revision 1208)
# Required for headless=True mode in playwright/patchright >= 1.49
# aarch64-linux uses the old builds CDN where headless is built into chromium,
# so this package only covers Chrome for Testing CDN platforms.
{
  stdenv,
  fetchzip,
  autoPatchelfHook,
  # Linux dependencies (subset of chromium.nix — headless shell needs fewer libs)
  alsa-lib,
  at-spi2-atk,
  atk,
  cairo,
  cups,
  dbus,
  expat,
  glib,
  libgbm,
  libgcc,
  libxkbcommon,
  nspr,
  nss,
  pango,
  libX11,
  libXcomposite,
  libXdamage,
  libXext,
  libXfixes,
  libXrandr,
  libxcb,
}:
let
  inherit (stdenv.hostPlatform) system;

  throwSystem = throw "Unsupported system: ${system}";

  browserVersion = "145.0.7632.6";

  platformDir =
    {
      x86_64-linux = "linux64";
      x86_64-darwin = "mac-x64";
      aarch64-darwin = "mac-arm64";
    }
    .${system} or throwSystem;

  headlessShellUrl = "https://cdn.playwright.dev/chrome-for-testing-public/${browserVersion}/${platformDir}/chrome-headless-shell-${platformDir}.zip";

  shellDir = "chrome-headless-shell-${platformDir}";

  headless-shell-linux = stdenv.mkDerivation {
    pname = "patchright-chromium-headless-shell";
    version = browserVersion;

    src = fetchzip {
      url = headlessShellUrl;
      hash = "sha256-FLzwuPYUJgH/WgLuKqsVJ+KSpKA0iGUh8WpBIyeP6LQ=";
    };

    nativeBuildInputs = [ autoPatchelfHook ];

    buildInputs = [
      alsa-lib
      at-spi2-atk
      atk
      cairo
      cups
      dbus
      expat
      glib
      libgbm
      libgcc
      libxkbcommon
      nspr
      nss
      pango
      stdenv.cc.cc.lib
      libX11
      libXcomposite
      libXdamage
      libXext
      libXfixes
      libXrandr
      libxcb
    ];

    installPhase = ''
      runHook preInstall
      mkdir -p $out/${shellDir}
      cp -R . $out/${shellDir}
      runHook postInstall
    '';

    meta = {
      description = "Chrome headless shell for Patchright";
      platforms = [ "x86_64-linux" ];
    };
  };

  headless-shell-darwin = fetchzip {
    url = headlessShellUrl;
    stripRoot = false;
    hash =
      {
        x86_64-darwin = "sha256-qXeSBKiJDlmTur6oFc+bIxJEiI1ajUh5F8K7EmZcDK0=";
        aarch64-darwin = "sha256-45DjMIu0t7IEYdXOmIqpV/1/MKdEfx/8T7DWagh6Zhc=";
      }
      .${system} or throwSystem;
  };
in
{
  x86_64-linux = headless-shell-linux;
  x86_64-darwin = headless-shell-darwin;
  aarch64-darwin = headless-shell-darwin;
}
.${system} or throwSystem
