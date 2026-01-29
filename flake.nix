{
  description = "LLM-useful CLI tools and skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];

      imports = [
        inputs.treefmt-nix.flakeModule
      ];

      perSystem =
        {
          pkgs,
          self',
          lib,
          ...
        }:
        {
          checks =
            let
              packages = lib.mapAttrs' (n: lib.nameValuePair "package-${n}") self'.packages;
            in
            packages;

          packages = {
            collect-github-reviews = pkgs.callPackage ./collect-github-reviews { };
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs.nixfmt.enable = true;
            programs.ruff.format = true;
            programs.ruff.check = true;
            settings.global.excludes = [ "collect-github-reviews/__init__.py" ];
            settings.formatter.ruff-check.options = [
              "--ignore"
              "INP001"
            ];
            programs.shellcheck.enable = true;
            programs.shfmt.enable = true;
            programs.mypy.enable = true;
            programs.mypy.directories."collect-github-reviews" = { };
          };
        };
    };
}
