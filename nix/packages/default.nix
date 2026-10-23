{
  callPackage,
  python3,
  vdirsyncer,
  msmtp,
  cherri,
}:
{
  biorefs-cli = callPackage ../../biorefs-cli { };
  calendar-cli = callPackage ../../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../../context7-cli { };
  crabfit-cli = callPackage ../../crabfit-cli { };
  gmaps-cli = callPackage ../../gmaps-cli { };
  kmap-cli = callPackage ../../kmap-cli { };
  linkwarden-cli = callPackage ../../linkwarden-cli { };
  miniflux-cli = callPackage ../../miniflux-cli { };
  nmap-cli = callPackage ../../nmap-cli { };
  queue = callPackage ../../queue { };
  zhost-cli = callPackage ../../zhost-cli { };
  shortcuts-cli = callPackage ../../shortcuts-cli { inherit cherri; };
  weather-cli = callPackage ../../weather-cli { };
}
