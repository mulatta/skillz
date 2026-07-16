{
  lib,
  python3Packages,
  pueue,
}:

python3Packages.buildPythonApplication {
  pname = "pymol-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
    pueue
  ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/pymol-cli
  '';

  preCheck = ''
    ruff format --check .
    ruff check .
    mypy pymol_cli tests
  '';

  pythonImportsCheck = [ "pymol_cli" ];

  meta = {
    description = "Control PyMOL XML-RPC sessions and generate structure-view scripts";
    license = lib.licenses.mit;
    mainProgram = "pymol-cli";
    maintainers = [ ];
  };
}
