{
  lib,
  stdenvNoCC,
}:

stdenvNoCC.mkDerivation {
  pname = "biorefs-cli";
  version = "0.1.0";

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/doc/biorefs-cli
    cp README.md $out/share/doc/biorefs-cli/README.md
    cp -r references $out/share/doc/biorefs-cli/references

    if [ -d skills ]; then
      mkdir -p $out/share/skills
      cp -r skills $out/share/skills/biorefs-cli
    fi

    runHook postInstall
  '';

  meta = {
    description = "Biomedical reference research CLI design and API reference snapshots";
    homepage = "https://github.com/mulatta/skillz";
    license = lib.licenses.mit;
    maintainers = [ ];
  };
}
