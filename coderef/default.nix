{
  lib,
  python3Packages,
  gh,
}:

python3Packages.buildPythonApplication {
  pname = "coderef";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 coderef.py $out/bin/coderef
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check coderef.py
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [ gh ])
  ];

  meta = {
    description = "Collect GitHub PR code changes for semantic search indexing";
    license = lib.licenses.mit;
    mainProgram = "coderef";
  };
}
