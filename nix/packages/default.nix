{
  callPackage,
  python3,
  vdirsyncer,
  msmtp,
  cherri,
}:
let
  patchright = python3.pkgs.callPackage ./patchright.nix { };
  chromeForTesting = callPackage ./chrome-for-testing.nix { };
in
{
  inherit patchright;

  biorefs-cli = callPackage ../../biorefs-cli { };
  calendar-cli = callPackage ../../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../../context7-cli { };
  crabfit-cli = callPackage ../../crabfit-cli { };
  gmaps-cli = callPackage ../../gmaps-cli { };
  kmap-cli = callPackage ../../kmap-cli { };
  linkwarden-cli = callPackage ../../linkwarden-cli { };
  miniflux-cli = callPackage ../../miniflux-cli { };
  paperfetch-cli = callPackage ../../paperfetch-cli { inherit chromeForTesting patchright; };
  nmap-cli = callPackage ../../nmap-cli { };
  n8n-cli = callPackage ../../n8n-cli { };
  pexpect-cli = callPackage ../../pexpect-cli { };
  queue = callPackage ../../queue { };
  zhost-cli = callPackage ../../zhost-cli { };
  shortcuts-cli = callPackage ../../shortcuts-cli { inherit cherri; };
  weather-cli = callPackage ../../weather-cli { };
}
