{
  self,
  inputs,
  lib,
}:
let
  registry = import ./skills.nix { inherit inputs; };

  mkBaseModule =
    name: def:
    { pkgs, config, ... }:
    let
      packageName = def.package or name;
      hasPackage = packageName != null;
      pkg = if hasPackage then self.packages.${pkgs.stdenv.hostPlatform.system}.${packageName} else null;
      skillDir = def.source or "${pkg}/share/skills/${name}";
    in
    {
      key = "skillz/base/${name}";
      home.packages = lib.optional hasPackage pkg;
      home.file = lib.listToAttrs (
        map (
          dir: lib.nameValuePair "${dir}/${name}" { source = skillDir; }
        ) config.programs.skillz.skillDirs
      );
    };

  mkSkillModule =
    name: def:
    let
      extra = def.extra or (_: { });
    in
    {
      key = "skillz/${name}";
      imports = [
        ./home-manager-common.nix
        (mkBaseModule name def)
        (extra { inherit self inputs; })
      ];
    };
in
builtins.mapAttrs mkSkillModule registry
