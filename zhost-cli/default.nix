{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "zhost-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ python3Packages.pymupdf ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
  ];

  preCheck = ''
    ruff format --check .
    ruff check .
    mypy zhost_cli tests
  '';

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/zhost-cli
  '';

  meta = {
    description = "Agent-oriented CLI for a self-hosted Zotero sync server (zhost)";
    license = lib.licenses.mit;
    mainProgram = "zhost-cli";
    maintainers = [ ];
  };
}
