{
  lib,
  python3Packages,
  patchelf,
  file,
  binutils, # for strings
}:

python3Packages.buildPythonApplication {
  pname = "cuda-check";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 cuda_check.py $out/bin/cuda-check
    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check cuda_check.py
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [
      patchelf
      file
      binutils
    ])
  ];

  meta = {
    description = "Verify CUDA linkage and RPATH in Nix-built binaries";
    license = lib.licenses.mit;
    mainProgram = "cuda-check";
  };
}
