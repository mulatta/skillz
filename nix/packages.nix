{
  callPackage,
  python3,
  vdirsyncer,
  msmtp,
  symlinkJoin,
  playwright-driver,
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

  buildbot-pr-check = callPackage ../buildbot-pr-check { };
  calendar-cli = callPackage ../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../context7-cli { };
  crabfit-cli = callPackage ../crabfit-cli { };
  crwl-cli = callPackage ../crwl-cli { inherit crawl4ai; };
  gmaps-cli = callPackage ../gmaps-cli { };
  miniflux-cli = callPackage ../miniflux-cli { };
  nmap-cli = callPackage ../nmap-cli { };
  n8n-cli = callPackage ../n8n-cli { };
  pexpect-cli = callPackage ../pexpect-cli { };
  weather-cli = callPackage ../weather-cli { };
}
