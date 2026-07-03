{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "weather-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/weather-cli
  '';

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff format --check weather_cli tests
    ruff check weather_cli tests
    mypy weather_cli tests
    pytest tests
    runHook postCheck
  '';

  meta = {
    description = "Get Korean weather from Korea Meteorological Administration APIs";
    homepage = "https://github.com/mulatta/skillz";
    license = lib.licenses.mit;
    mainProgram = "weather-cli";
  };
}
