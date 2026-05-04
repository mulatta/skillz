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

  checkPhase = ''
    runHook preCheck
    python -m unittest discover -s $src/tests
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
