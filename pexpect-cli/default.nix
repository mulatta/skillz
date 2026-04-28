{
  lib,
  python3Packages,
  pueue,
}:

python3Packages.buildPythonApplication {
  pname = "pexpect-cli";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ python3Packages.pexpect ];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    python3Packages.pytest-timeout
    pueue
  ];

  # pueue must be in PATH at runtime for session management
  makeWrapperArgs = [ "--prefix PATH : ${pueue}/bin" ];

  postPatch = ''
    patchShebangs bin/
  '';

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${../skills/pexpect-cli} $out/share/skills/pexpect-cli
  '';

  preCheck = ''
    export PATH=$out/bin:${pueue}/bin:$PATH
  '';

  pythonImportsCheck = [ "pexpect_cli" ];

  meta = {
    description = "Persistent pexpect sessions via pueue";
    license = lib.licenses.mit;
    mainProgram = "pexpect-cli";
  };
}
