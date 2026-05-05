{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "buildbot-pr-check";
  version = "0.2.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  # Runtime: stdlib only.
  dependencies = [ ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${./skills} $out/share/skills/buildbot-pr-check
  '';

  pythonImportsCheck = [ "buildbot_pr_check" ];

  meta = {
    description = "Inspect Buildbot (buildbot-nix) CI for a PR";
    license = lib.licenses.mit;
    mainProgram = "buildbot-pr-check";
    maintainers = [ ];
  };
}
