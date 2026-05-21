{
  callPackage,
  stdenvNoCC,
  python3,
  vdirsyncer,
  msmtp,
  symlinkJoin,
  playwright-driver,
  cherri,
}:
let
  alphashape = python3.pkgs.callPackage ../crwl-cli/deps/alphashape.nix { };
  patchright = python3.pkgs.callPackage ../crwl-cli/deps/patchright {
    inherit callPackage;
  };
  crawl4ai = python3.pkgs.callPackage ../crwl-cli/crawl4ai.nix {
    inherit
      alphashape
      patchright
      playwright-driver
      symlinkJoin
      ;
  };
in
{
  inherit
    alphashape
    crawl4ai
    patchright
    ;

  biorefs-cli = callPackage ../biorefs-cli { inherit stdenvNoCC; };
  buildbot-pr-check = callPackage ../buildbot-pr-check { };
  calendar-cli = callPackage ../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../context7-cli { };
  crabfit-cli = callPackage ../crabfit-cli { };
  crwl-cli = callPackage ../crwl-cli { inherit crawl4ai; };
  gmaps-cli = callPackage ../gmaps-cli { };
  kmap-cli = callPackage ../kmap-cli { };
  linkwarden-cli = callPackage ../linkwarden-cli { };
  miniflux-cli = callPackage ../miniflux-cli { };
  nmap-cli = callPackage ../nmap-cli { };
  n8n-cli = callPackage ../n8n-cli { };
  pexpect-cli = callPackage ../pexpect-cli { };
  vikunja-cli = callPackage ../vikunja-cli { };
  shortcuts-cli = callPackage ../shortcuts-cli { inherit cherri; };
  weather-cli = callPackage ../weather-cli { };
}
