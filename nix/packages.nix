{
  callPackage,
  python3,
  vdirsyncer,
  msmtp,
  crawl4ai,
}:
{
  calendar-cli = callPackage ../calendar-cli { inherit python3 vdirsyncer msmtp; };
  context7-cli = callPackage ../context7-cli { };
  crwl-cli = callPackage ../crwl-cli { inherit crawl4ai; };
  n8n-cli = callPackage ../n8n-cli { };
  pexpect-cli = callPackage ../pexpect-cli { };
}
