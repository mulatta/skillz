{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "context7-cli";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 context7_cli.py $out/bin/context7-cli
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check context7_cli.py
    runHook postCheck
  '';

  meta = {
    description = "Fetch up-to-date library documentation from Context7";
    homepage = "https://context7.com";
    license = lib.licenses.mit;
    mainProgram = "context7-cli";
  };
}
