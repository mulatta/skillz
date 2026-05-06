{
  description = "LLM-useful CLI tools and skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    cherri.url = "github:electrikmilk/cherri";
  };

  outputs =
    inputs@{
      self,
      flake-parts,
      nixpkgs,
      ...
    }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      imports = [
        inputs.treefmt-nix.flakeModule
      ];

      flake = {
        homeModules =
          import ./nix/home-modules.nix {
            inherit self inputs;
            lib = nixpkgs.lib;
          }
          // {
            default = import ./nix/home-manager.nix { inherit inputs; };
          };
      };

      perSystem =
        {
          pkgs,
          system,
          self',
          lib,
          ...
        }:
        {
          checks = import ./nix/checks.nix {
            inherit lib;
            packages = self'.packages;
          };

          packages = pkgs.callPackages ./nix/packages.nix {
            cherri = inputs.cherri.packages.${system}.cherri;
          };

          treefmt = import ./nix/treefmt.nix { inherit pkgs; };
        };
    };
}
