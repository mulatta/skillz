{
  description = "LLM-useful CLI tools and skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    stacks.url = "github:mulatta/stacks.nix";
    scientific-skills.url = "github:K-Dense-AI/claude-scientific-skills";
    scientific-skills.flake = false;
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
        skills = ./skills;
        homeModules =
          import ./nix/home-modules.nix {
            inherit self inputs;
            lib = nixpkgs.lib;
          }
          // {
            default = import ./nix/home-manager.nix { inherit inputs; };
          };
        homeManagerModules.default = import ./nix/home-manager.nix { inherit inputs; };
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
            crawl4ai = inputs.stacks.packages.${system}.crawl4ai;
          };

          treefmt = import ./nix/treefmt.nix { inherit pkgs; };
        };
    };
}
