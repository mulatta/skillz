{
  lib,
  python3Packages,
  gh,
}:

python3Packages.buildPythonApplication {
  pname = "style-review";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 style-review.py $out/bin/style-review
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check style-review.py
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [ gh ])
  ];

  meta = {
    description = "Collect GitHub PR data for style analysis and code review";
    license = lib.licenses.mit;
    mainProgram = "style-review";
  };
}
