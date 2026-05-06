{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "gmaps-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/gmaps-cli
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check gmaps_cli.py test_gmaps_cli_integration.py
    runHook postCheck
  '';

  meta = {
    description = "Search for places and get directions using Google Maps API";
    homepage = "https://github.com/Mic92/mics-skills";
    license = lib.licenses.mit;
    mainProgram = "gmaps-cli";
  };
}
