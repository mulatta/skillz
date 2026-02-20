{
  lib,
  python3Packages,
  crawl4ai,
}:

python3Packages.buildPythonApplication {
  pname = "crwl-cli";
  version = "0.1.0";
  pyproject = false;
  src = ./.;
  dontBuild = true;

  propagatedBuildInputs = [ crawl4ai ];

  installPhase = ''
    runHook preInstall
    install -Dm755 crawl.py $out/bin/crwl-cli
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];
  checkPhase = ''
    runHook preCheck
    ruff check crawl.py
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--set"
    "PLAYWRIGHT_BROWSERS_PATH"
    "${crawl4ai.passthru.browsers}"
  ];

  meta = {
    description = "Crawl web pages and extract markdown for LLM consumption";
    license = lib.licenses.mit;
    mainProgram = "crwl-cli";
  };
}
