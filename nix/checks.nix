{
  lib,
  packages,
  treefmtCheck,
}:

lib.mapAttrs' (n: lib.nameValuePair "package-${n}") packages // { treefmt = treefmtCheck; }
