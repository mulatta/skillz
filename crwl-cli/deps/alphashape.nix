{
  lib,
  buildPythonPackage,
  fetchFromGitHub,
  setuptools,
  setuptools-scm,
  # dependencies
  click,
  click-log,
  shapely,
  numpy,
  trimesh,
  networkx,
  rtree,
  scipy,
}:
buildPythonPackage (finalAttrs: {
  pname = "alphashape";
  version = "1.3.1";
  pyproject = true;

  src = fetchFromGitHub {
    owner = "bellockk";
    repo = "alphashape";
    tag = "v${finalAttrs.version}";
    hash = "sha256-T2wyU6fpiYRA1+9n//5EtOLhO1fzccQsie+gQj729Vs=";
  };

  build-system = [
    setuptools
    setuptools-scm
  ];

  dependencies = [
    click
    click-log
    shapely
    numpy
    trimesh
    networkx
    rtree
    scipy
  ];

  pythonImportsCheck = [ "alphashape" ];

  # Tests require additional test dependencies not packaged
  doCheck = false;

  meta = {
    description = "Toolbox for generating n-dimensional alpha shapes";
    homepage = "https://github.com/bellockk/alphashape";
    license = lib.licenses.mit;
    platforms = lib.platforms.unix;
  };
})
