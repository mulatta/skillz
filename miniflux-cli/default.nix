{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "miniflux-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/miniflux-cli
  '';

  meta = {
    description = "CLI for Miniflux entries, Markdown rendering, and enclosures";
    license = lib.licenses.mit;
    mainProgram = "miniflux-cli";
    maintainers = [ ];
  };
}
