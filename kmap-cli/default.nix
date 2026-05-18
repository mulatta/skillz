{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "kmap-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/kmap-cli
  '';

  nativeCheckInputs = with python3Packages; [
    mypy
    pytestCheckHook
    ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff check kmap_cli.py tests
    mypy kmap_cli.py tests
    pytest tests
    runHook postCheck
  '';

  meta = {
    description = "Search Korean places and public transit routes with TMAP";
    homepage = "https://transit.tmapmobility.com/";
    license = lib.licenses.mit;
    mainProgram = "kmap-cli";
  };
}
