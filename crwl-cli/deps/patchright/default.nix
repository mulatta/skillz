# Pre-built wheel; bundled Node.js replaced with Nix nodejs.
{
  lib,
  buildPythonPackage,
  fetchurl,
  greenlet,
  pyee,
  python,
  nodejs,
  callPackage,
  stdenv,
}:
buildPythonPackage (
  finalAttrs:
  let
    patchright-driver = callPackage ./driver.nix { };

    # py3-none wheels with non-standard platform tags — fetchurl required
    wheels = {
      x86_64-linux = {
        url = "https://files.pythonhosted.org/packages/ea/86/98d8f42d5186b6864144fb25e21da8aa7cffa5b9d1d76752276610b9ea58/patchright-1.58.0-py3-none-manylinux1_x86_64.whl";
        hash = "sha256-gyvuL+SM+dwHuzsPDQXu6SMgPzSM2YsUwsUV7s4yZzQ=";
      };
      aarch64-linux = {
        url = "https://files.pythonhosted.org/packages/b9/b1/7094545c805a31235ef69316ccc910aa5ff5e940c41e85df588ca660f00d/patchright-1.58.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl";
        hash = "sha256-Qxsd+JZ7SRnTJqMSFEXEfxV2m8ahDc66ppkHPrfRJfk=";
      };
      x86_64-darwin = {
        url = "https://files.pythonhosted.org/packages/61/c6/b1d685ccce237e280d8549454a8b5760e58ab5ee88af9ef875fad2282845/patchright-1.58.0-py3-none-macosx_10_13_x86_64.whl";
        hash = "sha256-yq3uxbSBLxLbXiReeLfBvdnGs40sFaWfowR7BOM6PmA=";
      };
      aarch64-darwin = {
        url = "https://files.pythonhosted.org/packages/61/13/e5726d38be9ecf9ed714346433f2536eb6423748836f4a22a6701b992ba0/patchright-1.58.0-py3-none-macosx_11_0_arm64.whl";
        hash = "sha256-r1Z9lNLXNb6PqIxv+UGORjYdgj97KMEMKCPlGUJzlQc=";
      };
    };
    wheel =
      wheels.${stdenv.hostPlatform.system}
        or (throw "patchright ${finalAttrs.version}: no wheel for ${stdenv.hostPlatform.system}");
  in
  {
    pname = "patchright";
    version = "1.58.0";
    format = "wheel";

    src = fetchurl wheel;

    pythonRelaxDeps = [
      "greenlet"
      "pyee"
    ];

    dependencies = [
      greenlet
      pyee
    ];

    postInstall = ''
      SITE=$out/${python.sitePackages}/patchright

      # Replace bundled Node.js with Nix nodejs; keep bundled JS driver as-is.
      chmod -R u+w $SITE/driver
      rm $SITE/driver/node
      ln -s ${lib.getExe nodejs} $SITE/driver/node
    '';

    # Pre-built wheel; tests require browser runtime
    doCheck = false;

    pythonImportsCheck = [ "patchright" ];

    passthru = {
      inherit (patchright-driver) browsers;
    };

    meta = {
      description = "Undetected Python version of Playwright";
      homepage = "https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python";
      changelog = "https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/releases";
      license = lib.licenses.asl20;
      platforms = lib.platforms.unix;
    };
  }
)
