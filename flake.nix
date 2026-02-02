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

      flake = {
        skills = ./skills;
      };

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
            context7-cli = pkgs.callPackage ./context7-cli { };
            cuda-check = pkgs.callPackage ./cuda-check { };
            style-review = pkgs.callPackage ./style-review { };
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs.nixfmt.enable = true;
            programs.ruff.format = true;
            programs.ruff.check = true;
            settings.global.excludes = [ ];
            settings.formatter.ruff-check.options = [
              "--ignore"
              "INP001,EXE001,C901,PLR0912,PLW2901"
            ];
            programs.shellcheck.enable = true;
            programs.shfmt.enable = true;
            programs.mypy.enable = true;
            programs.mypy.directories."context7-cli" = { };
            programs.mypy.directories."cuda-check" = { };
            programs.mypy.directories."style-review" = { };
          };
        };
    };
}
