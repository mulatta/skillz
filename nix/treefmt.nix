{ pkgs }:
{
  projectRootFile = "flake.nix";
  programs.nixfmt.enable = true;
  programs.ruff.format = true;
  programs.prettier.enable = true;
  programs.shellcheck.enable = true;
  programs.shfmt.enable = true;

  programs.mypy.enable = true;
  programs.mypy.directories = {
    "calendar-cli" = {
      extraPythonPackages =
        let
          types-icalendar = pkgs.callPackage ../calendar-cli/types-icalendar.nix {
            python = pkgs.python3;
          };
        in
        with pkgs.python3.pkgs;
        [
          icalendar
          pytest
          python-dateutil
          types-icalendar
          types-python-dateutil
        ];
    };
    "context7-cli" = { };
    "crwl-cli" = { };
    "n8n-cli" = {
      extraPythonPackages = with pkgs.python3.pkgs; [
        pytest
      ];
    };
    "pexpect-cli" = {
      extraPythonPackages = with pkgs.python3.pkgs; [
        pexpect
        pytest
      ];
    };
  };

  settings.global.excludes = [
    "*.lock"
    "*.toml"
  ];
}
