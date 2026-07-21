{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  python3Packages,
  graphviz,
  drawio,
  drawio-headless,
  drawioShapeIndex,
}:

let
  pythonEnv = python3.withPackages (ps: [ ps.defusedxml ]);
in
stdenvNoCC.mkDerivation {
  pname = "drawio-cli";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/libexec/drawio-cli $out/bin $out/share/drawio-cli $out/share/skills $out/share/doc/drawio-cli
    cp -r src/drawio_cli $out/libexec/drawio-cli/
    cp ${drawioShapeIndex}/share/drawio-cli/shape-index.json.gz $out/share/drawio-cli/shape-index.json.gz
    cp ${drawioShapeIndex}/share/drawio-cli/index-manifest.json $out/share/drawio-cli/index-manifest.json
    cp -r skills/drawio-cli $out/share/skills/drawio-cli
    cp README.md THIRD_PARTY_NOTICES.md $out/share/doc/drawio-cli/
    cp ${../LICENSE} $out/share/doc/drawio-cli/LICENSE
    cp -r licenses $out/share/doc/drawio-cli/licenses

    makeWrapper ${pythonEnv}/bin/python3 $out/bin/drawio-cli \
      --add-flags "-m drawio_cli" \
      --set PYTHONPATH "$out/libexec/drawio-cli" \
      --set DRAWIO_CLI_INDEX "$out/share/drawio-cli/shape-index.json.gz" \
      --set DRAWIO_CLI_DOT "${graphviz}/bin/dot" \
      --set DRAWIO_CLI_DRAWIO "${drawio-headless}/bin/drawio"

    runHook postInstall
  '';

  doCheck = true;

  nativeCheckInputs = [
    graphviz
    python3Packages.defusedxml
    python3Packages.mypy
    python3Packages.pytest
    python3Packages.ruff
  ];

  checkPhase = ''
    runHook preCheck
    ruff format --check src tests index-builder/update-baseline.py
    ruff check src tests index-builder/update-baseline.py
    mypy src tests index-builder/update-baseline.py
    PYTHONPATH=$PWD/src:${python3Packages.defusedxml}/${python3.sitePackages} pytest tests
    runHook postCheck
  '';

  meta = {
    description = "Create, validate, lay out, search, and render draw.io diagrams offline";
    license = with lib.licenses; [
      mit
      asl20
    ];
    mainProgram = "drawio-cli";
    platforms = drawio.meta.platforms;
  };
}
