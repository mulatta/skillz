{
  lib,
  python3Packages,
  gh,
}:

python3Packages.buildPythonApplication {
  pname = "style-review";
  version = "0.1.0";
  pyproject = false;

  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    # Install package
    mkdir -p $out/${python3Packages.python.sitePackages}
    cp -r style_review $out/${python3Packages.python.sitePackages}/

    # Create entry point script
    mkdir -p $out/bin
    cat > $out/bin/style-review << 'EOF'
    #!${python3Packages.python.interpreter}
    import sys
    from style_review.cli import main
    sys.exit(main())
    EOF
    chmod +x $out/bin/style-review

    runHook postInstall
  '';

  nativeCheckInputs = [ python3Packages.ruff ];

  checkPhase = ''
    runHook preCheck
    ruff check style_review/
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [ gh ])
  ];

  meta = {
    description = "Collect GitHub PR data for style analysis and code review";
    license = lib.licenses.mit;
    mainProgram = "style-review";
  };
}
