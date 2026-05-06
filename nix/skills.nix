{ ... }:

# Single source of truth for the skill ↔ package mapping.
#
# Fields (all optional):
#   package – package attr name from `self.packages.<system>` to install
#             (default: <name>). The package must carry
#             `share/skills/<name>/`.
#   extra   – additional home-manager module to merge in (only used by the
#             per-skill homeModules variant).
{
  buildbot-pr-check = { };
  calendar-cli = { };
  context7-cli = { };
  crabfit-cli = { };
  crwl-cli = { };
  gmaps-cli = { };
  miniflux-cli = { };
  n8n-cli = { };
  pexpect-cli = { };
}
