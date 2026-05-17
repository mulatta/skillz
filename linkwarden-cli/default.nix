{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "linkwarden-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
  ];

  preCheck = ''
    ruff format --check .
    ruff check .
    mypy linkwarden_cli tests
  '';

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/linkwarden-cli
  '';

  meta = {
    description = "Agent-oriented CLI for Linkwarden bookmark management";
    license = lib.licenses.mit;
    mainProgram = "linkwarden-cli";
    maintainers = [ ];
  };
}
