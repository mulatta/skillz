{
  lib,
  buildPythonPackage,
  fetchFromGitHub,
  setuptools,
  wheel,
  # dependencies
  aiofiles,
  aiohttp,
  aiosqlite,
  anyio,
  lxml,
  litellm,
  numpy,
  pillow,
  playwright,
  patchright,
  python-dotenv,
  requests,
  beautifulsoup4,
  playwright-stealth,
  xxhash,
  rank-bm25,
  snowballstemmer,
  pydantic,
  pyopenssl,
  psutil,
  pyyaml,
  nltk,
  rich,
  cssselect,
  httpx,
  fake-useragent,
  click,
  chardet,
  brotli,
  humanize,
  lark,
  alphashape,
  shapely,
  # optional deps
  pypdf,
  torch,
  scikit-learn,
  transformers,
  tokenizers,
  sentence-transformers,
  selenium,
  # passthru
  symlinkJoin,
  playwright-driver,
}:

let
  # Combined browsers: playwright (chromium-1200) + patchright (chromium-1208)
  # so both PlaywrightAdapter and UndetectedAdapter find their chromium.
  browsers = symlinkJoin {
    name = "crawl4ai-browsers";
    paths = [
      playwright-driver.browsers
      patchright.browsers
    ];
  };
in
buildPythonPackage (finalAttrs: {
  pname = "crawl4ai";
  version = "0.8.5";
  pyproject = true;

  src = fetchFromGitHub {
    owner = "unclecode";
    repo = "crawl4ai";
    tag = "v${finalAttrs.version}";
    hash = "sha256-y5Nve8e41+wcTlymL6bXxPCwmN8+8/YvHYLGO3x4M+Q=";
  };

  build-system = [
    setuptools
    wheel
  ];

  postPatch = ''
    # Remove directory creation from setup.py that assumes writable HOME.
    sed -i '/# Create the .crawl4ai folder/,/^    (crawl4ai_folder \/ folder).mkdir(exist_ok=True)/d' setup.py
  '';

  dependencies = [
    aiofiles
    aiohttp
    aiosqlite
    anyio
    lxml
    litellm
    numpy
    pillow
    playwright
    patchright
    python-dotenv
    requests
    beautifulsoup4
    playwright-stealth
    xxhash
    rank-bm25
    snowballstemmer
    pydantic
    pyopenssl
    psutil
    pyyaml
    nltk
    rich
    cssselect
    httpx
    fake-useragent
    click
    chardet
    brotli
    humanize
    lark
    alphashape
    shapely
  ];

  optional-dependencies = {
    pdf = [ pypdf ];
    torch = [
      torch
      nltk
      scikit-learn
    ];
    transformer = [
      transformers
      tokenizers
      sentence-transformers
    ];
    cosine = [
      torch
      transformers
      nltk
      sentence-transformers
    ];
    sync = [ selenium ];
  };

  pythonRelaxDeps = [
    "lxml"
    "snowballstemmer"
    "pyOpenSSL"
  ];

  makeWrapperArgs = [
    "--set PLAYWRIGHT_BROWSERS_PATH ${browsers}"
    "--set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD 1"
  ];

  # Tests require network access and browser setup.
  doCheck = false;

  # Skip import check as it tries to create directories in HOME.
  # pythonImportsCheck = [ "crawl4ai" ];

  passthru = {
    inherit browsers;
  };

  meta = {
    description = "Open-source LLM Friendly Web Crawler & Scraper";
    homepage = "https://github.com/unclecode/crawl4ai";
    changelog = "https://github.com/unclecode/crawl4ai/blob/v${finalAttrs.version}/CHANGELOG.md";
    license = lib.licenses.asl20;
    mainProgram = "crwl";
    platforms = lib.platforms.unix;
  };
})
