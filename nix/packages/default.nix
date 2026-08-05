{
  callPackage,
  python3,
  vdirsyncer,
  msmtp,
  cherri,
}:
let
  patchright = python3.pkgs.callPackage ./patchright.nix { };
  crawl4ai = callPackage ./crawl4ai.nix { inherit patchright; };
  chromeForTesting = callPackage ./chrome-for-testing.nix { };
  drawioShapeIndexCandidate = callPackage ../../drawio-cli/shape-index.nix {
    expectedIndex = null;
  };
  drawioShapeIndex = callPackage ../../drawio-cli/shape-index.nix {
    updateCandidate = drawioShapeIndexCandidate;
  };
in
{
  inherit crawl4ai patchright;

  biorefs-cli = callPackage ../../biorefs-cli { };
  calendar-cli = callPackage ../../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../../context7-cli { };
  crabfit-cli = callPackage ../../crabfit-cli { };
  crwl-cli = callPackage ../../crwl-cli { inherit crawl4ai; };
  drawio-shape-index = drawioShapeIndex;
  drawio-cli = callPackage ../../drawio-cli { inherit drawioShapeIndex; };
  gmaps-cli = callPackage ../../gmaps-cli { };
  kmap-cli = callPackage ../../kmap-cli { };
  linkwarden-cli = callPackage ../../linkwarden-cli { };
  miniflux-cli = callPackage ../../miniflux-cli { };
  paperfetch-cli = callPackage ../../paperfetch-cli { inherit chromeForTesting patchright; };
  nmap-cli = callPackage ../../nmap-cli { };
  n8n-cli = callPackage ../../n8n-cli { };
  pexpect-cli = callPackage ../../pexpect-cli { };
  pymol-cli = callPackage ../../pymol-cli { };
  vikunja-cli = callPackage ../../vikunja-cli { };
  zhost-cli = callPackage ../../zhost-cli { };
  shortcuts-cli = callPackage ../../shortcuts-cli { inherit cherri; };
  weather-cli = callPackage ../../weather-cli { };
}
