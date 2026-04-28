{ inputs }:

# Single source of truth for the skill ↔ package/source mapping.
#
# Fields (all optional):
#   package – package attr name from `self.packages.<system>` to install
#             (default: <name>). The package must carry
#             `share/skills/<name>/`.
#   source  – external skill directory. Use this for skill definitions that do
#             not have a matching CLI package.
#   extra   – additional home-manager module to merge in (only used by the
#             per-skill homeModules variant).
{
  calendar-cli = { };
  context7-cli = { };
  crwl-cli = { };
  n8n-cli = { };
  pexpect-cli = { };

  scientific = {
    package = null;
    source = "${inputs.scientific-skills}/scientific-skills";
  };
}
