# homr 0.7.0 (AGPL-3.0): optical music recognition, sheet image -> MusicXML.
# Its ONNX models are pinned here and baked into the package, so it never downloads at run time.
{ python3Packages, fetchPypi, fetchurl, unzip }:
let
  py = python3Packages;
  musicxml = py.buildPythonPackage rec {
    pname = "musicxml";
    version = "1.4";
    pyproject = true;
    src = fetchPypi { inherit pname version; sha256 = "7e410ebd08e1eba72e496d7e381fc4d4a472a68becf772e0f2c2c776152143c5"; };
    build-system = [ py.setuptools ];
    doCheck = false;
  };
  model = name: hash: fetchurl { url = "https://github.com/liebharc/homr/releases/download/onnx_checkpoints/${name}.zip"; inherit hash; };
  segnet = model "segnet_308-3296ccd40960f90ca6ab9c035cca945675d30a0f" "sha256-HUJ3NUqDl6aDDvEnkjLm2YnC0lS3RRUl5T/z03VLH3A=";
  segnet16 = model "segnet_308-3296ccd40960f90ca6ab9c035cca945675d30a0f_fp16" "sha256-jQWjf+doKWc7yd7wp8rxaOWGCqTRqPesG2Ejqmn+PYI="; # used on Apple Silicon (CoreML)
  encoder = model "encoder_pytorch_model_396-f6feedb42ff90087d898b0941a55d040fa6b2903" "sha256-nZvETaaMEYDIUXPXOe2y1wPZDA27363J6/ZjZoWlSJs=";
  decoder = model "decoder_pytorch_model_396-f6feedb42ff90087d898b0941a55d040fa6b2903" "sha256-Ci8CPh7PQfX5afLtTvgMBQzimkmWxmVQVs82xhBGd+g=";
in
py.buildPythonApplication rec {
  pname = "homr";
  version = "0.7.0";
  pyproject = true;
  src = fetchPypi { inherit pname version; sha256 = "4078b9e70c16a1250288d92e065528bbd8712617339749407f057aebab9cfb7d"; };
  postPatch = ''
    substituteInPlace pyproject.toml \
      --replace-fail 'requires = ["poetry-core>=1.0.0", "poetry-dynamic-versioning"]' 'requires = ["poetry-core>=1.0.0"]' \
      --replace-fail 'build-backend = "poetry_dynamic_versioning.backend"' 'build-backend = "poetry.core.masonry.api"'
  '';
  build-system = [ py.poetry-core ];
  dependencies = [ py.numpy py.opencv4 py.pillow py.typing-extensions musicxml py.rapidocr py.onnxruntime py.requests ];
  pythonRemoveDeps = [ "opencv-python-headless" "types-Pillow" ];
  pythonRelaxDeps = true;
  nativeBuildInputs = [ unzip ];
  postInstall = ''
    pkg=$out/${py.python.sitePackages}/homr
    unzip -q ${segnet} -d $pkg/segmentation
    unzip -q ${segnet16} -d $pkg/segmentation
    unzip -q ${encoder} -d $pkg/transformer
    unzip -q ${decoder} -d $pkg/transformer
  '';
  doCheck = false;
}
