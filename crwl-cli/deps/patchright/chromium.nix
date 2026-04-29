# Patchright uses standard Chromium from playwright CDN
# Since revision 1206+, Chromium uses Chrome for Testing CDN
{
  lib,
  stdenv,
  fetchzip,
  autoPatchelfHook,
  makeWrapper,
  patchelf,
  makeFontsConf,
  # Linux dependencies
  alsa-lib,
  at-spi2-atk,
  atk,
  cairo,
  cups,
  dbus,
  expat,
  glib,
  gobject-introspection,
  libGL,
  libgbm,
  libgcc,
  libxkbcommon,
  nspr,
  nss,
  pango,
  pciutils,
  systemdLibs,
  vulkan-loader,
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

  # Patchright 1.58.2 — chromium revision 1208, browserVersion 145.0.7632.6
  browserVersion = "145.0.7632.6";
  revision = "1208";

  # Since revision 1206+, x86_64/darwin use Chrome for Testing CDN.
  # aarch64-linux still uses the old builds CDN.
  chromiumUrl =
    {
      x86_64-linux = "https://cdn.playwright.dev/chrome-for-testing-public/${browserVersion}/linux64/chrome-linux64.zip";
      aarch64-linux = "https://cdn.playwright.dev/builds/chromium/${revision}/chromium-linux-arm64.zip";
      x86_64-darwin = "https://cdn.playwright.dev/chrome-for-testing-public/${browserVersion}/mac-x64/chrome-mac-x64.zip";
      aarch64-darwin = "https://cdn.playwright.dev/chrome-for-testing-public/${browserVersion}/mac-arm64/chrome-mac-arm64.zip";
    }
    .${system} or throwSystem;

  fontconfig_file = makeFontsConf { fontDirectories = [ ]; };

  chromeDir =
    {
      x86_64-linux = "chrome-linux64";
      aarch64-linux = "chrome-linux";
    }
    .${system} or throwSystem;

  chromium-linux = stdenv.mkDerivation {
    pname = "patchright-chromium";
    version = browserVersion;

    src = fetchzip {
      url = chromiumUrl;
      hash =
        {
          x86_64-linux = "sha256-dJSO05xOzlSl/EwOWNQCeuSb+lhUU6NlGBnRu59irnM=";
          aarch64-linux = "sha256-9DFLCPuc9WZjYLzlRW+Df2pb+mViPK3/IOkkUozELsw=";
        }
        .${system} or throwSystem;
    };

    nativeBuildInputs = [
      autoPatchelfHook
      patchelf
      makeWrapper
    ];

    buildInputs = [
      alsa-lib
      at-spi2-atk
      atk
      cairo
      cups
      dbus
      expat
      glib
      gobject-introspection
      libgbm
      libgcc
      libxkbcommon
      nspr
      nss
      pango
      stdenv.cc.cc.lib
      systemdLibs
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
      mkdir -p $out/${chromeDir}
      cp -R . $out/${chromeDir}
      wrapProgram $out/${chromeDir}/chrome \
        --set-default SSL_CERT_FILE /etc/ssl/certs/ca-bundle.crt \
        --set-default FONTCONFIG_FILE ${fontconfig_file}
      runHook postInstall
    '';

    appendRunpaths = lib.makeLibraryPath [
      libGL
      vulkan-loader
      pciutils
    ];

    postFixup = ''
      rm -f "$out/${chromeDir}/libvulkan.so.1"
      ln -s -t "$out/${chromeDir}" "${lib.getLib vulkan-loader}/lib/libvulkan.so.1"
    '';

    meta = {
      description = "Chromium browser for Patchright";
      platforms = [
        "x86_64-linux"
        "aarch64-linux"
      ];
    };
  };

  chromium-darwin = fetchzip {
    url = chromiumUrl;
    stripRoot = false;
    hash =
      {
        x86_64-darwin = "sha256-+jpk7PuOK4bEurrGt3Z60uY50k4YgtlL2DxTwp/wbbg=";
        aarch64-darwin = "sha256-qXdgHeBS5IFIa4hZVmjq0+31v/uDPXHyc4aH7Wn2E7E=";
      }
      .${system} or throwSystem;
  };
in
{
  x86_64-linux = chromium-linux;
  aarch64-linux = chromium-linux;
  x86_64-darwin = chromium-darwin;
  aarch64-darwin = chromium-darwin;
}
.${system} or throwSystem
