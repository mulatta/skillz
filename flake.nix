{
  description = "LLM-useful CLI tools and skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    cherri.url = "github:electrikmilk/cherri";
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      treefmt-nix,
      cherri,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      lib = nixpkgs.lib;

      eachSystem =
        f:
        lib.genAttrs systems (
          system:
          f {
            inherit system;
            pkgs = nixpkgs.legacyPackages.${system};
          }
        );

      treefmtEval = eachSystem (
        { pkgs, ... }: treefmt-nix.lib.evalModule pkgs (import ./nix/treefmt.nix { inherit pkgs; })
      );
    in
    {
      packages = eachSystem (
        { pkgs, system, ... }:
        pkgs.callPackages ./nix/packages.nix {
          cherri = cherri.packages.${system}.cherri;
        }
      );

      checks = eachSystem (
        { system, ... }:
        import ./nix/checks.nix {
          inherit lib;
          packages = self.packages.${system};
          treefmtCheck = treefmtEval.${system}.config.build.check self;
        }
      );

      formatter = eachSystem ({ system, ... }: treefmtEval.${system}.config.build.wrapper);

      homeModules = import ./nix/home-modules.nix { inherit self inputs lib; } // {
        default = import ./nix/home-manager.nix { inherit inputs; };
      };
    };
}
