{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "vikunja-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ python3Packages.jinja2 ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/vikunja-cli
  '';

  meta = {
    description = "Agent-oriented CLI for Vikunja task management workflows";
    license = lib.licenses.mit;
    mainProgram = "vikunja-cli";
    maintainers = [ ];
  };
}
