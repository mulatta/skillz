{
  callPackage,
  drawio,
  python3,
  vdirsyncer,
  msmtp,
  playwright-driver,
  cherri,
}:
let
  alphashape = python3.pkgs.alphashape.overridePythonAttrs (old: {
    # Face ordering varies with Darwin's geometry stack; imports and 2D behavior
    # remain covered by upstream's passing tests.
    disabledTests =
      (old.disabledTests or [ ])
      ++ python3.pkgs.lib.optionals python3.pkgs.stdenv.hostPlatform.isDarwin [
        "test_3_dimensional_regression"
        "test_3_dimensional_regression_with_dynamic_alpha"
      ];
  });
  patchright = python3.pkgs.callPackage ../crwl-cli/deps/patchright { };
  browsers = playwright-driver.selectBrowsers {
    withFirefox = false;
    withWebkit = false;
    withFfmpeg = false;
  };
  crawl4ai =
    (python3.pkgs.crawl4ai.override { inherit alphashape patchright; }).overridePythonAttrs
      (old: {
        # Optional test dependencies pull broken dlinfo into Darwin builds.
        doCheck = (old.doCheck or true) && !python3.pkgs.stdenv.hostPlatform.isDarwin;
        nativeCheckInputs =
          if python3.pkgs.stdenv.hostPlatform.isDarwin then [ ] else old.nativeCheckInputs;
        passthru = (old.passthru or { }) // {
          inherit browsers;
        };
      });
  drawioShapeIndexCandidate = callPackage ../drawio-cli/shape-index.nix {
    expectedIndex = null;
  };
  drawioShapeIndex = callPackage ../drawio-cli/shape-index.nix {
    updateCandidate = drawioShapeIndexCandidate;
  };
in
{
  inherit crawl4ai patchright;

  biorefs-cli = callPackage ../biorefs-cli { };
  calendar-cli = callPackage ../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../context7-cli { };
  crabfit-cli = callPackage ../crabfit-cli { };
  crwl-cli = callPackage ../crwl-cli { inherit crawl4ai; };
  drawio-shape-index = drawioShapeIndex;
  drawio-cli = callPackage ../drawio-cli { inherit drawioShapeIndex; };
  gmaps-cli = callPackage ../gmaps-cli { };
  kmap-cli = callPackage ../kmap-cli { };
  linkwarden-cli = callPackage ../linkwarden-cli { };
  miniflux-cli = callPackage ../miniflux-cli { };
  paperfetch-cli = callPackage ../paperfetch-cli { inherit patchright; };
  nmap-cli = callPackage ../nmap-cli { };
  n8n-cli = callPackage ../n8n-cli { };
  pexpect-cli = callPackage ../pexpect-cli { };
  pymol-cli = callPackage ../pymol-cli { };
  vikunja-cli = callPackage ../vikunja-cli { };
  zhost-cli = callPackage ../zhost-cli { };
  shortcuts-cli = callPackage ../shortcuts-cli { inherit cherri; };
  weather-cli = callPackage ../weather-cli { };
}
