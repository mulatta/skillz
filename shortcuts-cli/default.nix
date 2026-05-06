{
  lib,
  python3Packages,
  cherri,
  makeWrapper,
}:

python3Packages.buildPythonApplication {
  pname = "shortcuts-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  nativeBuildInputs = [ makeWrapper ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/shortcuts-cli
    wrapProgram $out/bin/shortcuts-cli \
      --prefix PATH : ${lib.makeBinPath [ cherri ]}
  '';

  nativeCheckInputs = [
    python3Packages.pytest
    python3Packages.ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff check shortcuts_cli.py tests
    pytest tests
    runHook postCheck
  '';

  meta = {
    description = "Build and run Apple Shortcuts from Cherri on macOS";
    homepage = "https://github.com/Mic92/mics-skills";
    license = lib.licenses.mit;
    mainProgram = "shortcuts-cli";
  };
}
