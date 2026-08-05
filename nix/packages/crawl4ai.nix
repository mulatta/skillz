{
  python3,
  playwright-driver,
  patchright,
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
  browsers = playwright-driver.selectBrowsers {
    withFirefox = false;
    withWebkit = false;
    withFfmpeg = false;
  };
in
(python3.pkgs.crawl4ai.override { inherit alphashape patchright; }).overridePythonAttrs (old: {
  # Optional test dependencies pull broken dlinfo into Darwin builds.
  doCheck = (old.doCheck or true) && !python3.pkgs.stdenv.hostPlatform.isDarwin;
  nativeCheckInputs =
    if python3.pkgs.stdenv.hostPlatform.isDarwin then [ ] else old.nativeCheckInputs;
  passthru = (old.passthru or { }) // {
    inherit browsers;
  };
})
