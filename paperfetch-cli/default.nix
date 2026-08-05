{
  lib,
  stdenv,
  python3Packages,
  patchright,
  chromeForTesting,
  xvfb,
  chromium,
  dejavu_fonts,
  liberation_ttf,
  makeFontsConf,
  noto-fonts,
}:

let
  # nixpkgs Chromium is Linux-only; google-chrome (the darwin alternative) is
  # unfree and frequently broken, so on macOS use prebuilt Chrome for Testing.
  defaultChromium =
    if stdenv.hostPlatform.isLinux then lib.getExe chromium else lib.getExe chromeForTesting;
  fontsConf = makeFontsConf {
    fontDirectories = [
      dejavu_fonts
      liberation_ttf
      noto-fonts
    ];
  };
in
python3Packages.buildPythonApplication {
  pname = "paperfetch-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;
  build-system = [ python3Packages.hatchling ];

  dependencies = [
    patchright
    python3Packages.defusedxml
    python3Packages.pyvirtualdisplay
    python3Packages.markdownify
  ];

  # Bundle a default Chromium (stock on Linux, prebuilt CfT on macOS) so the CLI
  # is self-contained; `resolve_chromium` still lets --executable / config / PATH
  # override. Xvfb (for `--headful`) is only needed/available on Linux.
  makeWrapperArgs =
    lib.optionals stdenv.hostPlatform.isLinux [
      "--prefix"
      "PATH"
      ":"
      (lib.makeBinPath [ xvfb ])
      "--set"
      "FONTCONFIG_FILE"
      fontsConf
    ]
    ++ [
      "--set"
      "PAPERFETCH_CHROMIUM"
      defaultChromium
    ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff format --check paperfetch_cli tests
    ruff check paperfetch_cli tests
    mypy paperfetch_cli tests
    pytest tests
    runHook postCheck
  '';

  postInstall = ''
    mkdir -p $out/share/doc/paperfetch-cli
    cp README.md $out/share/doc/paperfetch-cli/

    mkdir -p $out/share/skills
    cp -r skills $out/share/skills/paperfetch-cli
  '';

  meta = {
    description = "On-demand academic paper full-text and PDF fetcher";
    license = lib.licenses.mit;
    mainProgram = "paperfetch-cli";
  };
}
