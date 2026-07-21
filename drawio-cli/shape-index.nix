{
  lib,
  buildNpmPackage,
  drawio,
  gzip,
  python3,
  writeShellApplication,
  expectedIndex ? ./index-builder/expected-index.json,
  updateCandidate ? null,
}:

let
  expectedFlag = lib.optionalString (expectedIndex != null) "--expected ${expectedIndex}";
  updateScript = writeShellApplication {
    name = "drawio-shape-index-update";
    runtimeInputs = [ python3 ];
    text = ''
      if [[ ! -f flake.nix || ! -f drawio-cli/index-builder/expected-index.json ]]; then
        echo "run drawio shape index updater from the skillz repository root" >&2
        exit 2
      fi
      exec python3 ${./index-builder/update-baseline.py} \
        --manifest ${updateCandidate}/share/drawio-cli/index-manifest.json \
        "$@"
    '';
  };
in
buildNpmPackage {
  pname = "drawio-shape-index";
  version = drawio.version;

  src = lib.fileset.toSource {
    root = ./index-builder;
    fileset = lib.fileset.unions [
      ./index-builder/generate-index.js
      ./index-builder/package-lock.json
      ./index-builder/package.json
    ];
  };
  npmDepsHash = "sha256-pvPtuTTY4aftrT/UhwXYqje99dY3mdtoi+6f4IsTqgA=";

  dontNpmBuild = true;
  doInstallCheck = true;

  nativeBuildInputs = [ gzip ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/drawio-cli $out/share/doc/drawio-shape-index
    node generate-index.js \
      --web-root ${drawio.src}/drawio/src/main/webapp \
      --output $TMPDIR/shape-index.json \
      --manifest $TMPDIR/index-manifest.json \
      --drawio-version ${lib.escapeShellArg drawio.version} \
      ${expectedFlag}
    gzip -n -9 -c $TMPDIR/shape-index.json > $out/share/drawio-cli/shape-index.json.gz
    cp $TMPDIR/index-manifest.json $out/share/drawio-cli/index-manifest.json
    cp ${./index-builder/THIRD_PARTY_NOTICES.md} $out/share/doc/drawio-shape-index/THIRD_PARTY_NOTICES.md
    cp ${./licenses/Apache-2.0.txt} $out/share/doc/drawio-shape-index/LICENSE.Apache-2.0
    cp ${../LICENSE} $out/share/doc/drawio-shape-index/LICENSE.MIT

    runHook postInstall
  '';

  installCheckPhase = ''
    runHook preInstallCheck

    node - <<'JS'
    const crypto = require('node:crypto');
    const fs = require('node:fs');
    const zlib = require('node:zlib');
    const directory = process.env.out + '/share/drawio-cli/';
    const compressed = fs.readFileSync(directory + 'shape-index.json.gz');
    const raw = zlib.gunzipSync(compressed);
    const index = JSON.parse(raw.toString('utf8'));
    const manifest = JSON.parse(fs.readFileSync(directory + 'index-manifest.json', 'utf8'));
    if (!manifest.complete) throw new Error('manifest is not complete');
    if (index.entries.length !== manifest.entriesAfterDedup) throw new Error('entry count mismatch');
    if (index.entries.length < 10000) throw new Error('too few entries');
    if (crypto.createHash('sha256').update(raw).digest('hex') !== manifest.indexSha256) {
      throw new Error('index hash mismatch');
    }
    if (fs.existsSync(directory + 'shape-index.json')) throw new Error('raw index was installed');
    for (const query of ['aws lambda', 'kubernetes pod', 'pid valve', 'electrical resistor']) {
      const terms = query.split(/\s+/);
      if (!index.entries.some((entry) => terms.every((term) => entry.tags.includes(term)))) {
        throw new Error('missing canary ' + query);
      }
    }
    JS

    runHook postInstallCheck
  '';

  passthru = lib.optionalAttrs (updateCandidate != null) {
    inherit updateScript;
  };

  meta = {
    description = "Offline draw.io shape search index generated from packaged draw.io source";
    homepage = "https://www.drawio.com/";
    license = with lib.licenses; [
      mit
      asl20
    ];
    platforms = drawio.meta.platforms;
  };
}
