{ lib, packages }:

lib.mapAttrs' (n: lib.nameValuePair "package-${n}") packages
