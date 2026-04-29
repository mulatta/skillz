{ inputs }:
{
  lib,
  config,
  ...
}:
let
  cfg = config.programs.skillz;

  registry = import ./skills.nix { inherit inputs; };

  allSkills = builtins.attrNames registry;
  defaultSkills = allSkills;

  skillPackage =
    name:
    let
      packageName = registry.${name}.package or name;
    in
    cfg.package.${packageName};

  skillSource = name: "${skillPackage name}/share/skills/${name}";
in
{
  imports = [ ./home-manager-common.nix ];

  options.programs.skillz = {
    enable = lib.mkEnableOption "skillz LLM agent tools";

    skills = lib.mkOption {
      type = lib.types.listOf (lib.types.enum allSkills);
      default = defaultSkills;
      description = ''
        Which skills to install. CLI skills install the tool binary into
        `home.packages` and the corresponding skill definition into every
        directory listed in `programs.skillz.skillDirs`.

        Defaults to all CLI-backed skills.
      '';
      example = [
        "context7-cli"
        "n8n-cli"
        "pexpect-cli"
      ];
    };

    package = lib.mkOption {
      type = lib.types.attrsOf lib.types.package;
      description = "Attribute set of skillz packages.";
    };

    skillsSrc = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Deprecated. Skill definitions now ship inside the packages at
        `$out/share/skills/<name>/`; this option is ignored.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    warnings = lib.optional (
      cfg.skillsSrc != null
    ) "programs.skillz.skillsSrc is deprecated and ignored; skill files now ship inside the packages.";

    home.packages = map skillPackage cfg.skills;

    home.file = lib.listToAttrs (
      lib.concatMap (
        name:
        map (dir: {
          name = "${dir}/${name}";
          value.source = skillSource name;
        }) cfg.skillDirs
      ) cfg.skills
    );
  };
}
