{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "pareto-decide";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 pareto_decide.py $out/bin/pareto-decide
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check pareto_decide.py
    runHook postCheck
  '';

  meta = {
    description = "Multi-criteria Pareto analysis with marginal gain sweet spot detection";
    license = lib.licenses.mit;
    mainProgram = "pareto-decide";
  };
}
