{
  lib,
  python3Packages,
  gitMinimal,
  gh,
}:

python3Packages.buildPythonApplication {
  pname = "collect-github-reviews";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 collect_github_reviews.py $out/bin/collect-github-reviews
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check collect_github_reviews.py
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [
      gitMinimal
      gh
    ])
  ];

  meta = {
    description = "Collect GitHub PR review comments by user or repository";
    license = lib.licenses.mit;
    mainProgram = "collect-github-reviews";
  };
}
