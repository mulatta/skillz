{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "nmap-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/nmap-cli
  '';

  nativeCheckInputs = with python3Packages; [
    mypy
    pytestCheckHook
    ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff format --check nmap_cli.py tests
    ruff check nmap_cli.py tests
    mypy nmap_cli.py tests
    pytest tests
    runHook postCheck
  '';

  meta = {
    description = "Use NAVER Cloud Maps APIs from the command line";
    homepage = "https://api.ncloud-docs.com/docs/en/application-maps-overview";
    license = lib.licenses.mit;
    mainProgram = "nmap-cli";
  };
}
