{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "crabfit-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff format --check crabfit_cli.py tests
    ruff check crabfit_cli.py tests
    mypy crabfit_cli.py tests
    python -m unittest discover -s tests
    runHook postCheck
  '';

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/crabfit-cli
  '';

  meta = {
    description = "CLI for creating and managing Crab.fit scheduling events";
    license = lib.licenses.mit;
    mainProgram = "crabfit-cli";
    platforms = lib.platforms.all;
  };
}
