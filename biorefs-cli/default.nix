{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "biorefs-cli";
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

  checkPhase = ''
    runHook preCheck
    ruff format --check biorefs_cli tests
    ruff check biorefs_cli tests
    mypy biorefs_cli tests
    pytest tests
    runHook postCheck
  '';

  postInstall = ''
    mkdir -p $out/share/doc/biorefs-cli
    cp README.md $out/share/doc/biorefs-cli/README.md
    cp -r references $out/share/doc/biorefs-cli/references

    if [ -d skills ]; then
      mkdir -p $out/share/skills
      cp -r skills $out/share/skills/biorefs-cli
    fi
  '';

  meta = {
    description = "Biomedical reference research CLI scaffold";
    homepage = "https://github.com/mulatta/skillz";
    license = lib.licenses.mit;
    mainProgram = "biorefs-cli";
    maintainers = [ ];
  };
}
