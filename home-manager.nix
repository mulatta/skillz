{ inputs }:
{
  lib,
  config,
  ...
}:
let
  cfg = config.programs.skillz;

  # Skills that have a matching CLI package
  cliSkills = [
    "context7-cli"
    "crwl-cli"
    "pexpect-cli"
  ];

  # External skill sources (no CLI package, just skill definitions)
  externalSkills = {
    scientific = "${inputs.scientific-skills}/scientific-skills";
  };

  allSkills = cliSkills ++ builtins.attrNames externalSkills;

  # Resolve skill source path
  skillSource =
    name:
    if builtins.hasAttr name externalSkills then
      externalSkills.${name}
    else
      "${cfg.skillsSrc}/skills/${name}";
in
{
  options.programs.skillz = {
    enable = lib.mkEnableOption "skillz LLM agent tools";

    skills = lib.mkOption {
      type = lib.types.listOf (lib.types.enum allSkills);
      default = cliSkills;
      description = ''
        Which skills to install. CLI skills also install the tool binary.
        External skills (e.g. "scientific") install skill definitions only.
      '';
      example = [
        "context7-cli"
        "pexpect-cli"
        "scientific"
      ];
    };

    package = lib.mkOption {
      type = lib.types.attrsOf lib.types.package;
      description = "Attribute set of skillz packages.";
    };

    skillsSrc = lib.mkOption {
      type = lib.types.path;
      description = "Path to the skillz source tree (typically inputs.skillz).";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = builtins.filter (p: p != null) (
      map (name: if builtins.hasAttr name cfg.package then cfg.package.${name} else null) cfg.skills
    );

    # Symlink skill definitions into ~/.claude/skills/
    home.file = lib.listToAttrs (
      map (name: {
        name = ".claude/skills/${name}";
        value.source = skillSource name;
      }) cfg.skills
    );
  };
}
